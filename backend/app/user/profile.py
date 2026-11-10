"""내 정보 변경·PIN 변경·회원 탈퇴 (기능 A3). 정책값은 docs/decisions.md 1절을 따른다.

계좌·카드·자동이체를 확인해야 해서 user.service와 분리했다(account.service가 user.service를 쓰므로 순환 방지).
"""
from datetime import datetime, timezone

import psycopg
from psycopg import Connection

from app.account.service import CARD_LINKED_STATUSES
from app.common.errors import AppError
from app.common.security import hash_secret, verify_secret
from app.user import service as user_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- 정보 변경 ----------

def send_email_change_code(conn: Connection, user: dict, new_email: str) -> None:
    new_email = new_email.lower()
    if new_email == user["email"].lower():
        raise AppError(400, "VALIDATION_ERROR", "현재 이메일과 같습니다", "email")
    user_service.send_code(conn, new_email, "CHANGE_EMAIL")


def update_profile(conn: Connection, user: dict, req) -> dict:
    changes = {k: v for k, v in (("phone_num", req.phone_num), ("birth", req.birth), ("email", req.email)) if v is not None}
    if not changes:
        raise AppError(400, "VALIDATION_ERROR", "변경할 항목을 입력해 주세요", "phone_num")
    if "email" in changes:
        changes["email"] = changes["email"].lower()
        if changes["email"] == user["email"].lower():
            raise AppError(400, "VALIDATION_ERROR", "현재 이메일과 같습니다", "email")
        if not req.email_code:
            raise AppError(400, "VALIDATION_ERROR", "새 이메일로 받은 인증번호를 입력해 주세요", "email_code")
    if "phone_num" in changes and conn.execute("SELECT 1 FROM users WHERE phone_num = %s AND id <> %s",
                                               (changes["phone_num"], user["id"])).fetchone():
        raise AppError(409, "DUPLICATE_VALUE", "이미 사용 중인 휴대폰 번호입니다", "phone_num")
    if "email" in changes and conn.execute("SELECT 1 FROM users WHERE email = %s AND id <> %s",
                                           (changes["email"], user["id"])).fetchone():
        raise AppError(409, "DUPLICATE_VALUE", "이미 사용 중인 이메일입니다", "email")

    user_service.verify_pin(conn, user, req.pin)
    if "email" in changes:
        user_service.verify_code(conn, changes["email"], "CHANGE_EMAIL", req.email_code)
        conn.execute("DELETE FROM verification_codes WHERE email = %s AND purpose = 'CHANGE_EMAIL'", (changes["email"],))
    try:
        sets = ", ".join(f"{col} = %s" for col in changes)  # 컬럼명은 위 화이트리스트에서만 온다
        conn.execute(f"UPDATE users SET {sets} WHERE id = %s", (*changes.values(), user["id"]))
    except psycopg.errors.UniqueViolation:
        raise AppError(409, "DUPLICATE_VALUE", "이미 사용 중인 값입니다")
    return user_service.public_user(conn.execute("SELECT * FROM users WHERE id = %s", (user["id"],)).fetchone())


# ---------- PIN 변경 ----------

def change_pin(conn: Connection, user: dict, current_pin: str, new_pin: str) -> None:
    if current_pin == new_pin:
        raise AppError(400, "VALIDATION_ERROR", "현재 PIN과 다른 PIN을 입력해 주세요", "new_pin")
    user_service.verify_pin(conn, user, current_pin)  # 틀리면 실패 횟수가 쌓이고 5회째에 계정이 잠긴다
    conn.execute("UPDATE users SET pin = %s WHERE id = %s", (hash_secret(new_pin), user["id"]))


# ---------- 회원 탈퇴 ----------

def _lock_accounts(conn: Connection, user_id) -> list[dict]:
    """본인 계좌를 id 순서로 하나씩 잠근다(이체·카드와 같은 순서라 교착이 없다)."""
    ids = [r["id"] for r in conn.execute("SELECT id FROM accounts WHERE user_id = %s", (user_id,)).fetchall()]
    for account_id in sorted(ids):
        conn.execute("SELECT 1 FROM accounts WHERE id = %s FOR NO KEY UPDATE", (account_id,))
    return conn.execute("SELECT * FROM accounts WHERE user_id = %s ORDER BY id", (user_id,)).fetchall()


def _withdraw_blockers(conn: Connection, accounts: list[dict]) -> list[dict]:
    open_accounts = [a for a in accounts if a["status"] != "CLOSED"]
    ids = [a["id"] for a in open_accounts]
    reasons = []
    with_balance = [a for a in open_accounts if a["balance"] > 0]
    if with_balance:
        total = sum(a["balance"] for a in with_balance)
        reasons.append({"code": "BALANCE_REMAINING",
                        "message": f"잔액이 남은 계좌가 {len(with_balance)}개 있습니다 (합계 {total:,}원). 잔액을 모두 이체한 뒤 탈퇴해 주세요"})
    if ids:
        cards = conn.execute("SELECT count(*) AS n FROM cards WHERE account_id = ANY(%s) AND status = ANY(%s)",
                             (ids, list(CARD_LINKED_STATUSES))).fetchone()["n"]
        if cards:
            reasons.append({"code": "CARD_LINKED", "message": f"해지하지 않은 체크카드가 {cards}장 있습니다. 카드를 해지한 뒤 탈퇴해 주세요"})
        autos = conn.execute("SELECT count(*) AS n FROM auto_transfers WHERE status = 'ACTIVE' AND from_account_id = ANY(%s)",
                             (ids,)).fetchone()["n"]
        if autos:
            reasons.append({"code": "AUTO_TRANSFER_ACTIVE", "message": f"사용 중인 자동이체가 {autos}건 있습니다. 자동이체를 해지한 뒤 탈퇴해 주세요"})
    return reasons


def withdraw_check(conn: Connection, user_id) -> dict:
    reasons = _withdraw_blockers(conn, conn.execute("SELECT * FROM accounts WHERE user_id = %s", (user_id,)).fetchall())
    return {"allowed": not reasons, "reasons": reasons}


def withdraw(conn: Connection, user: dict, pin: str) -> dict:
    """탈퇴: 회원 상태를 WITHDRAWN으로 바꾸고 탈퇴일시를 기록한다. 거래 데이터는 보관한다.

    남은 계좌는 잔액이 0원이고 연결 서비스가 없는 것만 남으므로 함께 해지 처리한다.
    """
    accounts = _lock_accounts(conn, user["id"])
    reasons = _withdraw_blockers(conn, accounts)
    if reasons:
        raise AppError(409, "WITHDRAW_NOT_ALLOWED", reasons[0]["message"])
    user_service.verify_pin(conn, user, pin)
    now = _now()
    closed = conn.execute(
        "UPDATE accounts SET status = 'CLOSED', closed_at = %s WHERE user_id = %s AND status <> 'CLOSED'", (now, user["id"])).rowcount
    conn.execute("UPDATE users SET status = 'WITHDRAWN', withdrawn_at = %s WHERE id = %s", (now, user["id"]))
    return {"withdrawn": True, "closed_accounts": closed}
