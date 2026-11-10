"""체크카드 API 테스트 (product-spec 10절 TC-F-009, TC-E-005, TC-S-001/003/004 대응)."""
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.common.crypto import decrypt_card_number, luhn_valid
from app.main import app
from tests.conftest import PIN, new_user_session, open_account, sql
from tests.test_transfer import assert_ledger_consistent, balance, clone, fund

MASKED = re.compile(r"^\*{4} \*{4} \*{4} \d{4}$")


def issue(c, account_id, **kw):
    return c.post("/api/cards", json={"account_id": account_id, "card_network": "VISA", **kw})


def pay(c, card_id, amount, place="스타벅스 강남점", overseas=False):
    return c.post("/api/dev/card-payments", json={"card_id": card_id, "amount": amount, "place": place, "overseas": overseas})


def act(c, card_id, action, pin=PIN):
    return c.post(f"/api/cards/{card_id}/{action}", json={"pin": pin})


def counts(card_id, account_id):
    return (sql("SELECT count(*) AS n FROM card_payments WHERE card_id = %s", (card_id,))[0]["n"],
            sql("SELECT count(*) AS n FROM account_transactions WHERE account_id = %s", (account_id,))[0]["n"])


@pytest.fixture()
def ctx(client, outbox):
    """로그인한 사용자, 잔액 100만원 계좌, 발급된 카드 1장."""
    user = new_user_session(client, outbox)
    acc = open_account(client, nickname="카드 계좌")
    fund(acc["id"], 1_000_000)
    card = issue(client, acc["id"]).json()
    return {"c": client, "user": user, "acc": acc, "card": card}


# ---------- 발급 (D1.1) ----------

def test_issue_defaults_and_encrypted_storage(client, outbox):
    new_user_session(client, outbox)
    acc = open_account(client)
    res = issue(client, acc["id"])
    assert res.status_code == 201, res.text
    card = res.json()
    now = datetime.now(timezone.utc)
    assert MASKED.match(card["card_number_masked"]) and card["status"] == "ACTIVE"
    assert card["daily_limit"] == 1_000_000 and card["overseas_enabled"] is False  # 기본값
    assert card["expiry_date"] == f"{now.month:02d}/{(now.year + 5) % 100:02d}" and card["card_network"] == "VISA"
    assert "card_number" not in card
    stored = sql("SELECT card_number FROM cards WHERE id = %s", (card["id"],))[0]["card_number"]
    assert not re.fullmatch(r"\d{16}", stored)  # 평문이 아니라 암호문이 저장된다
    number = decrypt_card_number(stored)
    assert re.fullmatch(r"\d{16}", number) and luhn_valid(number) and number.startswith("4")
    assert number.endswith(card["last4"])


def test_network_prefixes(client, outbox):
    new_user_session(client, outbox)
    for network, prefix in (("MASTER", "5"), ("LOCAL", "9")):
        acc = open_account(client)
        card = issue(client, acc["id"], card_network=network).json()
        stored = sql("SELECT card_number FROM cards WHERE id = %s", (card["id"],))[0]["card_number"]
        assert decrypt_card_number(stored).startswith(prefix)


def test_issue_validations(client, outbox):
    new_user_session(client, outbox)
    acc = open_account(client)
    assert issue(client, acc["id"], daily_limit=5_000).json()["field"] == "daily_limit"
    assert issue(client, acc["id"], card_network="AMEX").status_code == 400
    assert issue(client, str(uuid.uuid4())).status_code == 404
    stranger = TestClient(app)
    new_user_session(stranger, outbox)
    assert issue(stranger, acc["id"]).status_code == 404  # 남의 계좌에는 발급 불가
    assert issue(TestClient(app), acc["id"]).status_code == 401
    assert issue(client, acc["id"]).status_code == 201
    res = issue(client, acc["id"])  # 계좌당 1장
    assert res.status_code == 409 and res.json()["code"] == "CARD_ALREADY_EXISTS"


def test_issue_blocked_for_suspended_or_closed_account(client, outbox):
    new_user_session(client, outbox)
    for status in ("SUSPENDED", "CLOSED"):
        acc = open_account(client)
        sql("UPDATE accounts SET status = %s WHERE id = %s", (status, acc["id"]))
        res = issue(client, acc["id"])
        assert res.status_code == 400 and res.json()["code"] == "ACCOUNT_STATUS_BLOCKED"


def test_concurrent_issue_creates_one_card(client, outbox):
    new_user_session(client, outbox)
    acc = open_account(client)
    clients = [clone(client) for _ in range(6)]
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda c: issue(c, acc["id"]), clients))
    assert sorted(r.status_code for r in results) == [201] + [409] * 5
    assert sql("SELECT count(*) AS n FROM cards WHERE account_id = %s", (acc["id"],))[0]["n"] == 1


# ---------- 조회·접근 제어 (D1.2~D1.3, B5.1) ----------

def test_list_and_detail_hide_full_number_and_check_owner(ctx, outbox):
    c, card = ctx["c"], ctx["card"]
    items = c.get("/api/cards").json()
    assert len(items) == 1 and MASKED.match(items[0]["card_number_masked"])
    assert all("card_number" not in i for i in items)
    detail = c.get(f"/api/cards/{card['id']}").json()
    assert detail["account_nickname"] == "카드 계좌" and detail["used_today"] == 0 and detail["remaining_today"] == 1_000_000
    stranger = TestClient(app)
    new_user_session(stranger, outbox)
    assert stranger.get("/api/cards").json() == []
    for method, path, body in [("get", f"/api/cards/{card['id']}", None), ("get", f"/api/cards/{card['id']}/payments", None),
                               ("post", f"/api/cards/{card['id']}/suspend", {"pin": PIN}),
                               ("post", f"/api/cards/{card['id']}/cancel", {"pin": PIN}),
                               ("patch", f"/api/cards/{card['id']}/settings", {"daily_limit": 50000, "pin": PIN}),
                               ("post", f"/api/dev/card-payments", {"card_id": card["id"], "amount": 1000, "place": "도용"})]:
        res = getattr(stranger, method)(path, **({"json": body} if body else {}))
        assert res.status_code == 404, path
    assert TestClient(app).get("/api/cards").status_code == 401


# ---------- 설정 변경 (D1.3) ----------

def test_change_settings_requires_pin_and_valid_values(ctx):
    c, card = ctx["c"], ctx["card"]
    url = f"/api/cards/{card['id']}/settings"
    res = c.patch(url, json={"daily_limit": 300_000, "pin": "000000"})
    assert res.status_code == 401 and res.json()["code"] == "INVALID_PIN"
    assert c.get(f"/api/cards/{card['id']}").json()["daily_limit"] == 1_000_000  # 인증 실패 시 변경 없음
    assert c.patch(url, json={"pin": PIN}).status_code == 400  # 바꿀 항목 없음
    assert c.patch(url, json={"daily_limit": 1_000, "pin": PIN}).status_code == 400
    res = c.patch(url, json={"daily_limit": 300_000, "overseas_enabled": True, "pin": PIN})
    assert res.status_code == 200 and res.json()["daily_limit"] == 300_000 and res.json()["overseas_enabled"] is True
    res = c.patch(url, json={"overseas_enabled": False, "pin": PIN})  # 일부 항목만 변경
    assert res.json()["daily_limit"] == 300_000 and res.json()["overseas_enabled"] is False
    act(c, card["id"], "suspend")
    assert c.patch(url, json={"daily_limit": 100_000, "pin": PIN}).status_code == 409  # 정상 카드만 변경 가능


# ---------- 상태 전이 (D1.3, D1.7, D1.8) ----------

def test_suspend_resume_lost_cancel_flow(ctx):
    c, card, acc = ctx["c"], ctx["card"], ctx["acc"]
    cid = card["id"]
    for action in ("suspend", "report-lost", "cancel", "reissue"):  # 정상 카드에서 가능한 동작(4회 실패는 잠금 전)
        res = act(c, cid, action, pin="000000")
        assert res.status_code == 401 and res.json()["code"] == "INVALID_PIN", action
    assert c.get(f"/api/cards/{cid}").json()["status"] == "ACTIVE"  # 인증 실패 시 상태 그대로

    assert act(c, cid, "resume").status_code == 409  # 정상 카드는 해제할 게 없음
    assert act(c, cid, "suspend").json()["status"] == "SUSPENDED"
    assert act(c, cid, "suspend").status_code == 409
    assert act(c, cid, "resume").json()["status"] == "ACTIVE"
    assert act(c, cid, "suspend").status_code == 200
    assert act(c, cid, "report-lost").json()["status"] == "LOST"  # 정지 중에도 분실 신고 가능
    assert act(c, cid, "resume").status_code == 409  # 분실은 해제 불가
    assert act(c, cid, "report-lost").status_code == 409
    assert act(c, cid, "cancel").json()["status"] == "CANCELED"
    assert act(c, cid, "cancel").status_code == 409 and act(c, cid, "reissue").status_code == 409
    assert issue(c, acc["id"]).status_code == 201  # 해지하면 같은 계좌에 새로 발급할 수 있다


def test_suspended_account_blocks_resume_but_not_lost_report(ctx):
    c, card, acc = ctx["c"], ctx["card"], ctx["acc"]
    act(c, card["id"], "suspend")
    sql("UPDATE accounts SET status = 'SUSPENDED' WHERE id = %s", (acc["id"],))
    res = act(c, card["id"], "resume")
    assert res.status_code == 400 and res.json()["code"] == "ACCOUNT_STATUS_BLOCKED"
    assert act(c, card["id"], "report-lost").status_code == 200  # 분실 신고는 계좌 상태와 상관없이 가능


# ---------- 재발급 (D1.4) ----------

def test_reissue_links_old_card_and_inherits_settings(ctx):
    c, card, acc = ctx["c"], ctx["card"], ctx["acc"]
    c.patch(f"/api/cards/{card['id']}/settings", json={"daily_limit": 400_000, "overseas_enabled": True, "pin": PIN})
    act(c, card["id"], "report-lost")
    res = act(c, card["id"], "reissue")
    assert res.status_code == 201
    new = res.json()
    assert new["id"] != card["id"] and new["status"] == "ACTIVE" and new["reissued_from_id"] == card["id"]
    assert new["daily_limit"] == 400_000 and new["overseas_enabled"] is True and new["card_network"] == "VISA"
    assert new["last4"] != card["last4"] or new["card_number_masked"] is not None
    assert c.get(f"/api/cards/{card['id']}").json()["status"] == "REISSUED"
    assert [i["id"] for i in c.get("/api/cards").json()] == [new["id"]]  # 목록에는 사용 가능한 카드만
    assert {i["id"] for i in c.get("/api/cards?include_inactive=true").json()} == {card["id"], new["id"]}
    assert act(c, card["id"], "reissue").status_code == 409  # 재발급된 카드는 다시 재발급 불가
    usable = sql("SELECT count(*) AS n FROM cards WHERE account_id = %s AND status IN ('ACTIVE','SUSPENDED','LOST')", (acc["id"],))[0]["n"]
    assert usable == 1


# ---------- 결제 시뮬레이터 (DEV-1, D1.5) ----------

def test_payment_updates_balance_ledger_and_notification(ctx):
    c, card, acc, user = ctx["c"], ctx["card"], ctx["acc"], ctx["user"]
    res = pay(c, card["id"], 5_600)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["balance_after"] == 994_400 and balance(acc["id"]) == 994_400
    row = sql("SELECT * FROM account_transactions WHERE card_payment_id = %s", (body["id"],))[0]
    assert (row["transaction_type"], row["transaction_direction"], row["amount"], row["new_balance"]) == ("CARD", "OUT", 5_600, 994_400)
    assert row["counterparty_name"] == "스타벅스 강남점" and str(row["account_id"]) == acc["id"]
    p = sql("SELECT * FROM card_payments WHERE id = %s", (body["id"],))[0]
    assert p["place"] == "스타벅스 강남점" and p["complete_at"] is not None
    note = sql("SELECT type, message FROM notifications WHERE user_id = %s AND type = 'CARD_PAYMENT'", (user["id"],))[0]
    assert "스타벅스 강남점" in note["message"] and "5,600" in note["message"] and card["last4"] in note["message"]
    listed = c.get(f"/api/cards/{card['id']}/payments").json()
    assert listed["total"] == 1 and listed["items"][0]["amount"] == 5_600
    tx = c.get(f"/api/accounts/{acc['id']}/transactions?type=CARD").json()
    assert tx["total"] == 1 and tx["items"][0]["counterparty_name"] == "스타벅스 강남점"
    assert_ledger_consistent(acc["id"])


def test_payment_rejections_leave_no_trace(ctx):
    c, card, acc = ctx["c"], ctx["card"], ctx["acc"]
    cid, aid = card["id"], acc["id"]

    def rejected(code, *args, **kw):
        before = counts(cid, aid), balance(aid)
        res = pay(c, cid, *args, **kw)
        assert res.status_code == 400 and res.json()["code"] == code, res.text
        assert (counts(cid, aid), balance(aid)) == before  # 결제·원장·잔액 변화 없음

    rejected("INSUFFICIENT_BALANCE", 2_000_000)
    rejected("OVERSEAS_DISABLED", 1_000, overseas=True)  # 해외결제 꺼진 카드의 해외 가맹점
    act(c, cid, "suspend")
    rejected("CARD_STATUS_BLOCKED", 1_000)
    act(c, cid, "resume")
    sql("UPDATE accounts SET status = 'SUSPENDED' WHERE id = %s", (aid,))
    rejected("ACCOUNT_STATUS_BLOCKED", 1_000)
    sql("UPDATE accounts SET status = 'ACTIVE' WHERE id = %s", (aid,))
    act(c, cid, "report-lost")
    rejected("CARD_STATUS_BLOCKED", 1_000)
    assert pay(c, cid, 0).status_code == 400 and pay(c, cid, 1_000, place="  ").status_code == 400


def test_overseas_payment_allowed_when_enabled(ctx):
    c, card = ctx["c"], ctx["card"]
    c.patch(f"/api/cards/{card['id']}/settings", json={"overseas_enabled": True, "pin": PIN})
    assert pay(c, card["id"], 30_000, place="Tokyo Cafe", overseas=True).status_code == 201


def test_card_daily_limit_counts_todays_payments(ctx):
    c, card = ctx["c"], ctx["card"]
    c.patch(f"/api/cards/{card['id']}/settings", json={"daily_limit": 100_000, "pin": PIN})
    assert pay(c, card["id"], 60_000).status_code == 201
    res = pay(c, card["id"], 50_000)
    assert res.status_code == 400 and res.json()["code"] == "LIMIT_EXCEEDED" and "40,000" in res.json()["message"]
    detail = c.get(f"/api/cards/{card['id']}").json()
    assert detail["used_today"] == 60_000 and detail["remaining_today"] == 40_000
    assert pay(c, card["id"], 40_000).status_code == 201  # 한도 경계까지는 가능


def test_concurrent_payments_never_overdraw(ctx):
    c, card, acc = ctx["c"], ctx["card"], ctx["acc"]
    sql("UPDATE cards SET daily_limit = 10000000 WHERE id = %s", (card["id"],))
    clients = [clone(c) for _ in range(6)]
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda x: pay(x, card["id"], 400_000), clients))
    assert len([r for r in results if r.status_code == 201]) == 2  # 100만원으로 40만원은 2번만
    assert all(r.json()["code"] == "INSUFFICIENT_BALANCE" for r in results if r.status_code != 201)
    assert balance(acc["id"]) == 200_000
    assert_ledger_consistent(acc["id"])


def test_payment_and_transfer_race_does_not_deadlock_or_overdraw(ctx, outbox):
    c, card, acc = ctx["c"], ctx["card"], ctx["acc"]
    other = TestClient(app)
    new_user_session(other, outbox)
    b = open_account(other)
    jobs = [("pay", clone(c)) for _ in range(5)] + [("xfer", clone(c)) for _ in range(5)]

    def run(job):
        kind, cl = job
        if kind == "pay":
            return pay(cl, card["id"], 10_000).status_code
        return cl.post("/api/transfers", json={"from_account_id": acc["id"], "to_account_num": b["account_num"],
                                               "amount": 10_000, "pin": PIN}, headers={"Idempotency-Key": uuid.uuid4().hex}).status_code
    with ThreadPoolExecutor(10) as pool:
        codes = list(pool.map(run, jobs))
    assert codes == [201] * 10
    assert balance(acc["id"]) == 1_000_000 - 100_000 and balance(b["id"]) == 50_000
    assert_ledger_consistent(acc["id"])


# ---------- 계좌 해지와의 연동 (B4.1) ----------

def test_card_blocks_account_close_until_canceled(ctx):
    c, card, acc = ctx["c"], ctx["card"], ctx["acc"]
    sql("UPDATE accounts SET balance = 0 WHERE id = %s", (acc["id"],))
    codes = lambda: {r["code"] for r in c.get(f"/api/accounts/{acc['id']}/close-check").json()["reasons"]}
    assert codes() == {"CARD_LINKED"}
    act(c, card["id"], "suspend")
    assert codes() == {"CARD_LINKED"}  # 정지 카드도 연결 서비스
    act(c, card["id"], "report-lost")
    assert codes() == {"CARD_LINKED"}  # 분실 카드도 해지 전까지는 연결 서비스
    act(c, card["id"], "cancel")
    assert codes() == set()
    assert c.post(f"/api/accounts/{acc['id']}/close", json={"pin": PIN}).status_code == 200


# ---------- 입금 시뮬레이터 (DEV-2) ----------

def test_deposit_simulator(client, outbox):
    new_user_session(client, outbox)
    acc = open_account(client)
    res = client.post("/api/dev/deposits", json={"account_id": acc["id"], "amount": 250_000, "counterparty_name": "(주)가상회사", "memo": "급여"})
    assert res.status_code == 201 and res.json()["balance"] == 250_000 and balance(acc["id"]) == 250_000
    row = sql("SELECT * FROM account_transactions WHERE account_id = %s", (acc["id"],))[0]
    assert (row["transaction_type"], row["transaction_direction"], row["new_balance"], row["memo"]) == ("DEPOSIT", "IN", 250_000, "급여")
    assert client.post("/api/dev/deposits", json={"account_id": acc["id"], "amount": 0}).status_code == 400
    sql("UPDATE accounts SET status = 'SUSPENDED' WHERE id = %s", (acc["id"],))
    assert client.post("/api/dev/deposits", json={"account_id": acc["id"], "amount": 1000}).status_code == 400  # 거래중지 계좌는 입금도 차단
    stranger = TestClient(app)
    new_user_session(stranger, outbox)
    assert stranger.post("/api/dev/deposits", json={"account_id": acc["id"], "amount": 1000}).status_code == 404


def test_dev_endpoints_are_blocked_outside_dev(ctx, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "app_env", "prod")
    c, card, acc = ctx["c"], ctx["card"], ctx["acc"]
    assert pay(c, card["id"], 1_000).status_code == 404
    assert c.post("/api/dev/deposits", json={"account_id": acc["id"], "amount": 1000}).status_code == 404


# ---------- 알림 (D1.5) ----------

def test_notifications_list_and_read(ctx, outbox):
    c, card = ctx["c"], ctx["card"]
    pay(c, card["id"], 1_000, place="가맹점A")
    pay(c, card["id"], 2_000, place="가맹점B")
    res = c.get("/api/notifications").json()
    assert res["unread_count"] == 2 and [n["type"] for n in res["items"]] == ["CARD_PAYMENT", "CARD_PAYMENT"]
    assert "가맹점B" in res["items"][0]["message"]  # 최신순
    first = res["items"][0]["id"]
    assert c.put(f"/api/notifications/{first}/read").json()["read_at"] is not None
    assert c.get("/api/notifications?unread=true").json()["unread_count"] == 1
    assert len(c.get("/api/notifications?unread=true").json()["items"]) == 1
    stranger = TestClient(app)
    new_user_session(stranger, outbox)
    assert stranger.put(f"/api/notifications/{first}/read").status_code == 404  # 남의 알림은 읽음 처리 불가
    assert stranger.get("/api/notifications").json()["items"] == []
    assert c.put("/api/notifications/read-all").json()["updated"] == 1
    assert c.get("/api/notifications").json()["unread_count"] == 0
    assert TestClient(app).get("/api/notifications").status_code == 401
