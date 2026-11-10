"""소비 서비스 (기능 E1, E3~E5). 정책값은 docs/decisions.md 5절, 집계 기준은 docs/agent-spec.md 2절을 따른다.

소비 = 카드 결제(완료) + 타인 명의 계좌로의 성공한 이체. 본인 계좌 간 이체·입금·일반 출금은 포함하지 않는다.
리포트 API와 에이전트의 소비 도구가 이 모듈의 같은 집계를 쓴다(숫자가 어긋나지 않게).
"""
import calendar
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from psycopg import Connection

from app.common.errors import AppError
from app.spending.merchant import merchant_key, strip_branch

KST = timezone(timedelta(hours=9))
FALLBACK_CATEGORY = "ETC"         # 분류되지 않은 가맹점은 '기타'로 보여준다
TRANSFER_CATEGORY = "TRANSFER"    # 타인 명의 이체는 항상 이 카테고리로 고정
MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")

CONSUMPTION_SQL = """
SELECT t.id, t.account_id, t.amount, t.transaction_at AS at, t.counterparty_name AS name, t.memo,
       CASE WHEN t.transaction_type = 'CARD' THEN 'CARD' ELSE 'TRANSFER_OTHER' END AS kind
FROM account_transactions t
JOIN accounts a            ON a.id = t.account_id
LEFT JOIN card_payments cp ON cp.id = t.card_payment_id
LEFT JOIN transfers tr     ON tr.id = t.transfer_id
LEFT JOIN accounts ra      ON ra.id = tr.to_account_id
WHERE a.user_id = %(user_id)s
  AND t.transaction_direction = 'OUT'
  AND t.transaction_at >= %(start)s AND t.transaction_at < %(end)s
  AND (
        (t.transaction_type = 'CARD' AND cp.complete_at IS NOT NULL)
     OR (t.transaction_type IN ('TRANSFER', 'AUTO_TRANSFER')
         AND tr.status = 'SUCCESS' AND ra.user_id <> a.user_id)
      )
ORDER BY t.transaction_at, t.id
"""


# ---------- 기간 ----------

def today_kst() -> date:
    return datetime.now(KST).date()


def parse_month(month: str | None) -> date:
    """'YYYY-MM' -> 그 달 1일. 없으면 이번 달(KST)."""
    if month is None:
        return today_kst().replace(day=1)
    m = MONTH_RE.match(month)
    if not m:
        raise AppError(400, "VALIDATION_ERROR", "월 형식이 올바르지 않습니다 (예: 2026-11)", "month")
    return date(int(m.group(1)), int(m.group(2)), 1)


def next_month(first: date) -> date:
    return date(first.year + (first.month == 12), first.month % 12 + 1, 1)


def prev_month(first: date) -> date:
    return date(first.year - (first.month == 1), (first.month - 2) % 12 + 1, 1)


def _start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=KST)


def month_label(first: date) -> str:
    return first.strftime("%Y-%m")


# ---------- 카테고리 ----------

def category_table(conn: Connection) -> dict[str, dict]:
    return {r["code"]: r for r in conn.execute("SELECT id, code, name FROM spending_categories ORDER BY id").fetchall()}


def list_categories(conn: Connection) -> list[dict]:
    return [{"code": c["code"], "name": c["name"]} for c in category_table(conn).values()]


def _category_map(conn: Connection, user_id) -> dict[str, tuple[str, str]]:
    """가맹점 키 -> (카테고리 코드, 출처). 우선순위: 사용자 보정(USER) > 공통 룰(RULE) > LLM 분류 캐시."""
    rank = {"USER": 0, "RULE": 1, "LLM": 2}
    best: dict[str, tuple[int, str, str]] = {}
    for r in conn.execute(
            "SELECT m.merchant_key, m.source, c.code FROM merchant_category_map m "
            "JOIN spending_categories c ON c.id = m.category_id WHERE m.user_id IS NULL OR m.user_id = %s", (user_id,)).fetchall():
        score = rank.get(r["source"], 3)
        if r["merchant_key"] not in best or score < best[r["merchant_key"]][0]:
            best[r["merchant_key"]] = (score, r["code"], r["source"])
    return {k: (code, source) for k, (_, code, source) in best.items()}


def consumption(conn: Connection, user_id, first: date) -> list[dict]:
    """한 달(KST)의 소비 거래에 카테고리를 붙여 돌려준다. 이 목록이 모든 소비 집계의 단일 기준이다."""
    rows = conn.execute(CONSUMPTION_SQL, {"user_id": user_id, "start": _start(first), "end": _start(next_month(first))}).fetchall()
    cmap = _category_map(conn, user_id)
    for r in rows:
        name = r["name"] or "(알 수 없음)"
        r["name"] = name
        if r["kind"] == "TRANSFER_OTHER":
            r.update(category=TRANSFER_CATEGORY, classified=True, merchant=name, key=name)
        else:
            key = merchant_key(name)
            code, _ = cmap.get(key, (None, None))
            r.update(category=code or FALLBACK_CATEGORY, classified=code is not None, merchant=strip_branch(name), key=key)
    return rows


def _by_category(rows: list[dict]) -> dict[str, dict]:
    agg: dict[str, dict] = defaultdict(lambda: {"amount": 0, "count": 0})
    for r in rows:
        agg[r["category"]]["amount"] += r["amount"]
        agg[r["category"]]["count"] += 1
    return agg


# ---------- 리포트 (E1) ----------

def _totals(rows: list[dict]) -> dict:
    card = [r for r in rows if r["kind"] == "CARD"]
    other = [r for r in rows if r["kind"] == "TRANSFER_OTHER"]
    return {"total": sum(r["amount"] for r in rows), "count": len(rows),
            "card_total": sum(r["amount"] for r in card), "card_count": len(card),
            "transfer_other_total": sum(r["amount"] for r in other), "transfer_other_count": len(other)}


def _rate(diff: int, base: int) -> float | None:
    return None if base == 0 else round(diff * 100 / base, 1)


def summary(conn: Connection, user_id, month: str | None) -> dict:
    first = parse_month(month)
    cur, prev = _totals(consumption(conn, user_id, first)), _totals(consumption(conn, user_id, prev_month(first)))
    return {"month": month_label(first), **cur, "prev_month": month_label(prev_month(first)), "prev_total": prev["total"],
            "diff": cur["total"] - prev["total"], "diff_rate": _rate(cur["total"] - prev["total"], prev["total"])}


def by_category(conn: Connection, user_id, month: str | None) -> dict:
    first = parse_month(month)
    cur, prev = _by_category(consumption(conn, user_id, first)), _by_category(consumption(conn, user_id, prev_month(first)))
    cats, total = category_table(conn), sum(v["amount"] for v in _by_category(consumption(conn, user_id, first)).values())
    items = []
    for code, v in cur.items():
        base = prev.get(code, {"amount": 0})["amount"]
        items.append({"code": code, "name": cats[code]["name"], "amount": v["amount"], "count": v["count"],
                      "share": round(v["amount"] * 100 / total, 1) if total else 0.0,
                      "prev_amount": base, "diff": v["amount"] - base})
    items.sort(key=lambda i: (-i["amount"], i["code"]))
    return {"month": month_label(first), "total": total, "items": items}


def top_merchants(conn: Connection, user_id, month: str | None, n: int) -> dict:
    first = parse_month(month)
    cats = category_table(conn)
    groups: dict[tuple, dict] = {}
    for r in consumption(conn, user_id, first):
        g = groups.setdefault((r["kind"], r["key"]), {"merchant": r["merchant"], "category": r["category"], "amount": 0, "count": 0})
        g["amount"] += r["amount"]
        g["count"] += 1
    items = sorted(groups.values(), key=lambda g: (-g["amount"], g["merchant"]))[:n]
    for g in items:
        g["category_name"] = cats[g["category"]]["name"]
    return {"month": month_label(first), "items": items}


def daily(conn: Connection, user_id, month: str | None) -> dict:
    first = parse_month(month)
    last = min(date(first.year, first.month, calendar.monthrange(first.year, first.month)[1]), max(today_kst(), first))
    per_day: dict[date, dict] = {}
    for r in consumption(conn, user_id, first):
        d = per_day.setdefault(r["at"].astimezone(KST).date(), {"amount": 0, "count": 0})
        d["amount"] += r["amount"]
        d["count"] += 1
    items, d = [], first
    while d <= last:
        v = per_day.get(d, {"amount": 0, "count": 0})
        items.append({"date": d.isoformat(), **v})
        d += timedelta(days=1)
    return {"month": month_label(first), "items": items}


def transactions(conn: Connection, user_id, month: str | None, category: str | None, page: int, size: int) -> dict:
    first = parse_month(month)
    cats = category_table(conn)
    if category and category not in cats:
        raise AppError(400, "VALIDATION_ERROR", "알 수 없는 카테고리입니다", "category")
    rows = [r for r in consumption(conn, user_id, first) if not category or r["category"] == category]
    rows.sort(key=lambda r: (r["at"], r["id"]), reverse=True)
    page_rows = rows[(page - 1) * size: page * size]
    return {"month": month_label(first), "page": page, "size": size, "total": len(rows),
            "items": [{"id": r["id"], "kind": r["kind"], "merchant": r["merchant"], "name": r["name"], "amount": r["amount"],
                       "at": r["at"], "memo": r["memo"], "category": r["category"],
                       "category_name": cats[r["category"]]["name"], "classified": r["classified"]} for r in page_rows]}


def compare(conn: Connection, user_id, month_a: str, month_b: str) -> dict:
    a, b = parse_month(month_a), parse_month(month_b)
    rows_a, rows_b = consumption(conn, user_id, a), consumption(conn, user_id, b)
    cats, agg_a, agg_b = category_table(conn), _by_category(rows_a), _by_category(rows_b)
    items = []
    for code in sorted(set(agg_a) | set(agg_b)):
        va, vb = agg_a.get(code, {"amount": 0})["amount"], agg_b.get(code, {"amount": 0})["amount"]
        items.append({"code": code, "name": cats[code]["name"], "amount_a": va, "amount_b": vb, "diff": vb - va,
                      "diff_rate": _rate(vb - va, va)})
    items.sort(key=lambda i: -i["diff"])
    ta, tb = _totals(rows_a)["total"], _totals(rows_b)["total"]
    return {"month_a": month_label(a), "month_b": month_label(b), "total_a": ta, "total_b": tb,
            "diff": tb - ta, "diff_rate": _rate(tb - ta, ta), "items": items}


def unclassified(conn: Connection, user_id, month: str | None) -> dict:
    """룰·보정에 없는 가맹점(기타로 표시 중). 사용자 보정이나 LLM 분류의 대상이다."""
    first = parse_month(month)
    groups: dict[str, dict] = {}
    for r in consumption(conn, user_id, first):
        if not r["classified"]:
            g = groups.setdefault(r["key"], {"merchant": r["merchant"], "merchant_key": r["key"], "amount": 0, "count": 0})
            g["amount"] += r["amount"]
            g["count"] += 1
    return {"month": month_label(first), "items": sorted(groups.values(), key=lambda g: -g["amount"])}


# ---------- 카테고리 보정 (E5) ----------

def set_merchant_category(conn: Connection, user_id, merchant: str, category_code: str) -> dict:
    cats = category_table(conn)
    if category_code not in cats:
        raise AppError(400, "VALIDATION_ERROR", "알 수 없는 카테고리입니다", "category_code")
    if category_code == TRANSFER_CATEGORY:
        raise AppError(400, "VALIDATION_ERROR", "'송금·이체'는 타인 이체 전용이라 가맹점에 지정할 수 없습니다", "category_code")
    key = merchant_key(merchant)
    if not key:
        raise AppError(400, "VALIDATION_ERROR", "가맹점명을 입력해 주세요", "merchant")
    conn.execute(
        "INSERT INTO merchant_category_map (user_id, merchant_key, category_id, source) VALUES (%s,%s,%s,'USER') "
        "ON CONFLICT ((COALESCE(user_id::text, '')), merchant_key) DO UPDATE SET category_id = EXCLUDED.category_id, "
        "source = 'USER', created_at = now()", (user_id, key, cats[category_code]["id"]))
    return {"merchant_key": key, "category_code": category_code, "category_name": cats[category_code]["name"], "source": "USER"}


def clear_merchant_category(conn: Connection, user_id, merchant: str) -> dict:
    n = conn.execute("DELETE FROM merchant_category_map WHERE user_id = %s AND merchant_key = %s AND source = 'USER'",
                     (user_id, merchant_key(merchant))).rowcount
    if n == 0:
        raise AppError(404, "NOT_FOUND", "되돌릴 사용자 보정이 없습니다")
    return {"cleared": True}


# ---------- 예산 (E3) ----------

def _level(spent: int, amount: int) -> int:
    return 100 if spent >= amount else 80 if spent * 100 >= amount * 80 else 0


def _spent_for(rows: list[dict], category_code: str | None) -> int:
    return sum(r["amount"] for r in rows if category_code is None or r["category"] == category_code)


def _budget_view(b: dict, spent: int) -> dict:
    pct = round(spent * 100 / b["amount"], 1)
    return {"id": b["id"], "month": month_label(b["budget_month"]), "category_code": b["code"],
            "category_name": b["name"] or "월 전체", "amount": b["amount"], "spent": spent,
            "remaining": b["amount"] - spent, "usage_pct": pct,
            "status": "OVER" if spent >= b["amount"] else "WARN" if pct >= 80 else "OK", "alert_level": b["alert_level"]}


def list_budgets(conn: Connection, user_id, month: str | None) -> dict:
    first = parse_month(month)
    rows = consumption(conn, user_id, first)
    budgets = conn.execute(
        "SELECT b.*, c.code, c.name FROM budgets b LEFT JOIN spending_categories c ON c.id = b.category_id "
        "WHERE b.user_id = %s AND b.budget_month = %s ORDER BY (b.category_id IS NOT NULL), c.id", (user_id, first)).fetchall()
    return {"month": month_label(first), "items": [_budget_view(b, _spent_for(rows, b["code"])) for b in budgets]}


def set_budget(conn: Connection, user_id, month: str, category_code: str | None, amount: int) -> dict:
    first = parse_month(month)
    cats = category_table(conn)
    if category_code is not None and category_code not in cats:
        raise AppError(400, "VALIDATION_ERROR", "알 수 없는 카테고리입니다", "category_code")
    cat_id = cats[category_code]["id"] if category_code else None
    # 이미 넘은 상태에서 예산을 정하면 과거 알림을 새로 보내지 않도록 현재 단계로 맞춰 둔다
    level = _level(_spent_for(consumption(conn, user_id, first), category_code), amount)
    row = conn.execute(
        "INSERT INTO budgets (user_id, category_id, budget_month, amount, alert_level) VALUES (%s,%s,%s,%s,%s) "
        "ON CONFLICT (user_id, (COALESCE(category_id, 0)), budget_month) DO UPDATE "
        "SET amount = EXCLUDED.amount, alert_level = EXCLUDED.alert_level RETURNING id", (user_id, cat_id, first, amount, level)).fetchone()
    b = conn.execute("SELECT b.*, c.code, c.name FROM budgets b LEFT JOIN spending_categories c ON c.id = b.category_id "
                     "WHERE b.id = %s", (row["id"],)).fetchone()
    return _budget_view(b, _spent_for(consumption(conn, user_id, first), category_code))


def delete_budget(conn: Connection, user_id, budget_id: int) -> None:
    if conn.execute("DELETE FROM budgets WHERE id = %s AND user_id = %s", (budget_id, user_id)).rowcount == 0:
        raise AppError(404, "NOT_FOUND", "예산을 찾을 수 없습니다")


# ---------- 예산 알림 (E4) ----------

def after_consumption(conn: Connection, user_id, when: datetime | None = None) -> None:
    """카드 결제·타인 이체가 확정된 직후, 같은 트랜잭션에서 호출한다.

    예산 사용률이 80%·100%를 처음 넘으면 `BUDGET_ALERT`를 단계마다 한 번씩만 만든다.
    예산 행을 먼저 잠가(FOR UPDATE) 동시 결제에서도 같은 단계 알림이 중복되지 않게 한다.
    """
    first = (when or datetime.now(timezone.utc)).astimezone(KST).date().replace(day=1)
    budgets = conn.execute(
        "SELECT b.*, c.code, c.name FROM budgets b LEFT JOIN spending_categories c ON c.id = b.category_id "
        "WHERE b.user_id = %s AND b.budget_month = %s ORDER BY b.id FOR UPDATE OF b", (user_id, first)).fetchall()
    if not budgets:
        return
    rows = consumption(conn, user_id, first)  # 잠금을 잡은 뒤 읽어야 다른 트랜잭션의 확정 결과가 보인다
    for b in budgets:
        spent = _spent_for(rows, b["code"])
        level = _level(spent, b["amount"])
        if level <= b["alert_level"]:
            continue
        label = b["name"] or "월 전체"
        for threshold in (80, 100):
            if b["alert_level"] < threshold <= level:
                conn.execute(
                    "INSERT INTO notifications (user_id, type, message, created_at) VALUES (%s,'BUDGET_ALERT',%s,now())",
                    (user_id, f"{first.month}월 {label} 예산({b['amount']:,}원)의 {threshold}%에 도달했어요. (사용 {spent:,}원)"))
        conn.execute("UPDATE budgets SET alert_level = %s WHERE id = %s", (level, b["id"]))
