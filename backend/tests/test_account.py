"""계좌 API 테스트 (product-spec 10절 TC-F-003/004/007/008, TC-E-005/009, TC-S-001/003 대응)."""
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.common import mailer
from app.main import app
from tests.conftest import (last_code, new_user_session, open_account, product_id, sql)

MASKED = re.compile(r"^\d{3}-\*{4}-\d{4}$")
FULL = re.compile(r"^\d{3}-\d{4}-\d{4}$")


def add_tx(account_id, type_, direction, amount, days_ago, name=None, memo=None, balance=0, counterparty_account=None):
    sql("INSERT INTO account_transactions (account_id, transaction_type, transaction_direction, amount, new_balance, "
        "counterparty_name, counterparty_account, memo, transaction_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now() - make_interval(days => %s))",
        (account_id, type_, direction, amount, balance, name, counterparty_account, memo, days_ago))


# ---------- 상품·개설 (B1) ----------

def test_products_have_rates_and_conditions(client, outbox):
    new_user_session(client, outbox)
    products = client.get("/api/products").json()
    assert len(products) == 4
    young = next(p for p in products if p["product_name"] == "청년 우대 입출금통장")
    assert float(young["interest_rate"]) == 2.0 and young["min_age"] == 19 and young["max_age"] == 34
    assert young["join_condition"] and young["rate_condition"]


def test_eligibility_by_age_and_birth(client, outbox):
    new_user_session(client, outbox, birth="1999-03-15")
    young = product_id(client, "청년 우대 입출금통장")
    assert client.get(f"/api/products/{young}/eligibility").json()["eligible"] is True

    old = TestClient(app)
    new_user_session(old, outbox, birth="1980-01-01")
    res = old.get(f"/api/products/{young}/eligibility").json()
    assert res["eligible"] is False and res["reasons"][0]["code"] == "AGE_NOT_ELIGIBLE"

    nobirth = TestClient(app)
    new_user_session(nobirth, outbox, birth=None)
    res = nobirth.get(f"/api/products/{young}/eligibility").json()
    assert res["eligible"] is False and res["reasons"][0]["code"] == "BIRTH_REQUIRED"


def test_open_account_success(client, outbox):
    user = new_user_session(client, outbox)
    acc = open_account(client, nickname="월급통장")
    assert FULL.match(acc["account_num"])
    assert acc["status"] == "ACTIVE" and acc["balance"] == 0
    assert acc["daily_limit"] == 1_000_000 and acc["month_limit"] == 5_000_000  # 기본 한도
    row = sql("SELECT account_password, opening_info FROM accounts WHERE id = %s", (acc["id"],))[0]
    assert row["account_password"] != "1357"  # 해시 저장
    assert row["opening_info"] == {"purpose": "SALARY", "income_source": "SALARY_INCOME"}
    n = sql("SELECT count(*) AS n FROM term_agreements WHERE user_id = %s AND term_id IN "
            "(SELECT id FROM terms WHERE category = 'ACCOUNT_OPEN')", (user["id"],))[0]["n"]
    assert n >= 3


def test_open_account_validations(client, outbox):
    new_user_session(client, outbox, birth="1999-03-15")
    base = {"product_id": product_id(client, "청년 우대 입출금통장"), "account_password": "1357",
            "account_password_confirm": "1357", "purpose": "SALARY", "income_source": "SALARY_INCOME"}
    res = client.post("/api/accounts", json={**base, "agreed_term_ids": []})
    assert res.status_code == 400 and res.json()["code"] == "REQUIRED_TERMS"
    terms = [t["id"] for t in client.get("/api/terms?category=ACCOUNT_OPEN").json() if t["required"]]
    res = client.post("/api/accounts", json={**base, "account_password_confirm": "1358", "agreed_term_ids": terms})
    assert res.status_code == 400 and "일치" in res.json()["message"]
    res = client.post("/api/accounts", json={**base, "account_password": "12a4", "account_password_confirm": "12a4",
                                             "agreed_term_ids": terms})
    assert res.status_code == 400 and res.json()["field"] == "account_password"
    assert client.post("/api/accounts", json={**base, "agreed_term_ids": terms}).status_code == 201
    res = client.post("/api/accounts", json={**base, "agreed_term_ids": terms})  # 청년 통장은 1인 1개
    assert res.status_code == 400 and res.json()["code"] == "PRODUCT_LIMIT"


def test_open_account_blocked_without_birth_for_age_product(client, outbox):
    new_user_session(client, outbox, birth=None)
    terms = [t["id"] for t in client.get("/api/terms?category=ACCOUNT_OPEN").json() if t["required"]]
    res = client.post("/api/accounts", json={
        "product_id": product_id(client, "기본 입출금통장"), "account_password": "1357", "account_password_confirm": "1357",
        "purpose": "SALARY", "income_source": "SALARY_INCOME", "agreed_term_ids": terms})
    assert res.status_code == 400 and res.json()["code"] == "BIRTH_REQUIRED"


def test_account_count_limit(client, outbox):
    new_user_session(client, outbox)
    for _ in range(5):
        open_account(client)
    terms = [t["id"] for t in client.get("/api/terms?category=ACCOUNT_OPEN").json() if t["required"]]
    res = client.post("/api/accounts", json={
        "product_id": product_id(client, "기본 입출금통장"), "account_password": "1357", "account_password_confirm": "1357",
        "purpose": "SALARY", "income_source": "SALARY_INCOME", "agreed_term_ids": terms})
    assert res.status_code == 400 and res.json()["code"] in ("PRODUCT_LIMIT", "ACCOUNT_LIMIT")


# ---------- 조회·접근 제어 (B2, B5.1) ----------

def test_list_masks_numbers_and_puts_favorite_first(client, outbox):
    new_user_session(client, outbox)
    first = open_account(client, nickname="첫째")
    second = open_account(client, nickname="둘째")
    assert client.put(f"/api/accounts/{second['id']}/favorite", json={"is_favorite": True}).json()["is_favorite"] is True
    items = client.get("/api/accounts").json()
    assert [i["nickname"] for i in items] == ["둘째", "첫째"]
    assert all(MASKED.match(i["account_num_masked"]) and "account_num" not in i for i in items)
    assert FULL.match(client.get(f"/api/accounts/{first['id']}").json()["account_num"])


def test_other_users_account_is_hidden_and_unauthenticated_blocked(client, outbox):
    new_user_session(client, outbox)
    acc = open_account(client)
    stranger = TestClient(app)
    new_user_session(stranger, outbox)
    aid = acc["id"]
    for method, path, body in [
        ("get", f"/api/accounts/{aid}", None), ("get", f"/api/accounts/{aid}/transactions", None),
        ("get", f"/api/accounts/{aid}/limits", None), ("get", f"/api/accounts/{aid}/close-check", None),
        ("put", f"/api/accounts/{aid}/favorite", {"is_favorite": True}),
        ("post", f"/api/accounts/{aid}/close", {"pin": "135790"}),
        ("get", f"/api/accounts/{aid}/statements", None),
    ]:
        res = getattr(stranger, method)(path, **({"json": body} if body else {}))
        assert res.status_code == 404 and res.json()["code"] == "NOT_FOUND", path
    assert stranger.get(f"/api/accounts/{uuid.uuid4()}").status_code == 404
    assert stranger.get("/api/accounts").json() == []
    anonymous = TestClient(app)
    assert anonymous.get("/api/accounts").status_code == 401
    assert anonymous.get(f"/api/accounts/{aid}").status_code == 401


def test_transaction_filters_search_and_paging(client, outbox):
    new_user_session(client, outbox)
    aid = open_account(client)["id"]
    add_tx(aid, "DEPOSIT", "IN", 100000, 40, "A회사", "급여")
    add_tx(aid, "CARD", "OUT", 5600, 5, "스타벅스 강남점")
    add_tx(aid, "CARD", "OUT", 12000, 3, "맥도날드 역삼점")
    add_tx(aid, "TRANSFER", "OUT", 50000, 2, "박서준", "월세 50%")
    add_tx(aid, "AUTO_TRANSFER", "OUT", 300000, 1, "박서준", "월세")
    add_tx(aid, "DEPOSIT", "IN", 2000, 130, "오래된 입금")  # 기본 3개월 밖
    url = f"/api/accounts/{aid}/transactions"
    res = client.get(url).json()
    assert res["total"] == 5 and [i["amount"] for i in res["items"]] == [300000, 50000, 12000, 5600, 100000]  # 최신순
    assert client.get(url + "?sort=oldest").json()["items"][0]["amount"] == 100000
    assert client.get(url + "?direction=OUT").json()["total"] == 4
    assert client.get(url + "?direction=IN").json()["total"] == 1
    assert client.get(url + "?type=CARD").json()["total"] == 2
    assert client.get(url + "?type=TRANSFER&type=AUTO_TRANSFER").json()["total"] == 2
    assert client.get(url + "?min_amount=10000&max_amount=60000").json()["total"] == 2
    assert client.get(url + "?q=스타").json()["total"] == 1
    assert client.get(url + "?q=%25").json()["total"] == 1  # '%'는 문자 그대로 검색
    page2 = client.get(url + "?size=2&page=2").json()
    assert page2["total"] == 5 and len(page2["items"]) == 2 and page2["page"] == 2
    assert client.get(url + "?from=2000-01-01").json()["total"] == 6  # 기간을 넓히면 오래된 거래도 포함
    assert client.get(url + "?from=2030-01-02&to=2030-01-01").status_code == 400
    assert client.get(url + "?min_amount=5&max_amount=1").status_code == 400
    assert client.get(url + "?direction=SIDEWAYS").status_code == 400


def test_transaction_detail_masks_counterparty_and_checks_account(client, outbox):
    new_user_session(client, outbox)
    a, b = open_account(client)["id"], open_account(client)["id"]
    add_tx(a, "TRANSFER", "OUT", 1000, 1, "박서준", "송금", counterparty_account="123-4567-8901")
    add_tx(b, "DEPOSIT", "IN", 7, 1, "다른 계좌")
    tx_a = client.get(f"/api/accounts/{a}/transactions").json()["items"][0]["id"]
    tx_b = client.get(f"/api/accounts/{b}/transactions").json()["items"][0]["id"]
    detail = client.get(f"/api/accounts/{a}/transactions/{tx_a}").json()
    assert MASKED.match(detail["counterparty_account"]) and detail["memo"] == "송금"
    assert client.get(f"/api/accounts/{a}/transactions/{tx_b}").status_code == 404  # 다른 계좌의 거래 ID


# ---------- 한도 (B3.2) ----------

def test_limits_usage_and_change(client, outbox):
    user = new_user_session(client, outbox)
    a, b = open_account(client)["id"], open_account(client)["id"]
    for amount, status, days in [(300000, "SUCCESS", 0), (200000, "PENDING", 0), (999999, "FAILED", 0), (400000, "SUCCESS", 40)]:
        sql("INSERT INTO transfers (id, idempotency_key, from_account_id, to_account_id, amount, status, request_at) "
            "VALUES (%s,%s,%s,%s,%s,%s, now() - make_interval(days => %s))",
            (uuid.uuid4(), uuid.uuid4().hex, a, b, amount, status, days))
    limits = client.get(f"/api/accounts/{a}/limits").json()
    assert limits["used_today"] == 500000 and limits["used_month"] == 500000  # 성공+처리중만, 지난달 제외
    assert limits["remaining_today"] == 500000
    url = f"/api/accounts/{a}/limits"
    res = client.put(url, json={"daily_limit": 2_000_000, "month_limit": 8_000_000, "pin": "000000"})
    assert res.status_code == 401 and res.json()["code"] == "INVALID_PIN"
    assert client.get(url).json()["daily_limit"] == 1_000_000  # 인증 실패 시 변경 없음
    for daily, month, field in [(5_000, 8_000_000, "daily_limit"), (20_000_000, 20_000_000, "daily_limit"),
                                (3_000_000, 60_000_000, "month_limit"), (6_000_000, 5_000_000, "daily_limit")]:
        res = client.put(url, json={"daily_limit": daily, "month_limit": month, "pin": user["pin"]})
        assert res.status_code == 400 and res.json()["code"] == "LIMIT_OUT_OF_RANGE" and res.json()["field"] == field
    res = client.put(url, json={"daily_limit": 2_000_000, "month_limit": 8_000_000, "pin": user["pin"]})
    assert res.status_code == 200 and res.json()["daily_limit"] == 2_000_000 and res.json()["month_limit"] == 8_000_000


# ---------- 통장 비밀번호·거래중지·해제 (B3.3) ----------

def test_password_failures_suspend_and_email_unlock(client, outbox):
    new_user_session(client, outbox)
    aid = open_account(client)["id"]
    url = f"/api/accounts/{aid}/verify-password"
    assert client.post(url, json={"account_password": "1357"}).status_code == 200
    for i in range(4):
        res = client.post(url, json={"account_password": "0000"})
        assert res.status_code == 401 and res.json()["code"] == "INVALID_ACCOUNT_PASSWORD"
    assert "남은 시도 1회" in res.json()["message"]
    res = client.post(url, json={"account_password": "0000"})
    assert res.status_code == 400 and res.json()["code"] == "ACCOUNT_STATUS_BLOCKED"
    assert client.get(f"/api/accounts/{aid}").json()["status"] == "SUSPENDED"
    # 거래중지 중에는 관리 변경 불가 (B5.2)
    assert client.put(f"/api/accounts/{aid}/favorite", json={"is_favorite": True}).status_code == 400
    assert client.put(f"/api/accounts/{aid}/limits",
                      json={"daily_limit": 100000, "month_limit": 500000, "pin": "135790"}).status_code == 400
    assert client.post(url, json={"account_password": "1357"}).status_code == 400  # 맞는 비밀번호도 중지 중에는 거절
    # 이메일 인증번호로 해제
    assert client.post(f"/api/accounts/{aid}/unlock/email-code").status_code == 200
    res = client.post(f"/api/accounts/{aid}/unlock", json={"code": "000000"})
    assert res.status_code == 400 and res.json()["code"] == "CODE_MISMATCH"
    assert client.get(f"/api/accounts/{aid}").json()["status"] == "SUSPENDED"
    code = last_code(outbox, outbox[-1][0])
    res = client.post(f"/api/accounts/{aid}/unlock", json={"code": code})
    assert res.status_code == 200 and res.json()["status"] == "ACTIVE"
    assert client.post(url, json={"account_password": "1357"}).status_code == 200


def test_unlock_rejected_for_active_account(client, outbox):
    new_user_session(client, outbox)
    aid = open_account(client)["id"]
    assert client.post(f"/api/accounts/{aid}/unlock/email-code").status_code == 400
    assert client.post(f"/api/accounts/{aid}/unlock", json={"code": "123456"}).status_code == 400


# ---------- 해지 (B4) ----------

def test_close_blockers_and_close(client, outbox):
    user = new_user_session(client, outbox)
    a, b = open_account(client)["id"], open_account(client)["id"]
    check = f"/api/accounts/{a}/close-check"
    assert client.get(check).json() == {"closable": True, "reasons": []}

    card_id = uuid.uuid4()
    sql("INSERT INTO cards (id, account_id, card_number, expiry_date, status, created_at) VALUES (%s,%s,%s,'05/31','SUSPENDED', now())",
        (card_id, a, uuid.uuid4().hex))
    auto_id = uuid.uuid4()
    sql("INSERT INTO auto_transfers (id, from_account_id, to_account_id, amount, cycle, run_day, start_date, next_run_date, created_at) "
        "VALUES (%s,%s,%s,1000,'MONTHLY',1,current_date,current_date + 30, now())", (auto_id, a, b))
    sql("UPDATE accounts SET balance = 1000 WHERE id = %s", (a,))
    codes = {r["code"] for r in client.get(check).json()["reasons"]}
    assert codes == {"CARD_LINKED", "AUTO_TRANSFER_ACTIVE", "BALANCE_REMAINING"}  # 정지 카드도 연결 서비스로 본다
    res = client.post(f"/api/accounts/{a}/close", json={"pin": user["pin"]})
    assert res.status_code == 409 and res.json()["code"] == "CLOSE_NOT_ALLOWED"
    assert client.get(f"/api/accounts/{a}").json()["status"] == "ACTIVE"

    sql("UPDATE cards SET status = 'CANCELED' WHERE id = %s", (card_id,))
    sql("UPDATE auto_transfers SET status = 'CANCELED' WHERE id = %s", (auto_id,))
    sql("UPDATE accounts SET balance = 0 WHERE id = %s", (a,))
    assert client.get(check).json()["closable"] is True
    res = client.post(f"/api/accounts/{a}/close", json={"pin": "000000"})
    assert res.status_code == 401 and client.get(f"/api/accounts/{a}").json()["status"] == "ACTIVE"
    add_tx(a, "DEPOSIT", "IN", 500, 1, "이전 거래")
    res = client.post(f"/api/accounts/{a}/close", json={"pin": user["pin"]})
    assert res.status_code == 200 and res.json()["status"] == "CLOSED" and res.json()["closed_at"]
    # 해지 후: 거래내역은 조회 가능, 관리 변경은 불가, 목록에서는 숨김
    assert client.get(f"/api/accounts/{a}/transactions").json()["total"] == 1
    assert client.put(f"/api/accounts/{a}/favorite", json={"is_favorite": True}).status_code == 400
    assert [i["id"] for i in client.get("/api/accounts").json()] == [b]
    assert {i["id"] for i in client.get("/api/accounts?include_closed=true").json()} == {a, b}
    assert client.post(f"/api/accounts/{a}/close", json={"pin": user["pin"]}).status_code == 409  # 이미 해지됨


# ---------- 거래내역 다운로드 신청 (B2.7) ----------

def test_statement_request_sent_and_failed(client, outbox, files, monkeypatch):
    user = new_user_session(client, outbox)
    aid = open_account(client)["id"]
    add_tx(aid, "CARD", "OUT", 5600, 2, "스타벅스 강남점", balance=94400)
    url = f"/api/accounts/{aid}/statements"
    res = client.post(url, json={"from": "2026-01-01", "to": "2026-11-10"})
    assert res.status_code == 201 and res.json()["status"] == "SENT"
    mail = files[0]
    assert mail["to"] == user["email"].lower() and mail["filename"].endswith(".csv")
    text = mail["data"].decode("utf-8-sig")
    assert "스타벅스 강남점" in text and "5600" in text and text.startswith("거래일시")
    assert "*" in mail["body"]  # 본문의 계좌번호는 마스킹

    res = client.post(url, json={"from": "2026-01-01", "to": "2026-11-10", "email": "other@test.example"})
    assert files[1]["to"] == "other@test.example" and res.json()["email"] == "other@test.example"

    assert client.post(url, json={"from": "2024-01-01", "to": "2026-11-10"}).status_code == 400  # 1년 초과
    assert client.post(url, json={"from": "2026-05-02", "to": "2026-05-01"}).status_code == 400
    assert client.post(url, json={"from": "2026-01-01", "to": "2099-01-01"}).status_code == 400  # 미래 날짜
    assert client.post(url, json={"from": "2026-01-01", "to": "2026-02-01", "email": "not-an-email"}).status_code == 400

    def boom(*args, **kwargs):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(mailer, "send_mail_attachment", boom)
    res = client.post(url, json={"from": "2026-01-01", "to": "2026-02-01"})
    assert res.status_code == 201 and res.json()["status"] == "FAILED"  # 접수와 구분되는 실패 상태
    statuses = [r["status"] for r in client.get(url).json()]
    assert statuses[0] == "FAILED" and statuses.count("SENT") == 2
