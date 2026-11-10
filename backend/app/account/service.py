"""계좌 서비스 (기능 B1~B5). 정책값은 docs/decisions.md 2절을 따른다."""
import calendar
import csv
import io
import random
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg
from psycopg import Connection
from psycopg.types.json import Jsonb

from app.common import mailer
from app.common.errors import AppError
from app.common.mask import mask_account_num
from app.common.security import hash_secret, verify_secret
from app.user import service as user_service

KST = timezone(timedelta(hours=9))
MAX_ACCOUNTS_PER_USER = 5
PASSWORD_MAX_FAIL = 5
DAILY_LIMIT_RANGE = (10_000, 10_000_000)
MONTH_LIMIT_RANGE = (10_000, 50_000_000)
STATEMENT_MAX_DAYS = 366
CARD_LINKED_STATUSES = ("ACTIVE", "SUSPENDED", "LOST")


# ---------- 공통 도우미 ----------

def today_kst() -> date:
    return datetime.now(KST).date()


def start_of_day(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=KST)


def months_ago(d: date, n: int) -> date:
    y, m = d.year, d.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def age_of(birth: date, today: date) -> int:
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def get_owned_account(conn: Connection, user_id, account_id, *, for_update: bool = False) -> dict:
    """본인 소유 계좌만 돌려준다. 없거나 타인 계좌면 404(존재 여부를 알려주지 않는다)."""
    row = conn.execute(
        "SELECT a.*, p.product_name, p.interest_rate FROM accounts a JOIN account_products p ON p.id = a.product_id "
        "WHERE a.id = %s AND a.user_id = %s" + (" FOR UPDATE OF a" if for_update else ""),
        (account_id, user_id)).fetchone()
    if row is None:
        raise AppError(404, "NOT_FOUND", "계좌를 찾을 수 없습니다")
    return row


def require_active(account: dict) -> None:
    """상태별 허용 동작(B5.2): 관리 변경은 정상 계좌만 가능."""
    if account["status"] == "SUSPENDED":
        raise AppError(400, "ACCOUNT_STATUS_BLOCKED", "거래중지 상태의 계좌입니다. 본인확인으로 해제한 뒤 이용해 주세요")
    if account["status"] == "CLOSED":
        raise AppError(400, "ACCOUNT_STATUS_BLOCKED", "해지된 계좌입니다")


def _summary(a: dict) -> dict:
    return {"id": a["id"], "nickname": a["nickname"], "product_name": a["product_name"],
            "account_num_masked": mask_account_num(a["account_num"]), "balance": a["balance"],
            "status": a["status"], "is_favorite": a["is_favorite"]}


def _detail(a: dict) -> dict:
    return {**_summary(a), "account_num": a["account_num"], "interest_rate": a["interest_rate"],
            "daily_limit": a["daily_limit"], "month_limit": a["month_limit"],
            "created_at": a["created_at"], "closed_at": a["closed_at"]}


# ---------- 상품 안내·가입 가능 여부 (B1.1) ----------

def list_products(conn: Connection) -> list[dict]:
    return conn.execute(
        "SELECT id, product_name, interest_rate, description, product_type, min_age, max_age, "
        "max_accounts_per_user, join_condition, rate_condition FROM account_products "
        "WHERE is_active ORDER BY id").fetchall()


def eligibility(conn: Connection, user: dict, product_id: int) -> dict:
    product = conn.execute("SELECT * FROM account_products WHERE id = %s AND is_active", (product_id,)).fetchone()
    if product is None:
        raise AppError(404, "NOT_FOUND", "상품을 찾을 수 없습니다")
    reasons = []
    if product["min_age"] is not None or product["max_age"] is not None:
        if user["birth"] is None:
            reasons.append({"code": "BIRTH_REQUIRED",
                            "message": "이 상품은 연령 조건이 있어 생년월일 등록이 필요합니다. 내 정보에서 생년월일을 입력해 주세요"})
        else:
            age = age_of(user["birth"], today_kst())
            if product["min_age"] is not None and age < product["min_age"] or \
                    product["max_age"] is not None and age > product["max_age"]:
                reasons.append({"code": "AGE_NOT_ELIGIBLE", "message": f"가입 조건(연령)에 맞지 않습니다. {product['join_condition']}"})
    same = conn.execute("SELECT count(*) AS n FROM accounts WHERE user_id = %s AND product_id = %s AND status <> 'CLOSED'",
                        (user["id"], product_id)).fetchone()["n"]
    if same >= product["max_accounts_per_user"]:
        reasons.append({"code": "PRODUCT_LIMIT", "message": f"이 상품은 1인 최대 {product['max_accounts_per_user']}개까지 개설할 수 있습니다"})
    total = conn.execute("SELECT count(*) AS n FROM accounts WHERE user_id = %s AND status <> 'CLOSED'",
                         (user["id"],)).fetchone()["n"]
    if total >= MAX_ACCOUNTS_PER_USER:
        reasons.append({"code": "ACCOUNT_LIMIT", "message": f"계좌는 최대 {MAX_ACCOUNTS_PER_USER}개까지 개설할 수 있습니다"})
    return {"eligible": not reasons, "reasons": reasons}


# ---------- 개설 (B1.2~B1.8) ----------

def _new_account_num(conn: Connection) -> str:
    while True:
        num = f"{random.randint(100, 999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"
        if conn.execute("SELECT 1 FROM accounts WHERE account_num = %s", (num,)).fetchone() is None:
            return num


def open_account(conn: Connection, user: dict, req) -> dict:
    result = eligibility(conn, user, req.product_id)
    if not result["eligible"]:
        first = result["reasons"][0]
        raise AppError(400, first["code"], first["message"], "product_id")

    terms = conn.execute("SELECT id, required FROM terms WHERE category = 'ACCOUNT_OPEN'").fetchall()
    ids = {t["id"] for t in terms}
    agreed = set(req.agreed_term_ids)
    if not agreed <= ids:
        raise AppError(400, "VALIDATION_ERROR", "존재하지 않는 약관입니다", "agreed_term_ids")
    if any(t["required"] and t["id"] not in agreed for t in terms):
        raise AppError(400, "REQUIRED_TERMS", "필수 약관과 상품설명서에 모두 동의해야 개설할 수 있습니다", "agreed_term_ids")

    account_id, now = uuid.uuid4(), datetime.now(timezone.utc)
    opening_info = {"purpose": req.purpose, "income_source": req.income_source}
    for _ in range(5):
        try:
            with conn.transaction():  # 번호 중복 시 이 구간만 되돌리고 다시 시도
                conn.execute(
                    "INSERT INTO accounts (id, user_id, product_id, account_num, account_password, nickname, "
                    "opening_info, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (account_id, user["id"], req.product_id, _new_account_num(conn), hash_secret(req.account_password),
                     req.nickname, Jsonb(opening_info), now))
            break
        except psycopg.errors.UniqueViolation:
            continue
    else:
        raise AppError(500, "ACCOUNT_NUM_FAILED", "계좌번호를 발급하지 못했습니다. 다시 시도해 주세요")
    for t in terms:
        conn.execute("INSERT INTO term_agreements (user_id, term_id, agreed, agreed_at) VALUES (%s,%s,%s,%s)",
                     (user["id"], t["id"], t["id"] in agreed, now))
    return _detail(get_owned_account(conn, user["id"], account_id))


# ---------- 조회 (B2) ----------

def list_accounts(conn: Connection, user_id, include_closed: bool = False) -> list[dict]:
    rows = conn.execute(
        "SELECT a.*, p.product_name, p.interest_rate FROM accounts a JOIN account_products p ON p.id = a.product_id "
        "WHERE a.user_id = %s" + ("" if include_closed else " AND a.status <> 'CLOSED'") +
        " ORDER BY a.is_favorite DESC, a.created_at, a.id", (user_id,)).fetchall()
    return [_summary(r) for r in rows]


def account_detail(conn: Connection, user_id, account_id) -> dict:
    return _detail(get_owned_account(conn, user_id, account_id))


def _escape_like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def list_transactions(conn: Connection, user_id, account_id, *, from_date: date | None, to_date: date | None,
                      direction: str, types: list[str], min_amount: int | None, max_amount: int | None,
                      q: str | None, sort: str, page: int, size: int) -> dict:
    get_owned_account(conn, user_id, account_id)  # 소유자 검증 (해지 계좌도 조회 가능)
    to_date = to_date or today_kst()
    from_date = from_date or months_ago(to_date, 3)  # 기본 조회 기간: 3개월
    if from_date > to_date:
        raise AppError(400, "VALIDATION_ERROR", "조회 시작일이 종료일보다 늦습니다", "from")
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise AppError(400, "VALIDATION_ERROR", "금액 범위가 올바르지 않습니다", "min_amount")

    where = ["account_id = %s", "transaction_at >= %s", "transaction_at < %s"]
    params: list = [account_id, start_of_day(from_date), start_of_day(to_date + timedelta(days=1))]
    if direction != "ALL":
        where.append("transaction_direction = %s")
        params.append(direction)
    if types:
        where.append("transaction_type = ANY(%s)")
        params.append(types)
    if min_amount is not None:
        where.append("amount >= %s")
        params.append(min_amount)
    if max_amount is not None:
        where.append("amount <= %s")
        params.append(max_amount)
    if q:
        where.append("(counterparty_name ILIKE %s OR memo ILIKE %s)")
        params += [_escape_like(q)] * 2
    clause = " AND ".join(where)
    order = "ASC" if sort == "oldest" else "DESC"
    total = conn.execute(f"SELECT count(*) AS n FROM account_transactions WHERE {clause}", params).fetchone()["n"]
    items = conn.execute(
        "SELECT id, transaction_type AS type, transaction_direction AS direction, amount, new_balance, "
        f"counterparty_name, memo, transaction_at FROM account_transactions WHERE {clause} "
        f"ORDER BY transaction_at {order}, id {order} LIMIT %s OFFSET %s", params + [size, (page - 1) * size]).fetchall()
    return {"items": items, "page": page, "size": size, "total": total,
            "from": from_date.isoformat(), "to": to_date.isoformat()}


def transaction_detail(conn: Connection, user_id, account_id, tx_id: int) -> dict:
    get_owned_account(conn, user_id, account_id)
    row = conn.execute(
        "SELECT id, transaction_type AS type, transaction_direction AS direction, amount, new_balance, "
        "counterparty_name, counterparty_account, memo, transaction_at FROM account_transactions "
        "WHERE id = %s AND account_id = %s", (tx_id, account_id)).fetchone()
    if row is None:
        raise AppError(404, "NOT_FOUND", "거래를 찾을 수 없습니다")
    row["counterparty_account"] = mask_account_num(row["counterparty_account"])
    return row


# ---------- 관리: 즐겨찾기·별칭·한도 (B3.1~B3.2) ----------

def set_favorite(conn: Connection, user_id, account_id, is_favorite: bool) -> dict:
    require_active(get_owned_account(conn, user_id, account_id))
    conn.execute("UPDATE accounts SET is_favorite = %s WHERE id = %s", (is_favorite, account_id))
    return account_detail(conn, user_id, account_id)


def set_nickname(conn: Connection, user_id, account_id, nickname: str) -> dict:
    require_active(get_owned_account(conn, user_id, account_id))
    conn.execute("UPDATE accounts SET nickname = %s WHERE id = %s", (nickname, account_id))
    return account_detail(conn, user_id, account_id)


def limit_usage(conn: Connection, account_id, exclude_id=None) -> dict:
    """오늘·이번 달(KST) 이체 사용량. 성공·처리중 이체를 합산한다(즉시이체·자동이체 포함).

    exclude_id는 지금 처리 중인 이체 자신을 빼기 위한 값이다.
    """
    today = today_kst()
    day_start, month_start = start_of_day(today), start_of_day(today.replace(day=1))
    row = conn.execute(
        "SELECT COALESCE(SUM(amount) FILTER (WHERE request_at >= %s), 0)::bigint AS today, "
        "COALESCE(SUM(amount), 0)::bigint AS month FROM transfers "
        "WHERE from_account_id = %s AND status IN ('SUCCESS', 'PENDING') AND request_at >= %s "
        "AND (%s::uuid IS NULL OR id <> %s::uuid)",
        (day_start, account_id, month_start, exclude_id, exclude_id)).fetchone()
    return {"used_today": row["today"], "used_month": row["month"]}


def get_limits(conn: Connection, user_id, account_id) -> dict:
    a = get_owned_account(conn, user_id, account_id)
    usage = limit_usage(conn, account_id)
    return {"daily_limit": a["daily_limit"], "month_limit": a["month_limit"], **usage,
            "remaining_today": max(0, min(a["daily_limit"] - usage["used_today"], a["month_limit"] - usage["used_month"])),
            "daily_limit_range": list(DAILY_LIMIT_RANGE), "month_limit_range": list(MONTH_LIMIT_RANGE)}


def change_limits(conn: Connection, user: dict, account_id, daily: int, month: int, pin: str) -> dict:
    a = get_owned_account(conn, user["id"], account_id)
    require_active(a)
    if not DAILY_LIMIT_RANGE[0] <= daily <= DAILY_LIMIT_RANGE[1]:
        raise AppError(400, "LIMIT_OUT_OF_RANGE", f"1일 한도는 {DAILY_LIMIT_RANGE[0]:,}원~{DAILY_LIMIT_RANGE[1]:,}원 사이여야 합니다", "daily_limit")
    if not MONTH_LIMIT_RANGE[0] <= month <= MONTH_LIMIT_RANGE[1]:
        raise AppError(400, "LIMIT_OUT_OF_RANGE", f"1달 한도는 {MONTH_LIMIT_RANGE[0]:,}원~{MONTH_LIMIT_RANGE[1]:,}원 사이여야 합니다", "month_limit")
    if daily > month:
        raise AppError(400, "LIMIT_OUT_OF_RANGE", "1일 한도는 1달 한도보다 클 수 없습니다", "daily_limit")
    user_service.verify_pin(conn, user, pin)
    conn.execute("UPDATE accounts SET daily_limit = %s, month_limit = %s WHERE id = %s", (daily, month, account_id))
    return get_limits(conn, user["id"], account_id)


# ---------- 통장 비밀번호·거래중지 (B1.3, B3.3) ----------

def verify_account_password(conn: Connection, user_id, account_id, password: str) -> None:
    a = get_owned_account(conn, user_id, account_id, for_update=True)
    require_active(a)
    if verify_secret(a["account_password"], password):
        conn.execute("UPDATE accounts SET password_fail_count = 0 WHERE id = %s", (account_id,))
        return
    row = conn.execute(
        "UPDATE accounts SET password_fail_count = password_fail_count + 1, "
        "status = CASE WHEN password_fail_count + 1 >= %s THEN 'SUSPENDED' ELSE status END "
        "WHERE id = %s RETURNING status, password_fail_count AS cnt", (PASSWORD_MAX_FAIL, account_id)).fetchone()
    conn.commit()
    if row["status"] == "SUSPENDED":
        raise AppError(400, "ACCOUNT_STATUS_BLOCKED", "통장 비밀번호를 5회 틀려 거래가 중지되었습니다. 본인확인으로 해제할 수 있어요")
    raise AppError(401, "INVALID_ACCOUNT_PASSWORD",
                   f"통장 비밀번호가 올바르지 않습니다 (남은 시도 {PASSWORD_MAX_FAIL - row['cnt']}회)", "account_password")


def send_unlock_code(conn: Connection, user: dict, account_id) -> None:
    a = get_owned_account(conn, user["id"], account_id)
    if a["status"] != "SUSPENDED":
        raise AppError(400, "ACCOUNT_STATUS_BLOCKED", "거래중지 상태의 계좌가 아닙니다")
    user_service.send_code(conn, user["email"], "UNLOCK_ACCOUNT")


def unlock_account(conn: Connection, user: dict, account_id, code: str) -> dict:
    a = get_owned_account(conn, user["id"], account_id, for_update=True)
    if a["status"] != "SUSPENDED":
        raise AppError(400, "ACCOUNT_STATUS_BLOCKED", "거래중지 상태의 계좌가 아닙니다")
    user_service.verify_code(conn, user["email"], "UNLOCK_ACCOUNT", code)
    conn.execute("UPDATE accounts SET status = 'ACTIVE', password_fail_count = 0 WHERE id = %s", (account_id,))
    conn.execute("DELETE FROM verification_codes WHERE email = %s AND purpose = 'UNLOCK_ACCOUNT'", (user["email"],))
    return account_detail(conn, user["id"], account_id)


# ---------- 해지 (B4) ----------

def close_blockers(conn: Connection, a: dict) -> list[dict]:
    reasons = []
    if a["status"] != "ACTIVE":
        reasons.append({"code": "STATUS_NOT_ACTIVE", "message": "정상 상태의 계좌만 해지할 수 있습니다"})
    if a["balance"] > 0:
        reasons.append({"code": "BALANCE_REMAINING", "message": f"잔액 {a['balance']:,}원이 남아 있습니다. 잔액을 모두 이체한 뒤 해지해 주세요"})
    cards = conn.execute("SELECT count(*) AS n FROM cards WHERE account_id = %s AND status = ANY(%s)",
                         (a["id"], list(CARD_LINKED_STATUSES))).fetchone()["n"]
    if cards:
        reasons.append({"code": "CARD_LINKED", "message": f"연결된 체크카드가 {cards}장 있습니다. 카드를 해지한 뒤 계좌를 해지해 주세요"})
    autos = conn.execute("SELECT count(*) AS n FROM auto_transfers WHERE status = 'ACTIVE' "
                         "AND (from_account_id = %s OR to_account_id = %s)", (a["id"], a["id"])).fetchone()["n"]
    if autos:
        reasons.append({"code": "AUTO_TRANSFER_ACTIVE", "message": f"사용 중인 자동이체가 {autos}건 있습니다. 자동이체를 해지한 뒤 계좌를 해지해 주세요"})
    return reasons


def close_check(conn: Connection, user_id, account_id) -> dict:
    reasons = close_blockers(conn, get_owned_account(conn, user_id, account_id))
    return {"closable": not reasons, "reasons": reasons}


def close_account(conn: Connection, user: dict, account_id, pin: str) -> dict:
    a = get_owned_account(conn, user["id"], account_id, for_update=True)  # 이체·카드 연결과 동시에 처리되지 않도록 잠근다
    reasons = close_blockers(conn, a)
    if reasons:
        raise AppError(409, "CLOSE_NOT_ALLOWED", reasons[0]["message"])
    user_service.verify_pin(conn, user, pin)
    conn.execute("UPDATE accounts SET status = 'CLOSED', closed_at = %s WHERE id = %s",
                 (datetime.now(timezone.utc), account_id))
    return account_detail(conn, user["id"], account_id)


# ---------- 거래내역 다운로드 신청 (B2.7) ----------

def _statement_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["거래일시", "구분", "유형", "금액", "거래 후 잔액", "상대방", "적요"])
    for r in rows:
        w.writerow([r["transaction_at"].astimezone(KST).strftime("%Y-%m-%d %H:%M:%S"),
                    "입금" if r["transaction_direction"] == "IN" else "출금", r["transaction_type"],
                    r["amount"], r["new_balance"], r["counterparty_name"] or "", r["memo"] or ""])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def request_statement(conn: Connection, user: dict, account_id, from_date: date, to_date: date, email: str | None) -> dict:
    a = get_owned_account(conn, user["id"], account_id)
    if from_date > to_date or to_date > today_kst():
        raise AppError(400, "VALIDATION_ERROR", "조회 기간이 올바르지 않습니다", "from")
    if (to_date - from_date).days + 1 > STATEMENT_MAX_DAYS:
        raise AppError(400, "VALIDATION_ERROR", "조회 기간은 최대 1년입니다", "to")
    email = (email or user["email"]).lower()
    req = conn.execute(
        "INSERT INTO statement_requests (account_id, from_date, to_date, email, created_at) "
        "VALUES (%s,%s,%s,%s,%s) RETURNING id", (account_id, from_date, to_date, email, datetime.now(timezone.utc))).fetchone()
    rows = conn.execute(
        "SELECT * FROM account_transactions WHERE account_id = %s AND transaction_at >= %s AND transaction_at < %s "
        "ORDER BY transaction_at, id", (account_id, start_of_day(from_date), start_of_day(to_date + timedelta(days=1)))).fetchall()
    try:
        mailer.send_mail_attachment(
            email, "[가상은행] 거래내역 파일",
            f"계좌 {mask_account_num(a['account_num'])}의 {from_date}~{to_date} 거래내역입니다. (총 {len(rows)}건)",
            f"transactions_{from_date}_{to_date}.csv", _statement_csv(rows))
        status = "SENT"
    except Exception:
        status = "FAILED"
    conn.execute("UPDATE statement_requests SET status = %s WHERE id = %s", (status, req["id"]))
    return {"id": req["id"], "status": status, "email": email, "count": len(rows),
            "message": "거래내역을 이메일로 보냈습니다" if status == "SENT" else "이메일 발송에 실패했습니다. 잠시 후 다시 신청해 주세요"}


def list_statements(conn: Connection, user_id, account_id) -> list[dict]:
    get_owned_account(conn, user_id, account_id)
    return conn.execute("SELECT id, from_date, to_date, email, status, created_at FROM statement_requests "
                        "WHERE account_id = %s ORDER BY id DESC LIMIT 50", (account_id,)).fetchall()
