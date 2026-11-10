"""체크카드 서비스 (기능 D1). 정책값은 docs/decisions.md 4절을 따른다.

잠금 순서는 항상 계좌 -> 카드다(결제·발급·상태 변경이 서로 엇갈려도 교착이 생기지 않게).
"""
import secrets
from datetime import date, datetime, timedelta, timezone

from psycopg import Connection

from app.account.service import KST, months_ago, require_active, start_of_day, today_kst
from app.common.crypto import decrypt_card_number, encrypt_card_number, luhn_number
from app.common.errors import AppError
from app.user import service as user_service

USABLE = ("ACTIVE", "SUSPENDED", "LOST")        # 계좌에 연결된 것으로 보는 상태(계좌당 1장)
NETWORK_PREFIX = {"VISA": "4", "MASTER": "5", "LOCAL": "9"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expiry(now: datetime) -> str:
    return f"{now.month:02d}/{(now.year + 5) % 100:02d}"


def _view(c: dict) -> dict:
    last4 = decrypt_card_number(c["card_number"])[-4:]
    return {"id": c["id"], "account_id": c["account_id"], "card_number_masked": f"**** **** **** {last4}",
            "last4": last4, "expiry_date": c["expiry_date"], "card_network": c["card_network"],
            "daily_limit": c["daily_limit"], "overseas_enabled": c["overseas_enabled"], "status": c["status"],
            "reissued_from_id": c["reissued_from_id"], "created_at": c["created_at"]}


def _own_card(conn: Connection, user_id, card_id) -> dict:
    row = conn.execute(
        "SELECT c.*, a.status AS account_status, a.nickname AS account_nickname FROM cards c "
        "JOIN accounts a ON a.id = c.account_id WHERE c.id = %s AND a.user_id = %s", (card_id, user_id)).fetchone()
    if row is None:
        raise AppError(404, "NOT_FOUND", "카드를 찾을 수 없습니다")
    return row


def _lock_account(conn: Connection, account_id) -> None:
    conn.execute("SELECT 1 FROM accounts WHERE id = %s FOR NO KEY UPDATE", (account_id,))


def _locked_card(conn: Connection, user_id, card_id) -> dict:
    """소유 확인 후 계좌 -> 카드 순서로 잠그고 최신 상태를 돌려준다."""
    card = _own_card(conn, user_id, card_id)
    _lock_account(conn, card["account_id"])
    fresh = conn.execute("SELECT c.*, a.status AS account_status FROM cards c JOIN accounts a ON a.id = c.account_id "
                         "WHERE c.id = %s FOR NO KEY UPDATE OF c", (card_id,)).fetchone()
    return fresh


# ---------- 발급·조회 (D1.1~D1.3) ----------

def _new_number(network: str) -> str:
    # 카드번호는 매번 다른 nonce로 암호화되어 DB 유니크 제약이 중복을 잡지 못한다.
    # 16자리 중 15자리가 난수라 충돌 확률은 무시할 수 있다(실서비스라면 해시 컬럼으로 중복을 확인한다).
    return luhn_number(NETWORK_PREFIX[network] + "".join(str(secrets.randbelow(10)) for _ in range(5)))


def _insert_card(conn: Connection, account_id, network: str, daily_limit: int, overseas: bool, reissued_from=None) -> dict:
    now = _now()
    return conn.execute(
        "INSERT INTO cards (id, account_id, card_number, expiry_date, card_network, daily_limit, overseas_enabled, "
        "reissued_from_id, created_at) VALUES (gen_random_uuid(),%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (account_id, encrypt_card_number(_new_number(network)), _expiry(now), network, daily_limit, overseas,
         reissued_from, now)).fetchone()


def issue_card(conn: Connection, user: dict, req) -> dict:
    acc = conn.execute("SELECT id, status FROM accounts WHERE id = %s AND user_id = %s", (req.account_id, user["id"])).fetchone()
    if acc is None:
        raise AppError(404, "NOT_FOUND", "계좌를 찾을 수 없습니다")
    _lock_account(conn, acc["id"])  # 같은 계좌에 동시에 두 장이 발급되지 않도록 직렬화
    require_active(conn.execute("SELECT * FROM accounts WHERE id = %s", (acc["id"],)).fetchone())
    existing = conn.execute("SELECT count(*) AS n FROM cards WHERE account_id = %s AND status = ANY(%s)",
                            (acc["id"], list(USABLE))).fetchone()["n"]
    if existing:
        raise AppError(409, "CARD_ALREADY_EXISTS", "이 계좌에는 이미 사용 중인 체크카드가 있습니다. 재발급이나 해지를 이용해 주세요")
    return _view(_insert_card(conn, acc["id"], req.card_network, req.daily_limit, req.overseas_enabled))


def list_cards(conn: Connection, user_id, include_inactive: bool = False) -> list[dict]:
    rows = conn.execute(
        "SELECT c.* FROM cards c JOIN accounts a ON a.id = c.account_id WHERE a.user_id = %s" +
        ("" if include_inactive else " AND c.status IN ('ACTIVE','SUSPENDED','LOST')") +
        " ORDER BY c.created_at DESC, c.id", (user_id,)).fetchall()
    return [_view(r) for r in rows]


def _used_today(conn: Connection, card_id) -> int:
    return conn.execute(
        "SELECT COALESCE(SUM(amount), 0)::bigint AS n FROM card_payments WHERE card_id = %s AND complete_at IS NOT NULL "
        "AND request_at >= %s", (card_id, start_of_day(today_kst()))).fetchone()["n"]


def card_detail(conn: Connection, user_id, card_id) -> dict:
    c = _own_card(conn, user_id, card_id)
    used = _used_today(conn, card_id)
    return {**_view(c), "account_nickname": c["account_nickname"], "used_today": used,
            "remaining_today": max(0, c["daily_limit"] - used)}


def list_payments(conn: Connection, user_id, card_id, from_date: date | None, to_date: date | None,
                  page: int, size: int) -> dict:
    _own_card(conn, user_id, card_id)
    to_date = to_date or today_kst()
    from_date = from_date or months_ago(to_date, 3)
    if from_date > to_date:
        raise AppError(400, "VALIDATION_ERROR", "조회 시작일이 종료일보다 늦습니다", "from")
    args = (card_id, start_of_day(from_date), start_of_day(to_date + timedelta(days=1)))
    total = conn.execute("SELECT count(*) AS n FROM card_payments WHERE card_id = %s AND request_at >= %s AND request_at < %s",
                         args).fetchone()["n"]
    items = conn.execute(
        "SELECT id, amount, place, request_at, complete_at FROM card_payments WHERE card_id = %s AND request_at >= %s "
        "AND request_at < %s ORDER BY request_at DESC, id DESC LIMIT %s OFFSET %s", args + (size, (page - 1) * size)).fetchall()
    return {"items": items, "page": page, "size": size, "total": total}


# ---------- 설정 변경·상태 전이 (D1.3, D1.4, D1.7, D1.8) ----------

def change_settings(conn: Connection, user: dict, card_id, daily_limit: int | None, overseas: bool | None, pin: str) -> dict:
    if daily_limit is None and overseas is None:
        raise AppError(400, "VALIDATION_ERROR", "변경할 항목을 입력해 주세요", "daily_limit")
    c = _locked_card(conn, user["id"], card_id)
    if c["status"] != "ACTIVE":
        raise AppError(409, "CARD_STATUS_BLOCKED", "정상 상태의 카드만 설정을 바꿀 수 있습니다")
    user_service.verify_pin(conn, user, pin)
    conn.execute("UPDATE cards SET daily_limit = %s, overseas_enabled = %s WHERE id = %s",
                 (c["daily_limit"] if daily_limit is None else daily_limit,
                  c["overseas_enabled"] if overseas is None else overseas, card_id))
    return card_detail(conn, user["id"], card_id)


def _transition(conn: Connection, user: dict, card_id, pin: str, allowed: tuple, new_status: str, blocked_msg: str) -> dict:
    c = _locked_card(conn, user["id"], card_id)
    if c["status"] not in allowed:
        raise AppError(409, "CARD_STATUS_BLOCKED", blocked_msg)
    if new_status == "ACTIVE" and c["account_status"] != "ACTIVE":
        raise AppError(400, "ACCOUNT_STATUS_BLOCKED", "연결 계좌가 정상 상태가 아니라 카드를 다시 사용할 수 없습니다")
    user_service.verify_pin(conn, user, pin)
    conn.execute("UPDATE cards SET status = %s WHERE id = %s", (new_status, card_id))
    return card_detail(conn, user["id"], card_id)


def suspend(conn, user, card_id, pin):
    return _transition(conn, user, card_id, pin, ("ACTIVE",), "SUSPENDED", "정상 상태의 카드만 정지할 수 있습니다")


def resume(conn, user, card_id, pin):
    return _transition(conn, user, card_id, pin, ("SUSPENDED",), "ACTIVE",
                       "정지 상태의 카드만 해제할 수 있습니다. 분실 카드는 재발급해 주세요")


def report_lost(conn, user, card_id, pin):
    return _transition(conn, user, card_id, pin, ("ACTIVE", "SUSPENDED"), "LOST", "이미 분실 처리되었거나 사용할 수 없는 카드입니다")


def cancel(conn, user, card_id, pin):
    return _transition(conn, user, card_id, pin, USABLE, "CANCELED", "이미 해지되었거나 재발급된 카드입니다")


def reissue(conn: Connection, user: dict, card_id, pin: str) -> dict:
    c = _locked_card(conn, user["id"], card_id)
    if c["status"] not in USABLE:
        raise AppError(409, "CARD_STATUS_BLOCKED", "이미 해지되었거나 재발급된 카드는 재발급할 수 없습니다")
    if c["account_status"] != "ACTIVE":
        raise AppError(400, "ACCOUNT_STATUS_BLOCKED", "연결 계좌가 정상 상태가 아니라 재발급할 수 없습니다")
    user_service.verify_pin(conn, user, pin)
    new = _insert_card(conn, c["account_id"], c["card_network"], c["daily_limit"], c["overseas_enabled"], reissued_from=card_id)
    conn.execute("UPDATE cards SET status = 'REISSUED' WHERE id = %s", (card_id,))
    return _view(new)


# ---------- 카드 결제 시뮬레이터 (DEV-1) ----------

def simulate_payment(conn: Connection, user: dict, card_id, amount: int, place: str, overseas: bool) -> dict:
    """은행 외부 카드망이 없으므로 결제를 직접 만든다. 체크카드라 승인 즉시 연결 계좌에서 차감한다.

    거절되면 아무것도 기록하지 않고 오류를 돌려준다.
    """
    card = _own_card(conn, user["id"], card_id)
    _lock_account(conn, card["account_id"])
    c = _locked_card(conn, user["id"], card_id)
    acc = conn.execute("SELECT * FROM accounts WHERE id = %s", (c["account_id"],)).fetchone()
    if c["status"] != "ACTIVE":
        raise AppError(400, "CARD_STATUS_BLOCKED", "사용할 수 없는 카드입니다(정지·분실·해지·재발급된 카드)")
    if acc["status"] != "ACTIVE":
        raise AppError(400, "ACCOUNT_STATUS_BLOCKED", "연결 계좌가 거래중지 또는 해지 상태입니다")
    if overseas and not c["overseas_enabled"]:
        raise AppError(400, "OVERSEAS_DISABLED", "해외결제가 꺼져 있는 카드입니다")
    if acc["balance"] < amount:
        raise AppError(400, "INSUFFICIENT_BALANCE", f"잔액이 부족합니다 (잔액 {acc['balance']:,}원)")
    used = _used_today(conn, card_id)
    if used + amount > c["daily_limit"]:
        raise AppError(400, "LIMIT_EXCEEDED", f"카드 일일 사용한도를 넘습니다 (오늘 남은 한도 {max(0, c['daily_limit'] - used):,}원)")

    now = _now()
    pay = conn.execute("INSERT INTO card_payments (card_id, amount, place, request_at, complete_at) VALUES (%s,%s,%s,%s,%s) RETURNING *",
                       (card_id, amount, place, now, now)).fetchone()
    new_balance = acc["balance"] - amount
    conn.execute("UPDATE accounts SET balance = %s WHERE id = %s", (new_balance, acc["id"]))
    conn.execute(
        "INSERT INTO account_transactions (account_id, card_payment_id, transaction_type, transaction_direction, amount, "
        "new_balance, counterparty_name, transaction_at) VALUES (%s,%s,'CARD','OUT',%s,%s,%s,%s)",
        (acc["id"], pay["id"], amount, new_balance, place, now))
    last4 = decrypt_card_number(c["card_number"])[-4:]
    conn.execute("INSERT INTO notifications (user_id, type, message, created_at) VALUES (%s,'CARD_PAYMENT',%s,%s)",
                 (user["id"], f"{place}에서 {amount:,}원이 결제되었습니다. (체크카드 {last4})", now))
    return {"id": pay["id"], "card_id": card_id, "amount": amount, "place": place, "approved_at": now,
            "balance_after": new_balance, "overseas": overseas}
