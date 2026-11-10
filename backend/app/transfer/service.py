"""이체 서비스 (기능 C1~C3). 정책값은 docs/decisions.md 3절을 따른다.

즉시이체와 자동이체는 모두 execute_transfer 하나로 처리한다(공통 이체 함수).
"""
import calendar
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from psycopg import Connection

from app.account import service as account_service
from app.common.errors import AppError
from app.common.mask import mask_account_num, mask_name
from app.user import service as user_service

log = logging.getLogger(__name__)
KEY_RE = re.compile(r"^[A-Za-z0-9_.:\-]{8,100}$")
MAX_ACTIVE_AUTO = 10
MAX_FAVORITES = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- 받는 분 확인 ----------

def _find_account_by_num(conn: Connection, account_num: str) -> dict | None:
    return conn.execute(
        "SELECT a.id, a.account_num, a.status, a.user_id, u.user_name FROM accounts a "
        "JOIN users u ON u.id = a.user_id WHERE a.account_num = %s", (account_num,)).fetchone()


def lookup_recipient(conn: Connection, user_id, account_num: str) -> dict:
    row = _find_account_by_num(conn, account_num)
    if row is None:
        raise AppError(404, "RECIPIENT_NOT_FOUND", "본 서비스에 개설된 계좌만 이체할 수 있습니다", "to_account_num")
    return {"account_num_masked": mask_account_num(row["account_num"]), "holder_name_masked": mask_name(row["user_name"]),
            "is_mine": row["user_id"] == user_id, "can_receive": row["status"] == "ACTIVE"}


# ---------- 공통 이체 함수 ----------

def _check(conn: Connection, src: dict, dst: dict, amount: int, tid) -> tuple[str, str] | None:
    """잠금을 잡은 뒤 호출한다. 실패하면 (코드, 메시지)를 돌려준다."""
    if src["status"] != "ACTIVE":
        return "ACCOUNT_STATUS_BLOCKED", "출금 계좌가 거래중지 또는 해지 상태라 이체할 수 없습니다"
    if dst["status"] != "ACTIVE":
        return "RECIPIENT_BLOCKED", "받는 계좌가 입금할 수 없는 상태입니다"
    if src["balance"] < amount:
        return "INSUFFICIENT_BALANCE", f"잔액이 부족합니다 (잔액 {src['balance']:,}원)"
    usage = account_service.limit_usage(conn, src["id"], exclude_id=tid)
    if usage["used_today"] + amount > src["daily_limit"]:
        left = max(0, src["daily_limit"] - usage["used_today"])
        return "LIMIT_EXCEEDED", f"1일 이체한도를 넘습니다 (오늘 남은 한도 {left:,}원)"
    if usage["used_month"] + amount > src["month_limit"]:
        left = max(0, src["month_limit"] - usage["used_month"])
        return "LIMIT_EXCEEDED", f"1달 이체한도를 넘습니다 (이번 달 남은 한도 {left:,}원)"
    return None


def execute_transfer(conn: Connection, *, from_id, to_id, amount: int, memo: str | None, key: str,
                     auto_id=None) -> dict:
    """한 번의 이체를 처리한다. 출금·입금·거래원장·상태 기록이 하나의 트랜잭션이다.

    - 같은 key를 다시 보내면 새로 처리하지 않고 기존 결과를 돌려준다(replayed=True).
    - 비즈니스 규칙 실패(잔액·한도·상태)는 이체를 FAILED로 남기고 fail을 돌려준다. 호출자가 커밋한다.
    - 계좌 행은 항상 id 순서로, 이체 기록 INSERT보다 먼저 잠가 동시 이체에서도 교착과 한도 초과가 생기지 않게 한다.
    """
    # 1) 계좌를 id 순서로 하나씩 먼저 잠근다.
    #    - ORDER BY ... FOR UPDATE는 정렬 전에 잠그므로 순서가 보장되지 않는다. 항상 같은 순서로 잠가야 교착이 없다.
    #    - 이체 행을 INSERT하면 외래키 때문에 두 계좌에 약한 잠금이 걸린다. 그 뒤에 잠금을 올리면 반대 방향 이체끼리
    #      서로 기다리는 교착이 생기므로, INSERT보다 잠금을 먼저 잡는다.
    for account_id in sorted({from_id, to_id}):
        conn.execute("SELECT 1 FROM accounts WHERE id = %s FOR NO KEY UPDATE", (account_id,))

    tid = uuid.uuid4()
    inserted = conn.execute(
        "INSERT INTO transfers (id, idempotency_key, from_account_id, to_account_id, auto_transfer_id, amount, memo, "
        "status, request_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'PENDING',%s) "
        "ON CONFLICT (idempotency_key) DO NOTHING RETURNING id",
        (tid, key, from_id, to_id, auto_id, amount, memo, _now())).fetchone()
    if inserted is None:
        old = conn.execute("SELECT * FROM transfers WHERE idempotency_key = %s", (key,)).fetchone()
        if (old["from_account_id"], old["to_account_id"], old["amount"]) != (from_id, to_id, amount):
            raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "같은 요청 키로 다른 내용의 이체를 보낼 수 없습니다")
        return {"transfer": old, "fail": None, "replayed": True}

    accounts = {r["id"]: r for r in conn.execute(
        "SELECT a.*, u.user_name FROM accounts a JOIN users u ON u.id = a.user_id WHERE a.id = ANY(%s)",
        ([from_id, to_id],)).fetchall()}
    src, dst = accounts[from_id], accounts[to_id]
    fail = _check(conn, src, dst, amount, tid)
    now = _now()
    if fail:
        conn.execute("UPDATE transfers SET status = 'FAILED', fail_reason = %s, complete_at = %s WHERE id = %s",
                     (fail[1][:200], now, tid))
        return {"transfer": conn.execute("SELECT * FROM transfers WHERE id = %s", (tid,)).fetchone(),
                "fail": fail, "replayed": False}

    typ = "AUTO_TRANSFER" if auto_id else "TRANSFER"
    new_src, new_dst = src["balance"] - amount, dst["balance"] + amount
    conn.execute("UPDATE accounts SET balance = %s WHERE id = %s", (new_src, from_id))
    conn.execute("UPDATE accounts SET balance = %s WHERE id = %s", (new_dst, to_id))
    sql = ("INSERT INTO account_transactions (account_id, transfer_id, transaction_type, transaction_direction, amount, "
           "new_balance, counterparty_name, counterparty_account, memo, transaction_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
    conn.execute(sql, (from_id, tid, typ, "OUT", amount, new_src, dst["user_name"], dst["account_num"], memo, now))
    conn.execute(sql, (to_id, tid, typ, "IN", amount, new_dst, src["user_name"], src["account_num"], memo, now))
    conn.execute("UPDATE transfers SET status = 'SUCCESS', complete_at = %s WHERE id = %s", (now, tid))
    return {"transfer": conn.execute("SELECT * FROM transfers WHERE id = %s", (tid,)).fetchone(),
            "fail": None, "replayed": False}


def _view(conn: Connection, t: dict) -> dict:
    to = conn.execute("SELECT a.account_num, u.user_name FROM accounts a JOIN users u ON u.id = a.user_id "
                      "WHERE a.id = %s", (t["to_account_id"],)).fetchone()
    after = conn.execute("SELECT new_balance FROM account_transactions WHERE transfer_id = %s AND account_id = %s "
                         "AND transaction_direction = 'OUT'", (t["id"], t["from_account_id"])).fetchone()
    return {"id": t["id"], "status": t["status"], "amount": t["amount"], "memo": t["memo"],
            "from_account_id": t["from_account_id"], "to_account_num_masked": mask_account_num(to["account_num"]),
            "to_holder_masked": mask_name(to["user_name"]), "fail_reason": t["fail_reason"],
            "requested_at": t["request_at"], "completed_at": t["complete_at"],
            "is_auto": t["auto_transfer_id"] is not None, "balance_after": after["new_balance"] if after else None}


# ---------- 즉시이체 (C1) ----------

def transfer_now(conn: Connection, user: dict, req, key: str | None) -> tuple[dict, bool]:
    """(결과, 이미 처리된 요청의 재전송 여부)를 돌려준다."""
    if not key or not KEY_RE.match(key):
        raise AppError(400, "VALIDATION_ERROR", "Idempotency-Key 헤더(8~100자)가 필요합니다", "Idempotency-Key")
    src = account_service.get_owned_account(conn, user["id"], req.from_account_id)
    dst = _find_account_by_num(conn, req.to_account_num)
    if dst is None:
        raise AppError(400, "RECIPIENT_NOT_FOUND", "본 서비스에 개설된 계좌만 이체할 수 있습니다", "to_account_num")
    if dst["id"] == src["id"]:
        raise AppError(400, "VALIDATION_ERROR", "출금 계좌와 받는 계좌가 같습니다", "to_account_num")
    user_service.verify_pin(conn, user, req.pin)

    out = execute_transfer(conn, from_id=src["id"], to_id=dst["id"], amount=req.amount, memo=req.memo, key=key)
    view = _view(conn, out["transfer"])
    if out["fail"]:
        conn.commit()  # FAILED 기록을 남긴 채 오류를 돌려준다
        code, message = out["fail"]
        raise AppError(400, code, message)
    return view, out["replayed"]


def _owned_transfer(conn: Connection, user_id, where: str, arg) -> dict:
    row = conn.execute(
        f"SELECT t.* FROM transfers t JOIN accounts a ON a.id = t.from_account_id "
        f"WHERE {where} AND a.user_id = %s", (arg, user_id)).fetchone()
    if row is None:
        raise AppError(404, "NOT_FOUND", "이체 내역을 찾을 수 없습니다")
    return _view(conn, row)


def get_transfer(conn: Connection, user_id, transfer_id) -> dict:
    return _owned_transfer(conn, user_id, "t.id = %s", transfer_id)


def get_transfer_by_key(conn: Connection, user_id, key: str) -> dict:
    return _owned_transfer(conn, user_id, "t.idempotency_key = %s", key)


# ---------- 최근·자주 쓰는 받는 계좌 (C3) ----------

def recent_recipients(conn: Connection, user_id, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        "SELECT a2.account_num, u2.user_name, max(t.complete_at) AS last_at FROM transfers t "
        "JOIN accounts a1 ON a1.id = t.from_account_id JOIN accounts a2 ON a2.id = t.to_account_id "
        "JOIN users u2 ON u2.id = a2.user_id WHERE a1.user_id = %s AND t.status = 'SUCCESS' "
        "GROUP BY a2.account_num, u2.user_name ORDER BY last_at DESC LIMIT %s", (user_id, limit)).fetchall()
    return [{"account_num": r["account_num"], "account_num_masked": mask_account_num(r["account_num"]),
             "holder_name_masked": mask_name(r["user_name"]), "last_transferred_at": r["last_at"]} for r in rows]


def _favorite_view(r: dict) -> dict:
    return {"id": r["id"], "account_num": r["account_num"], "account_num_masked": mask_account_num(r["account_num"]),
            "holder_name_masked": mask_name(r["holder_name"]), "alias": r["alias"]}


def list_favorites(conn: Connection, user_id) -> list[dict]:
    rows = conn.execute("SELECT * FROM favorite_recipients WHERE user_id = %s ORDER BY id DESC", (user_id,)).fetchall()
    return [_favorite_view(r) for r in rows]


def add_favorite(conn: Connection, user_id, account_num: str, alias: str | None) -> dict:
    acc = _find_account_by_num(conn, account_num)
    if acc is None:
        raise AppError(404, "RECIPIENT_NOT_FOUND", "본 서비스에 개설된 계좌만 등록할 수 있습니다", "account_num")
    if conn.execute("SELECT 1 FROM favorite_recipients WHERE user_id = %s AND account_num = %s",
                    (user_id, account_num)).fetchone():
        raise AppError(409, "DUPLICATE_VALUE", "이미 등록된 계좌입니다", "account_num")
    if conn.execute("SELECT count(*) AS n FROM favorite_recipients WHERE user_id = %s", (user_id,)).fetchone()["n"] >= MAX_FAVORITES:
        raise AppError(400, "LIMIT_EXCEEDED", f"자주 쓰는 계좌는 최대 {MAX_FAVORITES}개까지 등록할 수 있습니다")
    row = conn.execute(
        "INSERT INTO favorite_recipients (user_id, account_num, holder_name, alias) VALUES (%s,%s,%s,%s) RETURNING *",
        (user_id, account_num, acc["user_name"], alias)).fetchone()  # 예금주명은 서버가 계좌에서 가져온다
    return _favorite_view(row)


def delete_favorite(conn: Connection, user_id, favorite_id: int) -> None:
    n = conn.execute("DELETE FROM favorite_recipients WHERE id = %s AND user_id = %s", (favorite_id, user_id)).rowcount
    if n == 0:
        raise AppError(404, "NOT_FOUND", "등록된 계좌를 찾을 수 없습니다")


# ---------- 자동이체 (C2) ----------

def next_occurrence(cycle: str, run_day: int, after: date) -> date:
    """after보다 뒤에 오는 첫 실행일. 매월 실행일이 그 달 말일보다 크면 말일에 실행한다."""
    if cycle == "WEEKLY":
        d = after + timedelta(days=1)
        while d.weekday() != run_day:
            d += timedelta(days=1)
        return d
    y, m = after.year, after.month
    while True:
        candidate = date(y, m, min(run_day, calendar.monthrange(y, m)[1]))
        if candidate > after:
            return candidate
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _auto_view(conn: Connection, r: dict) -> dict:
    to = conn.execute("SELECT a.account_num, u.user_name FROM accounts a JOIN users u ON u.id = a.user_id "
                      "WHERE a.id = %s", (r["to_account_id"],)).fetchone()
    last = conn.execute("SELECT status, request_at, fail_reason FROM transfers WHERE auto_transfer_id = %s "
                        "ORDER BY request_at DESC LIMIT 1", (r["id"],)).fetchone()
    return {"id": r["id"], "from_account_id": r["from_account_id"],
            "to_account_num_masked": mask_account_num(to["account_num"]), "to_holder_masked": mask_name(to["user_name"]),
            "amount": r["amount"], "memo": r["memo"], "cycle": r["cycle"], "run_day": r["run_day"],
            "start_date": r["start_date"], "end_date": r["end_date"], "next_run_date": r["next_run_date"],
            "status": r["status"], "last_result": last["status"] if last else None,
            "last_run_at": last["request_at"] if last else None, "last_fail_reason": last["fail_reason"] if last else None}


def list_auto_transfers(conn: Connection, user_id) -> list[dict]:
    rows = conn.execute(
        "SELECT t.* FROM auto_transfers t JOIN accounts a ON a.id = t.from_account_id WHERE a.user_id = %s "
        "ORDER BY (t.status = 'ACTIVE') DESC, t.next_run_date, t.created_at", (user_id,)).fetchall()
    return [_auto_view(conn, r) for r in rows]


def create_auto_transfer(conn: Connection, user: dict, req) -> dict:
    src = account_service.get_owned_account(conn, user["id"], req.from_account_id)
    account_service.require_active(src)
    dst = _find_account_by_num(conn, req.to_account_num)
    if dst is None:
        raise AppError(400, "RECIPIENT_NOT_FOUND", "본 서비스에 개설된 계좌만 등록할 수 있습니다", "to_account_num")
    if dst["id"] == src["id"]:
        raise AppError(400, "VALIDATION_ERROR", "출금 계좌와 받는 계좌가 같습니다", "to_account_num")
    if dst["status"] != "ACTIVE":
        raise AppError(400, "RECIPIENT_BLOCKED", "받는 계좌가 입금할 수 없는 상태입니다", "to_account_num")
    if req.start_date <= account_service.today_kst():
        raise AppError(400, "VALIDATION_ERROR", "시작일은 내일 이후여야 합니다(등록 당일에는 실행되지 않습니다)", "start_date")
    active = conn.execute(
        "SELECT count(*) AS n FROM auto_transfers t JOIN accounts a ON a.id = t.from_account_id "
        "WHERE a.user_id = %s AND t.status = 'ACTIVE'", (user["id"],)).fetchone()["n"]
    if active >= MAX_ACTIVE_AUTO:
        raise AppError(400, "LIMIT_EXCEEDED", f"자동이체는 최대 {MAX_ACTIVE_AUTO}건까지 등록할 수 있습니다")
    first = next_occurrence(req.cycle, req.run_day, req.start_date - timedelta(days=1))
    if req.end_date is not None and first > req.end_date:
        raise AppError(400, "VALIDATION_ERROR", "시작일과 종료일 사이에 실행일이 없습니다", "end_date")
    user_service.verify_pin(conn, user, req.pin)
    row = conn.execute(
        "INSERT INTO auto_transfers (id, from_account_id, to_account_id, amount, memo, cycle, run_day, start_date, "
        "end_date, next_run_date, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (uuid.uuid4(), src["id"], dst["id"], req.amount, req.memo, req.cycle, req.run_day, req.start_date,
         req.end_date, first, _now())).fetchone()
    return _auto_view(conn, row)


def cancel_auto_transfer(conn: Connection, user: dict, auto_id, pin: str) -> dict:
    row = conn.execute(
        "SELECT t.* FROM auto_transfers t JOIN accounts a ON a.id = t.from_account_id "
        "WHERE t.id = %s AND a.user_id = %s FOR UPDATE OF t", (auto_id, user["id"])).fetchone()
    if row is None:
        raise AppError(404, "NOT_FOUND", "자동이체를 찾을 수 없습니다")
    if row["status"] != "ACTIVE":
        raise AppError(409, "VALIDATION_ERROR", "사용 중인 자동이체만 해지할 수 있습니다")
    user_service.verify_pin(conn, user, pin)
    row = conn.execute("UPDATE auto_transfers SET status = 'CANCELED' WHERE id = %s RETURNING *", (auto_id,)).fetchone()
    return _auto_view(conn, row)


def run_due_auto_transfers(conn: Connection, today: date | None = None) -> list[dict]:
    """실행일이 된 자동이체를 처리한다(스케줄러가 매일 09:00 KST에 호출).

    - 회차마다 중복 방지 키 `auto:{ID}:{실행일}`과 행 잠금(SKIP LOCKED)으로 같은 회차를 한 번만 실행한다.
    - 실패해도 재시도하지 않고 알림만 남기며, 다음 회차로 넘어간다.
    - 실행기가 멈춰 밀린 회차는 한 번만 실행하고 이후 회차로 넘어간다.
    """
    today = today or account_service.today_kst()
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM auto_transfers WHERE status = 'ACTIVE' AND next_run_date <= %s ORDER BY next_run_date, id",
        (today,)).fetchall()]
    conn.commit()
    results = []
    for auto_id in ids:
        try:
            with conn.transaction():
                row = conn.execute(
                    "SELECT * FROM auto_transfers WHERE id = %s AND status = 'ACTIVE' AND next_run_date <= %s "
                    "FOR UPDATE SKIP LOCKED", (auto_id, today)).fetchone()
                if row is None:
                    continue  # 다른 실행기가 처리 중이거나 이미 처리됨
                key = f"auto:{auto_id}:{row['next_run_date'].isoformat()}"
                out = execute_transfer(conn, from_id=row["from_account_id"], to_id=row["to_account_id"],
                                       amount=row["amount"], memo=row["memo"], key=key, auto_id=auto_id)
                if out["fail"]:
                    owner = conn.execute("SELECT user_id FROM accounts WHERE id = %s", (row["from_account_id"],)).fetchone()
                    conn.execute(
                        "INSERT INTO notifications (user_id, type, message, created_at) VALUES (%s,'AUTO_TRANSFER_FAIL',%s,%s)",
                        (owner["user_id"], f"자동이체({row['memo'] or '이체'}) {row['amount']:,}원이 실패했어요: {out['fail'][1]}"[:500], _now()))
                nxt = next_occurrence(row["cycle"], row["run_day"], today)
                status = "ENDED" if row["end_date"] and nxt > row["end_date"] else "ACTIVE"
                conn.execute("UPDATE auto_transfers SET next_run_date = %s, status = %s WHERE id = %s", (nxt, status, auto_id))
                results.append({"auto_transfer_id": auto_id, "result": out["transfer"]["status"],
                                "replayed": out["replayed"], "next_run_date": nxt, "status": status})
        except Exception:
            log.exception("자동이체 실행 실패: %s", auto_id)
    return results
