"""회원·인증 서비스 (기능 A1~A3). 정책값은 docs/decisions.md 1절을 따른다."""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg import Connection

from app.common import mailer
from app.common.errors import AppError
from app.common.security import create_token, hash_secret, verify_secret

MAX_FAIL = 5                            # 로그인·PIN 연속 실패 잠금 기준
CODE_TTL = timedelta(minutes=5)         # 인증번호 유효시간
CODE_MAX_ATTEMPTS = 5                   # 인증번호 시도 횟수
CODE_RESEND_GAP = timedelta(seconds=60)
CODE_DAILY_LIMIT = 5
VERIFIED_VALID = timedelta(minutes=30)  # 인증 성공 후 가입에 쓸 수 있는 시간
FAIL_COLUMNS = {"login_fail_count", "pin_fail_count"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def public_user(user: dict) -> dict:
    return {k: user[k] for k in ("id", "login_id", "user_name", "email", "phone_num", "birth", "status", "created_at")}


# ---------- 약관 ----------

def list_terms(conn: Connection, category: str) -> list[dict]:
    return conn.execute(
        "SELECT id, title, content, version, required, category FROM terms WHERE category = %s ORDER BY id",
        (category,)).fetchall()


# ---------- 이메일 인증번호 ----------

def send_code(conn: Connection, email: str, purpose: str) -> None:
    email = email.lower()
    if purpose in ("SIGNUP", "CHANGE_EMAIL"):
        if conn.execute("SELECT 1 FROM users WHERE email = %s", (email,)).fetchone():
            raise AppError(409, "DUPLICATE_VALUE", "이미 가입된 이메일입니다", "email")
    elif purpose == "RESET_PW":
        user = conn.execute("SELECT status FROM users WHERE email = %s", (email,)).fetchone()
        if user is None or user["status"] == "WITHDRAWN":
            return  # 가입 여부를 알려주지 않기 위해 같은 응답을 준다
    # UNLOCK_ACCOUNT는 로그인한 본인의 이메일로만 호출된다(계좌 API가 사용자 이메일을 넘긴다)

    now = _now()
    latest = conn.execute(
        "SELECT expires_at FROM verification_codes WHERE email = %s AND purpose = %s ORDER BY id DESC LIMIT 1",
        (email, purpose)).fetchone()
    if latest and latest["expires_at"] - CODE_TTL > now - CODE_RESEND_GAP:
        raise AppError(429, "TOO_MANY_REQUESTS", "인증번호는 60초 후에 다시 받을 수 있습니다")
    sent_today = conn.execute(
        "SELECT count(*) AS n FROM verification_codes WHERE email = %s AND purpose = %s AND expires_at > %s",
        (email, purpose, now - timedelta(hours=24) + CODE_TTL)).fetchone()["n"]
    if sent_today >= CODE_DAILY_LIMIT:
        raise AppError(429, "TOO_MANY_REQUESTS", "오늘 받을 수 있는 인증번호 횟수를 넘었습니다")

    code = f"{secrets.randbelow(10 ** 6):06d}"
    conn.execute(
        "INSERT INTO verification_codes (email, purpose, code_hash, expires_at) VALUES (%s,%s,%s,%s)",
        (email, purpose, hash_secret(code), now + CODE_TTL))
    try:
        mailer.send_mail(email, "[가상은행] 이메일 인증번호",
                         f"인증번호: {code}\n5분 안에 입력해 주세요. 본인이 요청하지 않았다면 무시해 주세요.")
    except Exception:
        raise AppError(503, "MAIL_SEND_FAILED", "인증 메일을 보내지 못했습니다. 잠시 후 다시 시도해 주세요")


def verify_code(conn: Connection, email: str, purpose: str, code: str) -> None:
    email = email.lower()
    row = conn.execute(
        "SELECT id, code_hash, expires_at, attempts FROM verification_codes "
        "WHERE email = %s AND purpose = %s AND verified_at IS NULL ORDER BY id DESC LIMIT 1",
        (email, purpose)).fetchone()
    if row is None or row["expires_at"] < _now():
        raise AppError(400, "CODE_EXPIRED", "인증번호가 만료되었습니다. 다시 받아 주세요", "code")
    if row["attempts"] >= CODE_MAX_ATTEMPTS:
        raise AppError(400, "CODE_ATTEMPTS_EXCEEDED", "인증번호를 너무 많이 틀렸습니다. 다시 받아 주세요", "code")
    if not verify_secret(row["code_hash"], code):
        left = CODE_MAX_ATTEMPTS - row["attempts"] - 1
        conn.execute("UPDATE verification_codes SET attempts = attempts + 1 WHERE id = %s", (row["id"],))
        conn.commit()
        raise AppError(400, "CODE_MISMATCH", f"인증번호가 올바르지 않습니다 (남은 시도 {left}회)", "code")
    conn.execute("UPDATE verification_codes SET verified_at = %s WHERE id = %s", (_now(), row["id"]))


def _require_verified(conn: Connection, email: str, purpose: str) -> None:
    row = conn.execute(
        "SELECT id FROM verification_codes WHERE email = %s AND purpose = %s AND verified_at > %s LIMIT 1",
        (email, purpose, _now() - VERIFIED_VALID)).fetchone()
    if row is None:
        raise AppError(400, "EMAIL_NOT_VERIFIED", "이메일 인증을 먼저 완료해 주세요", "email")


# ---------- 회원가입 ----------

def check_duplicate(conn: Connection, field: str, value: str) -> bool:
    column = {"login_id": "login_id", "email": "email", "phone": "phone_num"}[field]
    if field == "email":
        value = value.lower()
    return conn.execute(f"SELECT 1 FROM users WHERE {column} = %s", (value,)).fetchone() is not None


def signup(conn: Connection, req) -> dict:
    email = req.email.lower()
    for field, column, value in (("login_id", "login_id", req.login_id), ("email", "email", email),
                                 ("phone_num", "phone_num", req.phone_num)):
        if conn.execute(f"SELECT 1 FROM users WHERE {column} = %s", (value,)).fetchone():
            raise AppError(409, "DUPLICATE_VALUE", "이미 사용 중인 값입니다", field)

    terms = {t["id"]: t["required"] for t in list_terms(conn, "SIGNUP")}
    agreed = set(req.agreed_term_ids)
    if not agreed <= set(terms):
        raise AppError(400, "VALIDATION_ERROR", "존재하지 않는 약관입니다", "agreed_term_ids")
    if any(required and tid not in agreed for tid, required in terms.items()):
        raise AppError(400, "REQUIRED_TERMS", "필수 약관에 모두 동의해야 가입할 수 있습니다", "agreed_term_ids")

    _require_verified(conn, email, "SIGNUP")

    user_id, now = uuid.uuid4(), _now()
    try:
        conn.execute(
            "INSERT INTO users (id, login_id, email, user_name, birth, phone_num, password_hash, pin, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (user_id, req.login_id, email, req.user_name, req.birth, req.phone_num,
             hash_secret(req.password), hash_secret(req.pin), now))
    except psycopg.errors.UniqueViolation:
        raise AppError(409, "DUPLICATE_VALUE", "이미 사용 중인 값입니다")
    for tid in terms:
        conn.execute("INSERT INTO term_agreements (user_id, term_id, agreed, agreed_at) VALUES (%s,%s,%s,%s)",
                     (user_id, tid, tid in agreed, now))
    conn.execute("DELETE FROM verification_codes WHERE email = %s AND purpose = 'SIGNUP'", (email,))
    return conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()


# ---------- 로그인 ----------

def _register_failure(conn: Connection, user: dict, column: str) -> int:
    """실패 횟수를 올리고 5회가 되면 잠근다. 남은 시도 횟수를 돌려주고, 잠기면 0을 돌려준다."""
    assert column in FAIL_COLUMNS
    row = conn.execute(
        f"UPDATE users SET {column} = {column} + 1, "
        f"status = CASE WHEN {column} + 1 >= %s THEN 'LOCKED' ELSE status END "
        f"WHERE id = %s RETURNING status, {column} AS cnt", (MAX_FAIL, user["id"])).fetchone()
    return 0 if row["status"] == "LOCKED" else MAX_FAIL - row["cnt"]


def _locked_error() -> AppError:
    return AppError(403, "ACCOUNT_LOCKED", "계정이 잠겼습니다. 비밀번호 재설정으로 해제할 수 있어요")


def _record_history(conn: Connection, user_id, ip, ua, success: bool) -> None:
    conn.execute("INSERT INTO login_histories (user_id, ip, user_agent, success, created_at) VALUES (%s,%s,%s,%s,%s)",
                 (user_id, ip, ua, success, _now()))


def _is_suspicious(conn: Connection, user_id, ip, ua) -> bool:
    """① 최근 30일 접속 기록에 없던 (IP, 기기) 조합이거나 ② 직전 3회가 연속 실패였을 때."""
    recent = conn.execute("SELECT success FROM login_histories WHERE user_id = %s ORDER BY id DESC LIMIT 3",
                          (user_id,)).fetchall()
    if len(recent) == 3 and not any(r["success"] for r in recent):
        return True
    since = _now() - timedelta(days=30)
    if conn.execute("SELECT 1 FROM login_histories WHERE user_id = %s AND success AND created_at > %s LIMIT 1",
                    (user_id, since)).fetchone() is None:
        return False  # 첫 로그인은 제외
    known = conn.execute(
        "SELECT 1 FROM login_histories WHERE user_id = %s AND success AND created_at > %s "
        "AND ip IS NOT DISTINCT FROM %s AND user_agent IS NOT DISTINCT FROM %s LIMIT 1",
        (user_id, since, ip, ua)).fetchone()
    return known is None


def _login_success(conn: Connection, user: dict, ip, ua) -> tuple[str, dict]:
    if _is_suspicious(conn, user["id"], ip, ua):
        conn.execute("INSERT INTO notifications (user_id, type, message, created_at) VALUES (%s,'SUSPICIOUS_LOGIN',%s,%s)",
                     (user["id"], f"평소와 다른 환경에서 로그인되었습니다. 본인이 아니라면 비밀번호를 바꿔 주세요. (IP {ip})", _now()))
    conn.execute("UPDATE users SET login_fail_count = 0, pin_fail_count = 0 WHERE id = %s", (user["id"],))
    _record_history(conn, user["id"], ip, ua, True)
    return create_token(user["id"]), public_user(user)


def _login_target(conn: Connection, login_id: str) -> dict:
    user = conn.execute("SELECT * FROM users WHERE login_id = %s", (login_id,)).fetchone()
    if user is None or user["status"] == "WITHDRAWN":
        raise AppError(401, "INVALID_CREDENTIALS", "아이디 또는 비밀번호가 올바르지 않습니다")
    if user["status"] == "LOCKED":
        raise _locked_error()
    return user


def login_password(conn: Connection, login_id: str, password: str, ip, ua) -> tuple[str, dict]:
    user = _login_target(conn, login_id)
    if not verify_secret(user["password_hash"], password):
        left = _register_failure(conn, user, "login_fail_count")
        _record_history(conn, user["id"], ip, ua, False)
        conn.commit()
        if left == 0:
            raise _locked_error()
        raise AppError(401, "INVALID_CREDENTIALS", f"아이디 또는 비밀번호가 올바르지 않습니다 (남은 시도 {left}회)")
    return _login_success(conn, user, ip, ua)


def login_pin(conn: Connection, login_id: str, pin: str, ip, ua) -> tuple[str, dict]:
    user = _login_target(conn, login_id)
    if not verify_secret(user["pin"], pin):
        left = _register_failure(conn, user, "pin_fail_count")
        _record_history(conn, user["id"], ip, ua, False)
        conn.commit()
        if left == 0:
            raise _locked_error()
        raise AppError(401, "INVALID_PIN", f"PIN이 올바르지 않습니다 (남은 시도 {left}회)")
    return _login_success(conn, user, ip, ua)


def verify_pin(conn: Connection, user: dict, pin: str) -> None:
    """이체·한도 변경 같은 민감 동작 전 PIN 확인. 틀린 횟수가 5회가 되면 계정이 잠긴다."""
    if verify_secret(user["pin"], pin):
        if user["pin_fail_count"]:  # 실패 기록이 있을 때만 갱신한다(불필요한 행 잠금 방지)
            conn.execute("UPDATE users SET pin_fail_count = 0 WHERE id = %s", (user["id"],))
        return
    left = _register_failure(conn, user, "pin_fail_count")
    conn.commit()
    if left == 0:
        raise _locked_error()
    raise AppError(401, "INVALID_PIN", f"PIN이 올바르지 않습니다 (남은 시도 {left}회)", "pin")


# ---------- 비밀번호 재설정 ----------

def reset_password(conn: Connection, email: str, code: str, new_password: str) -> None:
    email = email.lower()
    verify_code(conn, email, "RESET_PW", code)
    user = conn.execute("SELECT id, status FROM users WHERE email = %s", (email,)).fetchone()
    if user is None or user["status"] == "WITHDRAWN":
        raise AppError(400, "CODE_EXPIRED", "인증번호가 만료되었습니다. 다시 받아 주세요", "code")
    conn.execute(
        "UPDATE users SET password_hash = %s, login_fail_count = 0, pin_fail_count = 0, "
        "status = CASE WHEN status = 'LOCKED' THEN 'ACTIVE' ELSE status END WHERE id = %s",
        (hash_secret(new_password), user["id"]))
    conn.execute("DELETE FROM verification_codes WHERE email = %s AND purpose = 'RESET_PW'", (email,))


# ---------- 내 정보·접속 기록 ----------

def login_histories(conn: Connection, user_id, limit: int = 20) -> list[dict]:
    return conn.execute(
        "SELECT id, ip, user_agent, success, created_at FROM login_histories "
        "WHERE user_id = %s ORDER BY id DESC LIMIT %s", (user_id, limit)).fetchall()
