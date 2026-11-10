"""이체 API 테스트 (product-spec 10절 TC-F-005/006, TC-E-002/003/004/008, TC-S-001/003 대응)."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.account.service import today_kst
from app.config import settings
from app.main import app
from app.transfer.service import next_occurrence
from tests.conftest import PIN, new_user_session, open_account, sql


# ---------- 도우미 ----------

def clone(client) -> TestClient:
    """같은 로그인 상태(쿠키)를 가진 새 클라이언트. 동시 요청 테스트에 쓴다."""
    c = TestClient(app)
    c.cookies.set("access_token", client.cookies.get("access_token"))
    return c


def fund(account_id, amount):
    sql("UPDATE accounts SET balance = %s WHERE id = %s", (amount, account_id))


def balance(account_id) -> int:
    return sql("SELECT balance FROM accounts WHERE id = %s", (account_id,))[0]["balance"]


def send(client, from_id, to_num, amount, key=None, pin=PIN, memo=None):
    headers = {"Idempotency-Key": key or uuid.uuid4().hex}
    body = {"from_account_id": from_id, "to_account_num": to_num, "amount": amount, "pin": pin}
    if memo is not None:
        body["memo"] = memo
    return client.post("/api/transfers", json=body, headers=headers)


def transfers_of(account_id) -> int:
    return sql("SELECT count(*) AS n FROM transfers WHERE from_account_id = %s", (account_id,))[0]["n"]


def assert_ledger_consistent(account_id):
    """거래원장의 거래 후 잔액이 입출금 순서대로 이어지고 마지막 값이 계좌 잔액과 같은지 확인한다."""
    rows = sql("SELECT transaction_direction AS d, amount, new_balance FROM account_transactions "
               "WHERE account_id = %s ORDER BY id", (account_id,))
    prev = None
    for r in rows:
        if prev is not None:
            assert r["new_balance"] == (prev + r["amount"] if r["d"] == "IN" else prev - r["amount"]), "원장 잔액이 이어지지 않음"
        assert r["new_balance"] >= 0
        prev = r["new_balance"]
    if prev is not None:
        assert prev == balance(account_id)


@pytest.fixture()
def pair(client, outbox):
    """A(로그인한 client)의 계좌 2개와 B(다른 client)의 계좌 1개."""
    user_a = new_user_session(client, outbox)
    a1, a2 = open_account(client, nickname="출금"), open_account(client, nickname="내 다른 계좌")
    other = TestClient(app)
    user_b = new_user_session(other, outbox)
    b1 = open_account(other, nickname="받는 계좌")
    return {"A": client, "B": other, "a1": a1, "a2": a2, "b1": b1, "user_a": user_a, "user_b": user_b}


# ---------- 받는 분 확인 ----------

def test_lookup_masks_holder_and_rejects_unknown(pair):
    a, b1 = pair["A"], pair["b1"]
    res = a.get(f"/api/recipients/lookup?account_num={b1['account_num']}").json()
    assert res["holder_name_masked"] == "테*트" and res["is_mine"] is False and res["can_receive"] is True
    assert "*" in res["account_num_masked"] and "account_num" not in res
    assert a.get(f"/api/recipients/lookup?account_num={pair['a2']['account_num']}").json()["is_mine"] is True
    res = a.get("/api/recipients/lookup?account_num=999-9999-9999")
    assert res.status_code == 404 and res.json()["code"] == "RECIPIENT_NOT_FOUND"
    assert a.get("/api/recipients/lookup?account_num=abc").status_code == 400
    sql("UPDATE accounts SET status = 'CLOSED' WHERE id = %s", (b1["id"],))
    assert a.get(f"/api/recipients/lookup?account_num={b1['account_num']}").json()["can_receive"] is False


# ---------- 즉시이체 정상 흐름 (C1) ----------

def test_transfer_moves_money_and_writes_both_ledger_rows(pair):
    a, a1, b1 = pair["A"], pair["a1"], pair["b1"]
    fund(a1["id"], 500_000)
    fund(b1["id"], 10_000)
    res = send(a, a1["id"], b1["account_num"], 120_000, memo="점심값")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "SUCCESS" and body["balance_after"] == 380_000 and body["replayed"] is False
    assert body["to_holder_masked"] == "테*트" and "*" in body["to_account_num_masked"]
    assert balance(a1["id"]) == 380_000 and balance(b1["id"]) == 130_000
    out = sql("SELECT * FROM account_transactions WHERE account_id = %s", (a1["id"],))[0]
    inn = sql("SELECT * FROM account_transactions WHERE account_id = %s", (b1["id"],))[0]
    assert (out["transaction_type"], out["transaction_direction"], out["amount"], out["new_balance"]) == ("TRANSFER", "OUT", 120_000, 380_000)
    assert (inn["transaction_type"], inn["transaction_direction"], inn["new_balance"]) == ("TRANSFER", "IN", 130_000)
    assert out["transfer_id"] == inn["transfer_id"] and out["memo"] == "점심값"
    assert out["counterparty_account"] == b1["account_num"] and inn["counterparty_account"] == a1["account_num"]
    t = sql("SELECT * FROM transfers WHERE id = %s", (body["id"],))[0]
    assert t["status"] == "SUCCESS" and t["complete_at"] is not None and t["fail_reason"] is None
    assert a.get(f"/api/transfers/{body['id']}").json()["status"] == "SUCCESS"
    assert_ledger_consistent(a1["id"]) or assert_ledger_consistent(b1["id"])


def test_transfer_to_my_other_account(pair):
    a, a1, a2 = pair["A"], pair["a1"], pair["a2"]
    fund(a1["id"], 100_000)
    assert send(a, a1["id"], a2["account_num"], 30_000).status_code == 201
    assert balance(a1["id"]) == 70_000 and balance(a2["id"]) == 30_000


# ---------- 실패 상황 (TC-E-002) ----------

def test_wrong_pin_blocks_transfer_without_record(pair):
    a, a1, b1 = pair["A"], pair["a1"], pair["b1"]
    fund(a1["id"], 100_000)
    res = send(a, a1["id"], b1["account_num"], 1_000, pin="000000")
    assert res.status_code == 401 and res.json()["code"] == "INVALID_PIN"
    assert transfers_of(a1["id"]) == 0 and balance(a1["id"]) == 100_000 and balance(b1["id"]) == 0


def test_insufficient_balance_is_recorded_as_failed(pair):
    a, a1, b1 = pair["A"], pair["a1"], pair["b1"]
    fund(a1["id"], 5_000)
    res = send(a, a1["id"], b1["account_num"], 6_000)
    assert res.status_code == 400 and res.json()["code"] == "INSUFFICIENT_BALANCE"
    t = sql("SELECT status, fail_reason FROM transfers WHERE from_account_id = %s", (a1["id"],))[0]
    assert t["status"] == "FAILED" and "잔액" in t["fail_reason"]
    assert balance(a1["id"]) == 5_000 and balance(b1["id"]) == 0
    assert sql("SELECT count(*) AS n FROM account_transactions WHERE account_id IN (%s, %s)", (a1["id"], b1["id"]))[0]["n"] == 0


def test_daily_and_month_limits_count_pending_too(pair):
    a, a1, b1 = pair["A"], pair["a1"], pair["b1"]
    fund(a1["id"], 2_000_000)
    sql("UPDATE accounts SET daily_limit = 300000, month_limit = 5000000 WHERE id = %s", (a1["id"],))
    assert send(a, a1["id"], b1["account_num"], 200_000).status_code == 201
    res = send(a, a1["id"], b1["account_num"], 150_000)
    assert res.status_code == 400 and res.json()["code"] == "LIMIT_EXCEEDED" and "100,000" in res.json()["message"]
    sql("INSERT INTO transfers (id, idempotency_key, from_account_id, to_account_id, amount, status, request_at) "
        "VALUES (%s,%s,%s,%s,100000,'PENDING', now())", (uuid.uuid4(), uuid.uuid4().hex, a1["id"], b1["id"]))
    assert send(a, a1["id"], b1["account_num"], 100_000).status_code == 400  # 처리중 이체도 한도에 포함
    assert balance(a1["id"]) == 1_800_000

    sql("UPDATE accounts SET daily_limit = 5000000, month_limit = 500000 WHERE id = %s", (a1["id"],))
    sql("UPDATE transfers SET status = 'FAILED' WHERE status = 'PENDING' AND from_account_id = %s", (a1["id"],))
    res = send(a, a1["id"], b1["account_num"], 400_000)
    assert res.status_code == 400 and "1달" in res.json()["message"] and "300,000" in res.json()["message"]


def test_blocked_source_or_recipient(pair):
    a, a1, b1 = pair["A"], pair["a1"], pair["b1"]
    fund(a1["id"], 100_000)
    sql("UPDATE accounts SET status = 'SUSPENDED' WHERE id = %s", (a1["id"],))
    res = send(a, a1["id"], b1["account_num"], 1_000)
    assert res.status_code == 400 and res.json()["code"] == "ACCOUNT_STATUS_BLOCKED"
    sql("UPDATE accounts SET status = 'ACTIVE' WHERE id = %s", (a1["id"],))
    sql("UPDATE accounts SET status = 'SUSPENDED' WHERE id = %s", (b1["id"],))
    res = send(a, a1["id"], b1["account_num"], 1_000)
    assert res.status_code == 400 and res.json()["code"] == "RECIPIENT_BLOCKED"  # 거래중지 계좌는 입금도 차단
    assert balance(a1["id"]) == 100_000 and balance(b1["id"]) == 0


def test_invalid_inputs_create_no_transfer(pair):
    a, a1, b1 = pair["A"], pair["a1"], pair["b1"]
    fund(a1["id"], 100_000)
    cases = [
        (send(a, a1["id"], b1["account_num"], 0), "amount"),
        (send(a, a1["id"], b1["account_num"], -5), "amount"),
        (send(a, a1["id"], b1["account_num"], 10, memo="가" * 101), "memo"),
        (send(a, a1["id"], "12345", 10), "to_account_num"),
        (send(a, a1["id"], "999-9999-9999", 10), "to_account_num"),  # 본 서비스에 없는 계좌 (TC-E-008)
        (send(a, a1["id"], a1["account_num"], 10), "to_account_num"),  # 같은 계좌
    ]
    for res, field in cases:
        assert res.status_code == 400 and res.json()["field"] == field, (field, res.text)
    body = {"from_account_id": a1["id"], "to_account_num": b1["account_num"], "amount": 10, "pin": PIN}
    assert a.post("/api/transfers", json=body).status_code == 400  # Idempotency-Key 없음
    assert a.post("/api/transfers", json=body, headers={"Idempotency-Key": "short"}).status_code == 400
    assert transfers_of(a1["id"]) == 0 and balance(a1["id"]) == 100_000


def test_access_control(pair):
    a, b, a1, b1 = pair["A"], pair["B"], pair["a1"], pair["b1"]
    fund(a1["id"], 100_000)
    res = send(b, a1["id"], b1["account_num"], 1_000)  # B가 A의 계좌에서 출금 시도
    assert res.status_code == 404 and balance(a1["id"]) == 100_000
    assert send(TestClient(app), a1["id"], b1["account_num"], 1_000).status_code == 401
    t = send(a, a1["id"], b1["account_num"], 1_000).json()
    assert b.get(f"/api/transfers/{t['id']}").status_code == 404  # 받는 사람도 보낸 사람의 이체 상세는 못 봄
    assert TestClient(app).get(f"/api/transfers/{t['id']}").status_code == 401


# ---------- 중복·응답 유실 (TC-E-003, TC-E-004) ----------

def test_same_key_is_processed_once_and_mismatch_rejected(pair):
    a, a1, b1 = pair["A"], pair["a1"], pair["b1"]
    fund(a1["id"], 100_000)
    key = "req-" + uuid.uuid4().hex
    first = send(a, a1["id"], b1["account_num"], 10_000, key=key)
    second = send(a, a1["id"], b1["account_num"], 10_000, key=key)
    assert first.status_code == 201 and second.status_code == 200
    assert second.json()["id"] == first.json()["id"] and second.json()["replayed"] is True
    assert balance(a1["id"]) == 90_000 and balance(b1["id"]) == 10_000  # 한 번만 처리
    assert sql("SELECT count(*) AS n FROM account_transactions WHERE account_id = %s", (a1["id"],))[0]["n"] == 1
    res = send(a, a1["id"], b1["account_num"], 20_000, key=key)  # 같은 키, 다른 금액
    assert res.status_code == 409 and res.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_lookup_result_by_key_after_lost_response(pair):
    a, b, a1, b1 = pair["A"], pair["B"], pair["a1"], pair["b1"]
    fund(a1["id"], 50_000)
    key = "lost-" + uuid.uuid4().hex
    send(a, a1["id"], b1["account_num"], 7_000, key=key)  # 응답을 못 받았다고 가정
    found = a.get(f"/api/transfers/by-key/{key}")
    assert found.status_code == 200 and found.json()["status"] == "SUCCESS" and found.json()["amount"] == 7_000
    assert b.get(f"/api/transfers/by-key/{key}").status_code == 404
    assert a.get("/api/transfers/by-key/no-such-key-123").status_code == 404
    assert send(a, a1["id"], b1["account_num"], 7_000, key=key).json()["replayed"] is True  # 재전송해도 추가 송금 없음
    assert balance(a1["id"]) == 43_000


def test_concurrent_same_key_creates_one_transfer(pair):
    a, a1, b1 = pair["A"], pair["a1"], pair["b1"]
    fund(a1["id"], 100_000)
    key = "same-" + uuid.uuid4().hex
    clients = [clone(a) for _ in range(6)]
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda c: send(c, a1["id"], b1["account_num"], 10_000, key=key), clients))
    assert sorted(r.status_code for r in results) == [200] * 5 + [201]
    assert len({r.json()["id"] for r in results}) == 1
    assert transfers_of(a1["id"]) == 1 and balance(a1["id"]) == 90_000
    assert_ledger_consistent(a1["id"])


def test_concurrent_transfers_never_overdraw(pair):
    a, a1, b1 = pair["A"], pair["a1"], pair["b1"]
    fund(a1["id"], 1_000_000)
    clients = [clone(a) for _ in range(6)]
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda c: send(c, a1["id"], b1["account_num"], 400_000), clients))
    ok = [r for r in results if r.status_code == 201]
    assert len(ok) == 2  # 1,000,000원으로 400,000원은 2번만 가능
    assert all(r.json()["code"] == "INSUFFICIENT_BALANCE" for r in results if r.status_code != 201)
    assert balance(a1["id"]) == 200_000 and balance(b1["id"]) == 800_000
    assert_ledger_consistent(a1["id"])
    assert_ledger_consistent(b1["id"])


def test_concurrent_transfers_respect_daily_limit(pair):
    a, a1, b1 = pair["A"], pair["a1"], pair["b1"]
    fund(a1["id"], 5_000_000)
    sql("UPDATE accounts SET daily_limit = 500000 WHERE id = %s", (a1["id"],))
    clients = [clone(a) for _ in range(6)]
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda c: send(c, a1["id"], b1["account_num"], 200_000), clients))
    assert len([r for r in results if r.status_code == 201]) == 2  # 한도 500,000원 안에서 200,000원 2번
    assert balance(a1["id"]) == 4_600_000


def test_opposite_direction_transfers_do_not_deadlock(pair):
    a, b, a1, b1 = pair["A"], pair["B"], pair["a1"], pair["b1"]
    fund(a1["id"], 1_000_000)
    fund(b1["id"], 1_000_000)
    jobs = [(clone(a), a1["id"], b1["account_num"]) for _ in range(5)] + [(clone(b), b1["id"], a1["account_num"]) for _ in range(5)]
    with ThreadPoolExecutor(10) as pool:
        results = list(pool.map(lambda j: send(j[0], j[1], j[2], 1_000), jobs))
    assert [r.status_code for r in results] == [201] * 10
    assert balance(a1["id"]) + balance(b1["id"]) == 2_000_000
    assert_ledger_consistent(a1["id"])
    assert_ledger_consistent(b1["id"])


# ---------- 최근·자주 쓰는 계좌 (C3) ----------

def test_recent_and_favorite_recipients(pair):
    a, b, a1, b1, a2 = pair["A"], pair["B"], pair["a1"], pair["b1"], pair["a2"]
    fund(a1["id"], 100_000)
    assert a.get("/api/recipients/recent").json() == []
    send(a, a1["id"], a2["account_num"], 1_000)
    send(a, a1["id"], b1["account_num"], 1_000)
    recent = a.get("/api/recipients/recent").json()
    assert [r["account_num"] for r in recent] == [b1["account_num"], a2["account_num"]]  # 최근 순
    assert recent[0]["holder_name_masked"] == "테*트"

    res = a.post("/api/recipients/favorites", json={"account_num": b1["account_num"], "alias": "친구"})
    assert res.status_code == 201 and res.json()["alias"] == "친구" and res.json()["holder_name_masked"] == "테*트"
    assert a.post("/api/recipients/favorites", json={"account_num": b1["account_num"]}).status_code == 409
    assert a.post("/api/recipients/favorites", json={"account_num": "999-9999-9999"}).status_code == 404
    fav_id = a.get("/api/recipients/favorites").json()[0]["id"]
    assert b.delete(f"/api/recipients/favorites/{fav_id}").status_code == 404  # 남의 즐겨찾기는 지울 수 없음
    assert a.delete(f"/api/recipients/favorites/{fav_id}").status_code == 204
    assert a.get("/api/recipients/favorites").json() == []


# ---------- 자동이체 날짜 계산 (C2.1) ----------

def test_next_occurrence_handles_month_end_and_weekdays():
    assert next_occurrence("MONTHLY", 31, date(2026, 10, 31)) == date(2026, 11, 30)  # 30일까지만 있는 달은 말일
    assert next_occurrence("MONTHLY", 31, date(2026, 11, 30)) == date(2026, 12, 31)
    assert next_occurrence("MONTHLY", 31, date(2027, 1, 31)) == date(2027, 2, 28)
    assert next_occurrence("MONTHLY", 15, date(2026, 12, 20)) == date(2027, 1, 15)
    assert next_occurrence("MONTHLY", 1, date(2026, 11, 1)) == date(2026, 12, 1)  # 기준일 '이후'
    assert next_occurrence("WEEKLY", 0, date(2026, 11, 10)) == date(2026, 11, 16)  # 화요일 다음 월요일
    assert next_occurrence("WEEKLY", 0, date(2026, 11, 9)) == date(2026, 11, 16)  # 월요일이면 다음 주 월요일


# ---------- 자동이체 등록·해지 ----------

def make_auto(client, a1, b1, **overrides):
    body = {"from_account_id": a1["id"], "to_account_num": b1["account_num"], "amount": 50_000, "memo": "월세",
            "cycle": "MONTHLY", "run_day": 31, "start_date": (today_kst() + timedelta(days=1)).isoformat(), "pin": PIN, **overrides}
    return client.post("/api/auto-transfers", json=body)


def test_auto_transfer_register_validations(pair):
    a, b, a1, b1 = pair["A"], pair["B"], pair["a1"], pair["b1"]
    tomorrow = today_kst() + timedelta(days=1)
    res = make_auto(a, a1, b1)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "ACTIVE" and body["next_run_date"] == next_occurrence("MONTHLY", 31, tomorrow - timedelta(days=1)).isoformat()
    assert "*" in body["to_account_num_masked"] and body["last_result"] is None
    for overrides, field in [
        ({"start_date": today_kst().isoformat()}, "start_date"),  # 등록 당일에는 실행되지 않음
        ({"cycle": "MONTHLY", "run_day": 0}, "run_day"), ({"cycle": "WEEKLY", "run_day": 7}, "run_day"),
        ({"cycle": "MONTHLY", "run_day": 32}, "run_day"),
        ({"end_date": (today_kst() - timedelta(days=1)).isoformat()}, "end_date"),
        ({"amount": 0}, "amount"), ({"to_account_num": a1["account_num"]}, "to_account_num"),
        ({"to_account_num": "999-9999-9999"}, "to_account_num"),
    ]:
        res = make_auto(a, a1, b1, **overrides)
        assert res.status_code == 400 and res.json()["field"] == field, (overrides, res.text)
    assert make_auto(a, a1, b1, pin="000000").status_code == 401
    assert make_auto(b, a1, b1).status_code == 404  # 남의 계좌로는 등록 불가
    # 시작일~종료일 사이에 실행일이 없는 경우
    res = make_auto(a, a1, b1, run_day=1, start_date=(today_kst() + timedelta(days=2)).isoformat(),
                    end_date=(today_kst() + timedelta(days=3)).isoformat())
    assert res.status_code == 400 if today_kst().day not in (29, 30) else True
    assert len(a.get("/api/auto-transfers").json()) == 1


def test_auto_transfer_cancel(pair):
    a, b, a1, b1 = pair["A"], pair["B"], pair["a1"], pair["b1"]
    auto_id = make_auto(a, a1, b1).json()["id"]
    assert a.post(f"/api/auto-transfers/{auto_id}/cancel", json={"pin": "000000"}).status_code == 401
    assert b.post(f"/api/auto-transfers/{auto_id}/cancel", json={"pin": PIN}).status_code == 404
    res = a.post(f"/api/auto-transfers/{auto_id}/cancel", json={"pin": PIN})
    assert res.status_code == 200 and res.json()["status"] == "CANCELED"
    assert a.post(f"/api/auto-transfers/{auto_id}/cancel", json={"pin": PIN}).status_code == 409


# ---------- 자동이체 실행 (스케줄러) ----------

def due_auto(pair, amount=50_000, **overrides):
    """오늘 실행 대상인 자동이체를 만든다(등록은 내일 이후만 가능하므로 날짜를 직접 당긴다)."""
    a, a1, b1 = pair["A"], pair["a1"], pair["b1"]
    auto_id = make_auto(a, a1, b1, amount=amount, cycle="MONTHLY", run_day=1, **overrides).json()["id"]
    sql("UPDATE auto_transfers SET next_run_date = %s WHERE id = %s", (today_kst(), auto_id))
    return auto_id


def run_scheduler(client, today=None):
    res = client.post("/api/dev/run-auto-transfers", json={"today": today.isoformat()} if today else {})
    assert res.status_code == 200, res.text
    return res.json()


def test_scheduler_runs_due_transfer_once_per_round(pair):
    a, a1, b1 = pair["A"], pair["a1"], pair["b1"]
    fund(a1["id"], 200_000)
    auto_id = due_auto(pair)
    results = run_scheduler(a)
    mine = [r for r in results if r["auto_transfer_id"] == auto_id]
    assert len(mine) == 1 and mine[0]["result"] == "SUCCESS" and mine[0]["status"] == "ACTIVE"
    assert balance(a1["id"]) == 150_000 and balance(b1["id"]) == 50_000
    t = sql("SELECT idempotency_key, auto_transfer_id FROM transfers WHERE auto_transfer_id = %s", (auto_id,))
    assert len(t) == 1 and t[0]["idempotency_key"] == f"auto:{auto_id}:{today_kst().isoformat()}"
    out = sql("SELECT transaction_type FROM account_transactions WHERE account_id = %s", (a1["id"],))
    assert [r["transaction_type"] for r in out] == ["AUTO_TRANSFER"]
    nxt = sql("SELECT next_run_date FROM auto_transfers WHERE id = %s", (auto_id,))[0]["next_run_date"]
    assert nxt > today_kst()
    assert not [r for r in run_scheduler(a) if r["auto_transfer_id"] == auto_id]  # 같은 회차는 다시 실행되지 않음
    listed = a.get("/api/auto-transfers").json()[0]
    assert listed["last_result"] == "SUCCESS"


def test_scheduler_same_round_never_pays_twice(pair):
    a, a1, b1 = pair["A"], pair["a1"], pair["b1"]
    fund(a1["id"], 200_000)
    auto_id = due_auto(pair)
    run_scheduler(a)
    sql("UPDATE auto_transfers SET next_run_date = %s WHERE id = %s", (today_kst(), auto_id))  # 같은 회차를 다시 실행하게 만든다
    again = [r for r in run_scheduler(a) if r["auto_transfer_id"] == auto_id]
    assert again and again[0]["replayed"] is True
    assert balance(a1["id"]) == 150_000  # 중복 방지 키 덕분에 추가 출금 없음
    assert sql("SELECT count(*) AS n FROM transfers WHERE auto_transfer_id = %s", (auto_id,))[0]["n"] == 1


def test_scheduler_concurrent_runners_pay_once(pair):
    a, a1, b1 = pair["A"], pair["a1"], pair["b1"]
    fund(a1["id"], 200_000)
    auto_id = due_auto(pair)
    clients = [clone(a) for _ in range(4)]
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(run_scheduler, clients))
    assert sql("SELECT count(*) AS n FROM transfers WHERE auto_transfer_id = %s", (auto_id,))[0]["n"] == 1
    assert balance(a1["id"]) == 150_000


def test_scheduler_failure_notifies_and_moves_on(pair):
    a, a1, user_a = pair["A"], pair["a1"], pair["user_a"]
    fund(a1["id"], 1_000)  # 잔액 부족
    auto_id = due_auto(pair)
    results = [r for r in run_scheduler(a) if r["auto_transfer_id"] == auto_id]
    assert results[0]["result"] == "FAILED" and results[0]["status"] == "ACTIVE"
    t = sql("SELECT status, fail_reason FROM transfers WHERE auto_transfer_id = %s", (auto_id,))[0]
    assert t["status"] == "FAILED" and "잔액" in t["fail_reason"]
    notes = sql("SELECT type, message FROM notifications WHERE user_id = %s", (user_a["id"],))
    assert [n["type"] for n in notes if n["type"] == "AUTO_TRANSFER_FAIL"] == ["AUTO_TRANSFER_FAIL"]
    assert sql("SELECT next_run_date FROM auto_transfers WHERE id = %s", (auto_id,))[0]["next_run_date"] > today_kst()  # 재시도 없이 다음 회차로
    assert balance(a1["id"]) == 1_000
    assert a.get("/api/auto-transfers").json()[0]["last_result"] == "FAILED"


def test_scheduler_ends_after_last_round_and_skips_missed_rounds(pair):
    a, a1 = pair["A"], pair["a1"]
    fund(a1["id"], 500_000)
    auto_id = due_auto(pair)
    sql("UPDATE auto_transfers SET end_date = %s WHERE id = %s", (today_kst() + timedelta(days=5), auto_id))
    results = [r for r in run_scheduler(a) if r["auto_transfer_id"] == auto_id]
    assert results[0]["status"] == "ENDED"  # 다음 회차가 종료일 뒤라 종료
    assert not [r for r in run_scheduler(a) if r["auto_transfer_id"] == auto_id]

    missed = due_auto(pair)
    sql("UPDATE auto_transfers SET next_run_date = %s WHERE id = %s", (today_kst() - timedelta(days=75), missed))
    before = balance(a1["id"])
    results = [r for r in run_scheduler(a) if r["auto_transfer_id"] == missed]
    assert len(results) == 1 and balance(a1["id"]) == before - 50_000  # 밀린 회차는 한 번만 실행
    assert sql("SELECT next_run_date FROM auto_transfers WHERE id = %s", (missed,))[0]["next_run_date"] > today_kst()


def test_canceled_auto_transfer_is_not_run(pair):
    a, a1 = pair["A"], pair["a1"]
    fund(a1["id"], 100_000)
    auto_id = due_auto(pair)
    a.post(f"/api/auto-transfers/{auto_id}/cancel", json={"pin": PIN})
    assert not [r for r in run_scheduler(a) if r["auto_transfer_id"] == auto_id]
    assert balance(a1["id"]) == 100_000


def test_dev_scheduler_endpoint_is_blocked_outside_dev(pair, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "prod")
    assert pair["A"].post("/api/dev/run-auto-transfers", json={}).status_code == 404
