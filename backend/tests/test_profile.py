"""정보 변경·PIN 변경·회원 탈퇴 테스트 (product-spec 10절 TC-F-010, TC-S-003 대응)."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import PASSWORD, PIN, last_code, new_identity, new_user_session, open_account, product_id, sql
from tests.test_card import act, issue
from tests.test_transfer import fund, make_auto


def user_row(user_id):
    return sql("SELECT * FROM users WHERE id = %s", (user_id,))[0]


# ---------- 정보 변경 ----------

def test_update_phone_and_birth_requires_pin(client, outbox):
    user = new_user_session(client, outbox, birth=None)
    new_phone = new_identity()["phone_num"]
    res = client.patch("/api/me", json={"phone_num": new_phone, "birth": "1999-03-15", "pin": "000000"})
    assert res.status_code == 401 and res.json()["code"] == "INVALID_PIN"
    assert user_row(user["id"])["birth"] is None and user_row(user["id"])["phone_num"] == user["phone_num"]  # 인증 실패 시 변경 없음

    res = client.patch("/api/me", json={"phone_num": new_phone, "birth": "1999-03-15", "pin": PIN})
    assert res.status_code == 200
    assert res.json()["phone_num"] == new_phone and res.json()["birth"] == "1999-03-15"
    assert "pin" not in res.json() and "password_hash" not in res.json()
    assert client.get("/api/me").json()["phone_num"] == new_phone


def test_update_profile_validation(client, outbox):
    user = new_user_session(client, outbox)
    other = new_identity()
    other_client = TestClient(app)
    taken = new_user_session(other_client, outbox)
    cases = [
        ({"pin": PIN}, 400, "phone_num"),                                   # 바꿀 항목 없음
        ({"pin": PIN, "phone_num": "123"}, 400, "phone_num"),
        ({"pin": PIN, "birth": "2999-01-01"}, 400, "birth"),
        ({"pin": PIN, "phone_num": taken["phone_num"]}, 409, "phone_num"),  # 다른 회원이 쓰는 번호
        ({"pin": PIN, "user_name": "다른이름"}, 400, "user_name"),             # 이름은 변경 불가
        ({"pin": "12345", "phone_num": other["phone_num"]}, 400, "pin"),
    ]
    for body, status, field in cases:
        res = client.patch("/api/me", json=body)
        assert res.status_code == status and res.json()["field"] == field, (body, res.text)
    assert TestClient(app).patch("/api/me", json={"pin": PIN, "phone_num": other["phone_num"]}).status_code == 401
    assert client.patch("/api/me", json={"pin": PIN, "phone_num": user["phone_num"]}).status_code == 200  # 같은 값은 허용


def test_birth_update_unlocks_age_restricted_product(client, outbox):
    new_user_session(client, outbox, birth=None)
    young = product_id(client, "청년 우대 입출금통장")
    assert client.get(f"/api/products/{young}/eligibility").json()["reasons"][0]["code"] == "BIRTH_REQUIRED"
    client.patch("/api/me", json={"birth": "1999-03-15", "pin": PIN})
    assert client.get(f"/api/products/{young}/eligibility").json()["eligible"] is True


# ---------- 이메일 변경 ----------

def test_change_email_with_code_on_new_address(client, outbox):
    user = new_user_session(client, outbox)
    new_email = f"{uuid.uuid4().hex[:10]}@test.example"
    assert client.post("/api/me/email-code", json={"email": user["email"]}).status_code == 400  # 현재 이메일과 같음
    assert client.post("/api/me/email-code", json={"email": new_email}).status_code == 200
    assert outbox[-1][0] == new_email  # 인증번호는 새 이메일로 간다
    code = last_code(outbox, new_email)

    res = client.patch("/api/me", json={"email": new_email, "pin": PIN})
    assert res.status_code == 400 and res.json()["field"] == "email_code"
    wrong = "000000" if code != "000000" else "111111"
    res = client.patch("/api/me", json={"email": new_email, "email_code": wrong, "pin": PIN})
    assert res.status_code == 400 and res.json()["code"] == "CODE_MISMATCH"
    assert user_row(user["id"])["email"] == user["email"].lower()  # 아직 그대로
    res = client.patch("/api/me", json={"email": new_email, "email_code": code, "pin": PIN})
    assert res.status_code == 200 and res.json()["email"] == new_email
    assert sql("SELECT count(*) AS n FROM verification_codes WHERE email = %s", (new_email,))[0]["n"] == 0
    res = client.patch("/api/me", json={"email": new_email, "email_code": code, "pin": PIN})
    assert res.status_code == 400  # 같은 이메일로 다시 변경 불가(이미 현재 이메일)


def test_change_email_to_taken_address_is_blocked(client, outbox):
    new_user_session(client, outbox)
    other = TestClient(app)
    taken = new_user_session(other, outbox)
    res = client.post("/api/me/email-code", json={"email": taken["email"]})
    assert res.status_code == 409 and res.json()["code"] == "DUPLICATE_VALUE"
    res = client.patch("/api/me", json={"email": taken["email"], "email_code": "123456", "pin": PIN})
    assert res.status_code == 409


# ---------- PIN 변경 ----------

def test_change_pin(client, outbox):
    user = new_user_session(client, outbox)
    old_hash = user_row(user["id"])["pin"]
    res = client.put("/api/me/pin", json={"current_pin": "000000", "new_pin": "246810"})
    assert res.status_code == 401 and res.json()["code"] == "INVALID_PIN"
    assert client.put("/api/me/pin", json={"current_pin": PIN, "new_pin": PIN}).json()["field"] == "new_pin"  # 같은 PIN
    assert client.put("/api/me/pin", json={"current_pin": PIN, "new_pin": "12ab56"}).status_code == 400
    assert client.put("/api/me/pin", json={"current_pin": PIN, "new_pin": "246810"}).status_code == 200
    assert user_row(user["id"])["pin"] != old_hash and user_row(user["id"])["pin"] != "246810"  # 해시 저장
    fresh = TestClient(app)
    assert fresh.post("/api/auth/login-pin", json={"login_id": user["login_id"], "pin": PIN}).status_code == 401  # 옛 PIN 무효
    assert fresh.post("/api/auth/login-pin", json={"login_id": user["login_id"], "pin": "246810"}).status_code == 200
    assert client.post("/api/me/pin/verify", json={"pin": "246810"}).status_code == 200


def test_wrong_current_pin_five_times_locks_account(client, outbox):
    user = new_user_session(client, outbox)
    for _ in range(4):
        assert client.put("/api/me/pin", json={"current_pin": "000000", "new_pin": "246810"}).status_code == 401
    assert client.put("/api/me/pin", json={"current_pin": "000000", "new_pin": "246810"}).status_code == 403
    assert user_row(user["id"])["status"] == "LOCKED"
    assert client.get("/api/me").status_code == 403  # 잠긴 회원은 기존 세션도 막힘


# ---------- 회원 탈퇴 ----------

def test_withdraw_check_lists_blockers_and_withdraw_is_refused(client, outbox):
    user = new_user_session(client, outbox)
    a1, a2 = open_account(client), open_account(client)
    assert client.get("/api/me/withdraw-check").json() == {"allowed": True, "reasons": []}  # 빈 계좌만 있으면 탈퇴 가능
    fund(a1["id"], 5_000)
    card = issue(client, a1["id"]).json()
    auto_id = make_auto(client, a1, a2).json()["id"]
    check = client.get("/api/me/withdraw-check").json()
    assert check["allowed"] is False
    assert {r["code"] for r in check["reasons"]} == {"BALANCE_REMAINING", "CARD_LINKED", "AUTO_TRANSFER_ACTIVE"}
    res = client.post("/api/me/withdraw", json={"pin": PIN})
    assert res.status_code == 409 and res.json()["code"] == "WITHDRAW_NOT_ALLOWED"
    assert user_row(user["id"])["status"] == "ACTIVE" and client.get("/api/me").status_code == 200

    sql("UPDATE accounts SET balance = 0 WHERE id = %s", (a1["id"],))
    assert {r["code"] for r in client.get("/api/me/withdraw-check").json()["reasons"]} == {"CARD_LINKED", "AUTO_TRANSFER_ACTIVE"}
    act(client, card["id"], "report-lost")  # 분실 상태 카드도 해지 전까지는 막는다
    assert "CARD_LINKED" in {r["code"] for r in client.get("/api/me/withdraw-check").json()["reasons"]}
    act(client, card["id"], "cancel")
    client.post(f"/api/auto-transfers/{auto_id}/cancel", json={"pin": PIN})
    assert client.get("/api/me/withdraw-check").json() == {"allowed": True, "reasons": []}


def test_withdraw_success_closes_empty_accounts_and_blocks_login(client, outbox):
    user = new_user_session(client, outbox)
    a1, a2 = open_account(client), open_account(client)
    sql("INSERT INTO account_transactions (account_id, transaction_type, transaction_direction, amount, new_balance, "
        "counterparty_name, transaction_at) VALUES (%s,'DEPOSIT','IN',1000,0,'이전 거래', now())", (a1["id"],))
    res = client.post("/api/me/withdraw", json={"pin": "000000"})
    assert res.status_code == 401 and user_row(user["id"])["status"] == "ACTIVE"  # PIN 틀리면 탈퇴 안 됨

    res = client.post("/api/me/withdraw", json={"pin": PIN})
    assert res.status_code == 200 and res.json() == {"withdrawn": True, "closed_accounts": 2}
    row = user_row(user["id"])
    assert row["status"] == "WITHDRAWN" and row["withdrawn_at"] is not None
    assert {r["status"] for r in sql("SELECT status FROM accounts WHERE user_id = %s", (user["id"],))} == {"CLOSED"}
    assert sql("SELECT count(*) AS n FROM account_transactions WHERE account_id = %s", (a1["id"],))[0]["n"] == 1  # 거래내역은 보관

    assert client.get("/api/me").status_code == 401  # 쿠키가 지워지고 세션도 무효
    fresh = TestClient(app)
    res = fresh.post("/api/auth/login", json={"login_id": user["login_id"], "password": PASSWORD})
    assert res.status_code == 401 and res.json()["code"] == "INVALID_CREDENTIALS"
    assert fresh.post("/api/auth/login-pin", json={"login_id": user["login_id"], "pin": PIN}).status_code == 401
    assert client.post("/api/me/withdraw", json={"pin": PIN}).status_code == 401  # 다시 탈퇴 불가


def test_withdraw_wrong_pin_counts_toward_lock(client, outbox):
    user = new_user_session(client, outbox)
    for _ in range(4):
        assert client.post("/api/me/withdraw", json={"pin": "000000"}).status_code == 401
    assert client.post("/api/me/withdraw", json={"pin": "000000"}).status_code == 403
    assert user_row(user["id"])["status"] == "LOCKED"


def test_new_endpoints_require_login(client):
    anon = TestClient(app)
    for method, path, body in [("post", "/api/me/email-code", {"email": "x@test.example"}),
                               ("patch", "/api/me", {"pin": PIN, "phone_num": "010-1111-2222"}),
                               ("put", "/api/me/pin", {"current_pin": PIN, "new_pin": "246810"}),
                               ("get", "/api/me/withdraw-check", None), ("post", "/api/me/withdraw", {"pin": PIN})]:
        res = getattr(anon, method)(path, **({"json": body} if body else {}))
        assert res.status_code == 401, path
