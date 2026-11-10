"""회원·인증 테스트 (product-spec 10절 TC-F-001/002/010, TC-E-001/007, TC-S-002/003/004 대응)."""
from datetime import datetime, timedelta, timezone

import jwt
import psycopg

from app.config import settings
from tests.conftest import PASSWORD, PIN, last_code, new_identity, required_term_ids, signup_user


def db():
    return psycopg.connect(settings.database_url, row_factory=psycopg.rows.dict_row)


# ---------- 회원가입 (A1) ----------

def test_terms_list_has_required_terms(client):
    terms = client.get("/api/terms?category=SIGNUP").json()
    assert len(terms) >= 3 and any(t["required"] for t in terms) and any(not t["required"] for t in terms)


def test_signup_success_stores_hashes_and_agreements(client, outbox):
    user = signup_user(client, outbox)
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE login_id = %s", (user["login_id"],)).fetchone()
        assert row["status"] == "ACTIVE"
        assert row["password_hash"] != PASSWORD and row["pin"] != PIN  # 평문 저장 금지
        agreements = conn.execute("SELECT count(*) AS n FROM term_agreements WHERE user_id = %s", (row["id"],)).fetchone()
        assert agreements["n"] >= 3
        assert conn.execute("SELECT count(*) AS n FROM verification_codes WHERE email = %s", (user["email"],)).fetchone()["n"] == 0


def test_signup_requires_email_verification(client):
    ident = new_identity()
    res = client.post("/api/auth/signup", json={**ident, "password": PASSWORD, "pin": PIN,
                                                "agreed_term_ids": required_term_ids(client)})
    assert res.status_code == 400 and res.json()["code"] == "EMAIL_NOT_VERIFIED"


def test_signup_blocked_without_required_terms(client, outbox):
    ident = new_identity()
    client.post("/api/auth/email-codes", json={"email": ident["email"], "purpose": "SIGNUP"})
    client.post("/api/auth/email-codes/verify",
                json={"email": ident["email"], "purpose": "SIGNUP", "code": last_code(outbox, ident["email"])})
    res = client.post("/api/auth/signup", json={**ident, "password": PASSWORD, "pin": PIN, "agreed_term_ids": []})
    assert res.status_code == 400 and res.json()["code"] == "REQUIRED_TERMS"


def test_signup_rejects_bad_pin_and_password(client, outbox):
    ident = new_identity()
    base = {**ident, "agreed_term_ids": [1]}
    res = client.post("/api/auth/signup", json={**base, "password": PASSWORD, "pin": "12345"})
    assert res.status_code == 400 and res.json()["field"] == "pin"
    res = client.post("/api/auth/signup", json={**base, "password": "short", "pin": PIN})
    assert res.status_code == 400 and res.json()["field"] == "password"


def test_signup_duplicate_values(client, outbox):
    user = signup_user(client, outbox)
    other = new_identity()
    for field, value in (("login_id", user["login_id"]), ("phone_num", user["phone_num"])):
        ident = {**other, field: value}
        client.post("/api/auth/email-codes", json={"email": ident["email"], "purpose": "SIGNUP"})
        client.post("/api/auth/email-codes/verify",
                    json={"email": ident["email"], "purpose": "SIGNUP", "code": last_code(outbox, ident["email"])})
        res = client.post("/api/auth/signup", json={**ident, "password": PASSWORD, "pin": PIN,
                                                    "agreed_term_ids": required_term_ids(client)})
        assert res.status_code == 409 and res.json()["code"] == "DUPLICATE_VALUE" and res.json()["field"] == field
    # 이미 가입된 이메일은 인증번호 발송 단계에서 차단
    res = client.post("/api/auth/email-codes", json={"email": user["email"], "purpose": "SIGNUP"})
    assert res.status_code == 409
    assert client.get(f"/api/auth/check-duplicate?field=login_id&value={user['login_id']}").json() == {"duplicate": True}


# ---------- 이메일 인증번호 ----------

def test_code_wrong_then_attempt_limit(client, outbox):
    email = new_identity()["email"]
    client.post("/api/auth/email-codes", json={"email": email, "purpose": "SIGNUP"})
    real = last_code(outbox, email)
    wrong = "000000" if real != "000000" else "111111"
    for i in range(5):
        res = client.post("/api/auth/email-codes/verify", json={"email": email, "purpose": "SIGNUP", "code": wrong})
        assert res.status_code == 400 and res.json()["code"] == "CODE_MISMATCH"
    res = client.post("/api/auth/email-codes/verify", json={"email": email, "purpose": "SIGNUP", "code": real})
    assert res.json()["code"] == "CODE_ATTEMPTS_EXCEEDED"  # 5회 초과 후에는 맞아도 거절


def test_code_expired(client, outbox):
    email = new_identity()["email"]
    client.post("/api/auth/email-codes", json={"email": email, "purpose": "SIGNUP"})
    code = last_code(outbox, email)
    with db() as conn:
        conn.execute("UPDATE verification_codes SET expires_at = now() - interval '1 minute' WHERE email = %s", (email,))
    res = client.post("/api/auth/email-codes/verify", json={"email": email, "purpose": "SIGNUP", "code": code})
    assert res.status_code == 400 and res.json()["code"] == "CODE_EXPIRED"


def test_code_resend_limits(client, outbox):
    email = new_identity()["email"]
    assert client.post("/api/auth/email-codes", json={"email": email, "purpose": "SIGNUP"}).status_code == 200
    res = client.post("/api/auth/email-codes", json={"email": email, "purpose": "SIGNUP"})
    assert res.status_code == 429  # 60초 이내 재발송
    with db() as conn:  # 하루 5회 제한
        for _ in range(4):
            conn.execute("INSERT INTO verification_codes (email, purpose, code_hash, expires_at) "
                         "VALUES (%s, 'SIGNUP', 'x', now() - interval '2 minutes')", (email,))
        conn.execute("UPDATE verification_codes SET expires_at = now() - interval '2 minutes' WHERE email = %s", (email,))
    res = client.post("/api/auth/email-codes", json={"email": email, "purpose": "SIGNUP"})
    assert res.status_code == 429


def test_password_reset_does_not_reveal_unknown_email(client, outbox):
    res = client.post("/api/auth/email-codes", json={"email": "nobody@test.example", "purpose": "RESET_PW"})
    assert res.status_code == 200 and outbox == []


# ---------- 로그인·로그아웃 (A2) ----------

def test_login_sets_httponly_cookie_and_me(client, outbox):
    user = signup_user(client, outbox)
    assert client.get("/api/me").status_code == 401  # 미인증
    res = client.post("/api/auth/login", json={"login_id": user["login_id"], "password": user["password"]})
    assert res.status_code == 200
    assert "httponly" in res.headers["set-cookie"].lower()
    me = client.get("/api/me")
    assert me.status_code == 200 and me.json()["login_id"] == user["login_id"]
    assert "password_hash" not in me.json() and "pin" not in me.json()
    assert client.get("/api/me/login-histories").json()[0]["success"] is True


def test_pin_login_and_logout(client, outbox):
    user = signup_user(client, outbox)
    assert client.post("/api/auth/login-pin", json={"login_id": user["login_id"], "pin": user["pin"]}).status_code == 200
    assert client.get("/api/me").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/me").status_code == 401


def test_login_fails_five_times_locks_and_reset_unlocks(client, outbox):
    user = signup_user(client, outbox)
    body = {"login_id": user["login_id"], "password": "Wrong!1234"}
    for i in range(4):
        res = client.post("/api/auth/login", json=body)
        assert res.status_code == 401 and res.json()["code"] == "INVALID_CREDENTIALS"
    assert "남은 시도 1회" in res.json()["message"]
    assert client.post("/api/auth/login", json=body).status_code == 403  # 5번째 실패로 잠금
    res = client.post("/api/auth/login", json={"login_id": user["login_id"], "password": user["password"]})
    assert res.status_code == 403 and res.json()["code"] == "ACCOUNT_LOCKED"  # 맞는 비밀번호도 거절

    client.post("/api/auth/email-codes", json={"email": user["email"], "purpose": "RESET_PW"})
    new_pw = "Newpass!678"
    res = client.post("/api/auth/password-reset",
                      json={"email": user["email"], "code": last_code(outbox, user["email"]), "new_password": new_pw})
    assert res.status_code == 200
    assert client.post("/api/auth/login", json={"login_id": user["login_id"], "password": new_pw}).status_code == 200


def test_pin_failures_lock_account(client, outbox):
    user = signup_user(client, outbox)
    for _ in range(4):
        assert client.post("/api/auth/login-pin", json={"login_id": user["login_id"], "pin": "000000"}).status_code == 401
    assert client.post("/api/auth/login-pin", json={"login_id": user["login_id"], "pin": "000000"}).status_code == 403
    with db() as conn:
        assert conn.execute("SELECT status FROM users WHERE login_id = %s", (user["login_id"],)).fetchone()["status"] == "LOCKED"


def test_pin_verify_in_session(client, outbox):
    user = signup_user(client, outbox)
    client.post("/api/auth/login", json={"login_id": user["login_id"], "password": user["password"]})
    assert client.post("/api/me/pin/verify", json={"pin": user["pin"]}).status_code == 200
    res = client.post("/api/me/pin/verify", json={"pin": "000000"})
    assert res.status_code == 401 and res.json()["code"] == "INVALID_PIN"


def test_unknown_login_gives_same_error(client):
    res = client.post("/api/auth/login", json={"login_id": "t_nobody0000", "password": PASSWORD})
    assert res.status_code == 401 and res.json()["code"] == "INVALID_CREDENTIALS"


# ---------- 토큰 (TC-S-002) ----------

def test_expired_and_tampered_tokens_rejected(client, outbox):
    user = signup_user(client, outbox)
    expired = jwt.encode({"sub": user["id"], "exp": datetime.now(tz=timezone.utc) - timedelta(minutes=1)},
                         settings.jwt_secret, algorithm="HS256")
    client.cookies.set("access_token", expired)
    res = client.get("/api/me")
    assert res.status_code == 401 and res.json()["code"] == "TOKEN_EXPIRED"
    forged = jwt.encode({"sub": user["id"], "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=5)},
                        "wrong-secret", algorithm="HS256")
    client.cookies.set("access_token", forged)
    assert client.get("/api/me").status_code == 401


# ---------- 이상 접속 알림 (A2.4) ----------

def test_suspicious_login_creates_notification(client, outbox):
    user = signup_user(client, outbox)
    creds = {"login_id": user["login_id"], "password": user["password"]}
    client.post("/api/auth/login", json=creds, headers={"user-agent": "Chrome-A"})
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM notifications WHERE user_id = %s", (user["id"],)).fetchone()["n"] == 0
    client.post("/api/auth/login", json=creds, headers={"user-agent": "Chrome-A"})  # 같은 환경: 알림 없음
    client.post("/api/auth/login", json=creds, headers={"user-agent": "Firefox-B"})  # 새 환경
    with db() as conn:
        rows = conn.execute("SELECT type FROM notifications WHERE user_id = %s", (user["id"],)).fetchall()
    assert [r["type"] for r in rows] == ["SUSPICIOUS_LOGIN"]
