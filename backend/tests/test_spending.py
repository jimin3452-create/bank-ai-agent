"""소비 API 테스트 (agent-spec 9절 인수 기준, TC-AG-016/017 대응).

소비 = 카드 결제(완료) + 타인 명의 계좌로의 성공한 이체. 본인 계좌 간 이체·입금·일반 출금은 포함하지 않는다.
"""
import calendar
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.spending.merchant import merchant_key, strip_branch
from app.spending.service import KST, parse_month, prev_month, today_kst
from tests.conftest import PIN, new_user_session, open_account, sql
from tests.test_card import issue, pay
from tests.test_transfer import clone, fund, send

NOW_MONTH = today_kst().strftime("%Y-%m")
PREV = prev_month(parse_month(NOW_MONTH))
PREV_MONTH = PREV.strftime("%Y-%m")


def prev_at(day=15, hour=12) -> datetime:
    return datetime(PREV.year, PREV.month, day, hour, tzinfo=KST)


def hist_card(card_id, account_id, amount, place, at, complete=True):
    """과거 시점의 카드 결제(+원장)를 직접 넣는다. complete=False는 결제 미완료 건."""
    pid = sql("INSERT INTO card_payments (card_id, amount, place, request_at, complete_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
              (card_id, amount, place, at, at if complete else None))[0]["id"]
    sql("INSERT INTO account_transactions (account_id, card_payment_id, transaction_type, transaction_direction, amount, "
        "new_balance, counterparty_name, transaction_at) VALUES (%s,%s,'CARD','OUT',%s,0,%s,%s)", (account_id, pid, amount, place, at))


def hist_transfer(src, dst, amount, at, status="SUCCESS", name="받는 분"):
    tid = uuid.uuid4()
    sql("INSERT INTO transfers (id, idempotency_key, from_account_id, to_account_id, amount, status, request_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (tid, uuid.uuid4().hex, src, dst, amount, status, at))
    sql("INSERT INTO account_transactions (account_id, transfer_id, transaction_type, transaction_direction, amount, new_balance, "
        "counterparty_name, transaction_at) VALUES (%s,%s,'TRANSFER','OUT',%s,0,%s,%s)", (src, tid, amount, name, at))


@pytest.fixture()
def world(client, outbox):
    """A: 계좌 2개(a1에 카드, 잔액 500만원) / B: 계좌 1개. client는 A로 로그인."""
    user_a = new_user_session(client, outbox)
    a1, a2 = open_account(client, nickname="주계좌"), open_account(client, nickname="비상금")
    fund(a1["id"], 5_000_000)
    sql("UPDATE accounts SET daily_limit = 10000000, month_limit = 50000000 WHERE id = %s", (a1["id"],))
    card = issue(client, a1["id"]).json()
    sql("UPDATE cards SET daily_limit = 10000000 WHERE id = %s", (card["id"],))
    other = TestClient(app)
    new_user_session(other, outbox)
    b1 = open_account(other, nickname="받는 계좌")
    return {"A": client, "B": other, "a1": a1, "a2": a2, "b1": b1, "card": card, "user_a": user_a}


def alerts(user_id):
    return [r["message"] for r in sql("SELECT message FROM notifications WHERE user_id = %s AND type = 'BUDGET_ALERT' ORDER BY id", (user_id,))]


# ---------- 가맹점 정규화 ----------

def test_merchant_normalization():
    assert strip_branch("스타벅스 강남점") == "스타벅스" and strip_branch("스타벅스 선릉역점") == "스타벅스"
    assert strip_branch("GS25 역삼점") == "GS25" and strip_branch("메가커피 홍대점") == "메가커피"
    assert strip_branch("달빛 서점") == "달빛 서점"  # 한 글자 + '점'은 가맹점명의 일부
    assert merchant_key("GS25 역삼점") == "gs25" and merchant_key("SKT 통신요금") == "skt통신요금"
    assert merchant_key("카카오T") == "카카오t" and merchant_key("365치과 강남점") == "365치과"
    assert merchant_key("스타벅스 강남점") == merchant_key("스타벅스 역삼점") == merchant_key("스타벅스")


# ---------- 소비의 정의 (TC-AG-016, TC-AG-017) ----------

def test_consumption_is_card_plus_transfer_to_others_only(world):
    a, a1, a2, b1, card = world["A"], world["a1"], world["a2"], world["b1"], world["card"]
    assert pay(a, card["id"], 5_600, "스타벅스 강남점").status_code == 201
    assert pay(a, card["id"], 12_000, "맥도날드 역삼점").status_code == 201
    assert send(a, a1["id"], b1["account_num"], 50_000, memo="월세").status_code == 201          # 타인 이체: 소비
    assert send(a, a1["id"], a2["account_num"], 30_000).status_code == 201                         # 본인 계좌 간: 제외
    assert send(a, a1["id"], b1["account_num"], 900_000_000).status_code == 400                    # 실패한 이체: 제외
    a.post("/api/dev/deposits", json={"account_id": a1["id"], "amount": 1_000_000})               # 입금: 제외
    now = datetime.now(timezone.utc)
    hist_card(card["id"], a1["id"], 7_777, "결제 미완료 가맹점", now, complete=False)               # 결제 미완료: 제외
    sql("INSERT INTO account_transactions (account_id, transaction_type, transaction_direction, amount, new_balance, "
        "counterparty_name, transaction_at) VALUES (%s,'WITHDRAW','OUT',3333,0,'ATM',%s)", (a1["id"], now))  # 일반 출금: 제외
    hist_transfer(a1["id"], b1["id"], 4_444, now, status="FAILED")                                  # 실패 이체 원장: 제외

    s = a.get("/api/spending/summary").json()
    assert s["total"] == 67_600 and s["count"] == 3
    assert (s["card_total"], s["card_count"]) == (17_600, 2) and (s["transfer_other_total"], s["transfer_other_count"]) == (50_000, 1)
    cats = a.get("/api/spending/by-category").json()
    by = {i["code"]: i for i in cats["items"]}
    assert by["CAFE"]["amount"] == 5_600 and by["FOOD"]["amount"] == 12_000 and by["TRANSFER"]["amount"] == 50_000
    assert sum(i["amount"] for i in cats["items"]) == cats["total"] == s["total"]  # 카테고리 합계 = 총소비
    assert abs(sum(i["share"] for i in cats["items"]) - 100) < 0.5
    assert [i["code"] for i in cats["items"]] == ["TRANSFER", "FOOD", "CAFE"]  # 금액 큰 순

    other = world["B"].get("/api/spending/summary").json()  # 받은 돈은 B의 소비가 아니다
    assert other["total"] == 0 and other["count"] == 0
    assert TestClient(app).get("/api/spending/summary").status_code == 401


def test_transactions_list_with_category_filter_and_paging(world):
    a, a1, b1, card = world["A"], world["a1"], world["b1"], world["card"]
    for place, amount in [("스타벅스 강남점", 5_600), ("메가커피 홍대점", 4_100), ("맥도날드 역삼점", 12_000)]:
        pay(a, card["id"], amount, place)
    send(a, a1["id"], b1["account_num"], 20_000, memo="친구")
    res = a.get("/api/spending/transactions").json()
    assert res["total"] == 4 and res["items"][0]["kind"] == "TRANSFER_OTHER"  # 최신순
    cafe = a.get("/api/spending/transactions?category=CAFE").json()
    assert cafe["total"] == 2 and {i["merchant"] for i in cafe["items"]} == {"스타벅스", "메가커피"}
    assert all(i["category_name"] == "카페·간식" and i["classified"] for i in cafe["items"])
    page = a.get("/api/spending/transactions?size=2&page=2").json()
    assert page["total"] == 4 and len(page["items"]) == 2
    assert a.get("/api/spending/transactions?category=NOPE").status_code == 400
    assert a.get("/api/spending/summary?month=2026-13").status_code == 400


# ---------- 가맹점 분류·보정 (E5) ----------

def test_unclassified_merchants_default_to_etc_until_user_fixes_them(world):
    a, b, card = world["A"], world["B"], world["card"]
    pay(a, card["id"], 8_000, "동네서점 강남점")
    pay(a, card["id"], 9_000, "동네서점 역삼점")
    summary = a.get("/api/spending/by-category").json()
    assert [(i["code"], i["amount"]) for i in summary["items"]] == [("ETC", 17_000)]  # 미분류는 '기타'
    un = a.get("/api/spending/unclassified").json()["items"]
    assert len(un) == 1 and un[0]["merchant"] == "동네서점" and un[0]["amount"] == 17_000 and un[0]["count"] == 2

    res = a.put("/api/spending/merchant-category", json={"merchant": "동네서점 신촌점", "category_code": "CULTURE"})
    assert res.status_code == 200 and res.json()["source"] == "USER"  # 지점이 달라도 같은 가맹점
    after = a.get("/api/spending/by-category").json()
    assert [(i["code"], i["amount"]) for i in after["items"]] == [("CULTURE", 17_000)]
    assert a.get("/api/spending/unclassified").json()["items"] == []
    assert all(t["classified"] for t in a.get("/api/spending/transactions").json()["items"])
    # 보정은 그 회원에게만 적용된다
    b1 = world["b1"]
    sql("UPDATE accounts SET balance = 100000 WHERE id = %s", (b1["id"],))
    bcard = issue(b, b1["id"]).json()
    pay(b, bcard["id"], 3_000, "동네서점 강남점")
    assert [(i["code"], i["amount"]) for i in b.get("/api/spending/by-category").json()["items"]] == [("ETC", 3_000)]


def test_user_override_beats_rule_and_can_be_reverted(world):
    a, b, b1, card = world["A"], world["B"], world["b1"], world["card"]
    pay(a, card["id"], 5_000, "스타벅스 강남점")
    assert a.get("/api/spending/by-category").json()["items"][0]["code"] == "CAFE"  # 공통 룰
    a.put("/api/spending/merchant-category", json={"merchant": "스타벅스", "category_code": "FOOD"})
    assert a.get("/api/spending/by-category").json()["items"][0]["code"] == "FOOD"  # 사용자 보정 > 룰
    sql("UPDATE accounts SET balance = 100000 WHERE id = %s", (b1["id"],))
    bcard = issue(b, b1["id"]).json()
    pay(b, bcard["id"], 5_000, "스타벅스 역삼점")
    assert b.get("/api/spending/by-category").json()["items"][0]["code"] == "CAFE"  # 다른 회원은 그대로
    assert a.delete("/api/spending/merchant-category?merchant=스타벅스").status_code == 200
    assert a.get("/api/spending/by-category").json()["items"][0]["code"] == "CAFE"  # 되돌리면 룰로 복귀
    assert a.delete("/api/spending/merchant-category?merchant=스타벅스").status_code == 404
    assert a.delete("/api/spending/merchant-category?merchant=맥도날드").status_code == 404  # 공통 룰은 지울 수 없음


def test_merchant_category_validation(world):
    a = world["A"]
    for body, field in [({"merchant": "가게", "category_code": "TRANSFER"}, "category_code"),  # 이체 전용
                        ({"merchant": "가게", "category_code": "NOPE"}, "category_code"),
                        ({"merchant": "  ", "category_code": "FOOD"}, "merchant"),
                        ({"merchant": "", "category_code": "FOOD"}, "merchant")]:
        res = a.put("/api/spending/merchant-category", json=body)
        assert res.status_code == 400 and res.json()["field"] == field, body
    codes = [c["code"] for c in a.get("/api/spending/categories").json()]
    assert len(codes) == 11 and "TRANSFER" in codes and "ETC" in codes


# ---------- 기간 비교·가맹점·일별 (E1) ----------

def test_previous_month_comparison(world):
    a, a1, b1, card = world["A"], world["a1"], world["b1"], world["card"]
    hist_card(card["id"], a1["id"], 30_000, "스타벅스 강남점", prev_at(3))
    hist_card(card["id"], a1["id"], 20_000, "맥도날드 역삼점", prev_at(5))
    hist_transfer(a1["id"], b1["id"], 100_000, prev_at(1), name="박서준")
    pay(a, card["id"], 40_000, "스타벅스 강남점")
    pay(a, card["id"], 10_000, "맥도날드 역삼점")
    s = a.get("/api/spending/summary").json()
    assert s["total"] == 50_000 and s["prev_month"] == PREV_MONTH and s["prev_total"] == 150_000
    assert s["diff"] == -100_000 and s["diff_rate"] == -66.7
    cats = {i["code"]: i for i in a.get("/api/spending/by-category").json()["items"]}
    assert cats["CAFE"]["prev_amount"] == 30_000 and cats["CAFE"]["diff"] == 10_000 and cats["FOOD"]["diff"] == -10_000
    cmp = a.get(f"/api/spending/compare?month_a={PREV_MONTH}&month_b={NOW_MONTH}").json()
    assert (cmp["total_a"], cmp["total_b"], cmp["diff"]) == (150_000, 50_000, -100_000)
    assert cmp["items"][0]["code"] == "CAFE" and cmp["items"][0]["diff_rate"] == 33.3  # 증가가 큰 순
    assert {i["code"]: i["amount_b"] for i in cmp["items"]}["TRANSFER"] == 0
    empty = a.get("/api/spending/summary?month=2000-01").json()
    assert empty["total"] == 0 and empty["diff_rate"] is None  # 이전 달이 0이면 증감률 없음


def test_top_merchants_group_branches(world):
    a, a1, b1, card = world["A"], world["a1"], world["b1"], world["card"]
    pay(a, card["id"], 5_000, "스타벅스 강남점")
    pay(a, card["id"], 6_000, "스타벅스 역삼점")
    pay(a, card["id"], 9_000, "맥도날드 역삼점")
    send(a, a1["id"], b1["account_num"], 30_000)
    top = a.get("/api/spending/top-merchants?n=3").json()["items"]
    assert [(g["merchant"], g["amount"], g["count"]) for g in top] == [("테스트", 30_000, 1), ("스타벅스", 11_000, 2), ("맥도날드", 9_000, 1)]
    assert top[0]["category"] == "TRANSFER" and top[1]["category_name"] == "카페·간식"
    assert len(a.get("/api/spending/top-merchants?n=1").json()["items"]) == 1
    assert a.get("/api/spending/top-merchants?n=0").status_code == 400


def test_daily_fills_zero_days(world):
    a, card = world["A"], world["card"]
    pay(a, card["id"], 5_000, "스타벅스 강남점")
    cur = a.get("/api/spending/daily").json()["items"]
    assert len(cur) == today_kst().day and cur[-1]["amount"] == 5_000 and cur[-1]["date"] == today_kst().isoformat()
    assert sum(i["amount"] for i in cur) == 5_000
    sql("DELETE FROM account_transactions WHERE card_payment_id IS NOT NULL AND account_id = %s", (world["a1"]["id"],))
    hist_card(card["id"], world["a1"]["id"], 7_000, "맥도날드 역삼점", prev_at(10))
    prev = a.get(f"/api/spending/daily?month={PREV_MONTH}").json()["items"]
    assert len(prev) == calendar.monthrange(PREV.year, PREV.month)[1]  # 지난달은 말일까지 전부
    assert [i["amount"] for i in prev if i["amount"]] == [7_000] and prev[9]["amount"] == 7_000


# ---------- 예산 (E3) ----------

def test_budget_crud_and_usage(world):
    a, b, card = world["A"], world["B"], world["card"]
    pay(a, card["id"], 90_000, "맥도날드 역삼점")
    res = a.put("/api/budgets", json={"month": NOW_MONTH, "category_code": "FOOD", "amount": 100_000})
    assert res.status_code == 200
    food = res.json()
    assert food["spent"] == 90_000 and food["remaining"] == 10_000 and food["usage_pct"] == 90.0 and food["status"] == "WARN"
    a.put("/api/budgets", json={"month": NOW_MONTH, "amount": 1_000_000})  # 월 전체
    assert a.put("/api/budgets", json={"month": NOW_MONTH, "category_code": "FOOD", "amount": 80_000}).json()["status"] == "OVER"
    listed = a.get("/api/budgets").json()["items"]
    assert [i["category_name"] for i in listed] == ["월 전체", "식비"] and len(listed) == 2  # 같은 항목은 덮어씀
    total = listed[0]
    assert total["spent"] == 90_000 and total["status"] == "OK" and total["category_code"] is None
    assert a.get(f"/api/budgets?month={PREV_MONTH}").json()["items"] == []
    assert b.get("/api/budgets").json()["items"] == []  # 다른 회원 예산은 안 보임

    for body, field in [({"month": NOW_MONTH, "amount": 0}, "amount"), ({"month": "2026-13", "amount": 1000}, "month"),
                        ({"month": NOW_MONTH, "category_code": "NOPE", "amount": 1000}, "category_code"),
                        ({"month": NOW_MONTH, "amount": -5}, "amount")]:
        res = a.put("/api/budgets", json=body)
        assert res.status_code == 400 and res.json()["field"] == field, body
    bid = listed[1]["id"]
    assert b.delete(f"/api/budgets/{bid}").status_code == 404
    assert a.delete(f"/api/budgets/{bid}").status_code == 204
    assert len(a.get("/api/budgets").json()["items"]) == 1
    assert TestClient(app).get("/api/budgets").status_code == 401


# ---------- 예산 알림 (E4) ----------

def test_budget_alerts_fire_once_per_threshold(world):
    a, card, user = world["A"], world["card"], world["user_a"]
    a.put("/api/budgets", json={"month": NOW_MONTH, "category_code": "FOOD", "amount": 100_000})
    pay(a, card["id"], 79_000, "맥도날드 역삼점")
    assert alerts(user["id"]) == []
    pay(a, card["id"], 2_000, "맥도날드 역삼점")  # 81%
    assert len(alerts(user["id"])) == 1 and "80%" in alerts(user["id"])[0] and "식비" in alerts(user["id"])[0]
    pay(a, card["id"], 1_000, "맥도날드 역삼점")  # 같은 단계: 알림 없음
    assert len(alerts(user["id"])) == 1
    pay(a, card["id"], 19_000, "맥도날드 역삼점")  # 101%
    msgs = alerts(user["id"])
    assert len(msgs) == 2 and "100%" in msgs[1]
    pay(a, card["id"], 5_000, "맥도날드 역삼점")  # 더 넘어도 추가 알림 없음
    assert len(alerts(user["id"])) == 2
    assert a.get("/api/budgets").json()["items"][0]["alert_level"] == 100
    assert any(n["type"] == "BUDGET_ALERT" for n in a.get("/api/notifications").json()["items"])


def test_single_payment_crossing_both_thresholds_sends_both(world):
    a, card, user = world["A"], world["card"], world["user_a"]
    a.put("/api/budgets", json={"month": NOW_MONTH, "category_code": "CAFE", "amount": 10_000})
    pay(a, card["id"], 12_000, "스타벅스 강남점")
    msgs = alerts(user["id"])
    assert len(msgs) == 2 and "80%" in msgs[0] and "100%" in msgs[1] and all("카페·간식" in m for m in msgs)


def test_total_budget_counts_other_transfers_but_not_own(world):
    a, a1, a2, b1, user = world["A"], world["a1"], world["a2"], world["b1"], world["user_a"]
    a.put("/api/budgets", json={"month": NOW_MONTH, "amount": 100_000})
    assert send(a, a1["id"], a2["account_num"], 95_000).status_code == 201   # 본인 계좌 간: 소비 아님
    assert alerts(user["id"]) == []
    assert send(a, a1["id"], b1["account_num"], 85_000).status_code == 201   # 타인 이체: 85%
    msgs = alerts(user["id"])
    assert len(msgs) == 1 and "80%" in msgs[0] and "월 전체" in msgs[0]
    assert a.get("/api/budgets").json()["items"][0]["spent"] == 85_000


def test_setting_budget_after_exceeding_does_not_replay_alerts(world):
    a, card, user = world["A"], world["card"], world["user_a"]
    pay(a, card["id"], 50_000, "맥도날드 역삼점")
    res = a.put("/api/budgets", json={"month": NOW_MONTH, "category_code": "FOOD", "amount": 10_000})
    assert res.json()["status"] == "OVER" and res.json()["alert_level"] == 100
    pay(a, card["id"], 1_000, "맥도날드 역삼점")
    assert alerts(user["id"]) == []  # 이미 넘은 상태에서 정한 예산은 과거 알림을 보내지 않는다


def test_budget_of_other_month_is_not_alerted(world):
    a, card, user = world["A"], world["card"], world["user_a"]
    a.put("/api/budgets", json={"month": PREV_MONTH, "category_code": "FOOD", "amount": 1_000})
    pay(a, card["id"], 50_000, "맥도날드 역삼점")
    assert alerts(user["id"]) == []


def test_concurrent_payments_send_each_alert_once(world, outbox):
    a, a1, card, user = world["A"], world["a1"], world["card"], world["user_a"]
    a2 = world["a2"]
    fund(a2["id"], 5_000_000)
    sql("UPDATE accounts SET daily_limit = 10000000 WHERE id = %s", (a2["id"],))
    card2 = issue(a, a2["id"]).json()
    sql("UPDATE cards SET daily_limit = 10000000 WHERE id = %s", (card2["id"],))
    a.put("/api/budgets", json={"month": NOW_MONTH, "amount": 100_000})
    jobs = [(clone(a), card["id"] if i % 2 else card2["id"]) for i in range(6)]
    with ThreadPoolExecutor(6) as pool:
        codes = list(pool.map(lambda j: pay(j[0], j[1], 20_000, "맥도날드 역삼점").status_code, jobs))
    assert codes == [201] * 6  # 서로 다른 계좌·카드의 동시 결제도 교착 없이 처리
    msgs = alerts(user["id"])
    assert len(msgs) == 2 and sum("80%" in m for m in msgs) == 1 and sum("100%" in m for m in msgs) == 1
    assert a.get("/api/budgets").json()["items"][0]["spent"] == 120_000
