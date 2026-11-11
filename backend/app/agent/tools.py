"""에이전트 도구. 기존 서비스 계층을 그대로 호출한다(화면 API와 숫자가 어긋나지 않게).

- 모든 도구는 로그인한 회원(ctx.user)의 데이터만 다룬다. user_id는 서버가 넣고 모델은 정하지 못한다.
- 계좌·카드 번호는 마스킹된 값만 돌려주고, 거래 결과의 가맹점명·적요는 '데이터'일 뿐이다.
- 조회 도구는 Result(facts, evidence, sources, links)를 돌려주고, 쓰기 도구는 확인 후에만 execute_write로 실행한다.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from fastapi.encoders import jsonable_encoder
from psycopg import Connection

from app.account import service as account_service
from app.agent import resolve
from app.agent.links import build_link
from app.agent.resolve import Clarify
from app.agent.schemas import Understanding
from app.card import service as card_service
from app.common.errors import AppError
from app.common.mask import mask_account_num, mask_name
from app.notification import service as notification_service
from app.spending import service as spending_service
from app.transfer import service as transfer_service
from app.user import profile as profile_service
from app.user import service as user_service

SHOW = 5          # 목록에 보여 줄 최대 건수
FETCH = 100       # 합계 계산을 위해 가져오는 최대 건수


@dataclass
class Ctx:
    conn: Connection
    user: dict
    today: date


@dataclass
class Result:
    facts: dict
    evidence: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    links: list = field(default_factory=list)


def _safe(value):
    return jsonable_encoder(value)


def _tx_evidence(items: list[dict], date_key="transaction_at", name_key="counterparty_name") -> list[dict]:
    return [{"tx_id": i.get("id"), "date": _safe(i[date_key])[:10], "merchant": i.get(name_key) or i.get("merchant") or "",
             "amount": i["amount"], "type": i.get("type") or i.get("kind"), "direction": i.get("direction")} for i in items[:SHOW]]


def _acc_name(a: dict) -> str:
    return a.get("nickname") or a.get("product_name") or "계좌"


def _mask_ip(ip: str | None) -> str | None:
    if not ip:
        return ip
    parts = ip.split(".")
    return ".".join(parts[:3] + ["***"]) if len(parts) == 4 else ip


def _mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}***@{domain}"


# ====================== 조회 ======================

def list_accounts(ctx: Ctx, u: Understanding) -> Result:
    items = account_service.list_accounts(ctx.conn, ctx.user["id"])
    slim = [{"nickname": i["nickname"] or i["product_name"], "product_name": i["product_name"],
             "account_num_masked": i["account_num_masked"], "balance": i["balance"], "status": i["status"],
             "is_favorite": i["is_favorite"]} for i in items]
    return Result({"items": slim, "total_balance": sum(i["balance"] for i in items), "count": len(items)})


def account_detail(ctx: Ctx, u: Understanding) -> Result:
    acc = resolve.resolve_account(ctx.conn, ctx.user["id"], u.account_hint)
    d = account_service.account_detail(ctx.conn, ctx.user["id"], acc["id"])
    lim = account_service.get_limits(ctx.conn, ctx.user["id"], acc["id"])
    return Result({"nickname": _acc_name(acc), "product_name": acc["product_name"], "account_num_masked": mask_account_num(acc["account_num"]),
                   "balance": d["balance"], "status": d["status"], "interest_rate": _safe(d["interest_rate"]),
                   "daily_limit": lim["daily_limit"], "month_limit": lim["month_limit"], "used_today": lim["used_today"],
                   "used_month": lim["used_month"], "remaining_today": lim["remaining_today"]},
                  links=[build_link("SCR-005", path_id=acc["id"])])


def account_limits(ctx: Ctx, u: Understanding) -> Result:
    acc = resolve.resolve_account(ctx.conn, ctx.user["id"], u.account_hint)
    lim = account_service.get_limits(ctx.conn, ctx.user["id"], acc["id"])
    return Result({"nickname": _acc_name(acc), **{k: lim[k] for k in ("daily_limit", "month_limit", "used_today", "used_month", "remaining_today")}},
                  links=[build_link("SCR-009", path_id=acc["id"], focus="limit", label="이체한도 바꾸러 가기")])


def search_transactions(ctx: Ctx, u: Understanding) -> Result:
    acc = resolve.resolve_account(ctx.conn, ctx.user["id"], u.account_hint, purpose="의 거래내역")
    p = resolve.resolve_period(u.period, ctx.today, default="LAST_3_MONTHS")
    try:
        res = account_service.list_transactions(
            ctx.conn, ctx.user["id"], acc["id"], from_date=p.from_date, to_date=p.to_date, direction=u.direction or "ALL",
            types=list(u.tx_types), min_amount=u.min_amount, max_amount=u.max_amount, q=u.query_text or u.merchant,
            sort="latest", page=1, size=FETCH)
    except AppError as e:
        raise Clarify(e.message, ["period"])
    items = res["items"]
    facts = {"account": _acc_name(acc), "period": p.label, "total": res["total"], "truncated": res["total"] > FETCH,
             "sum_in": sum(i["amount"] for i in items if i["direction"] == "IN"),
             "sum_out": sum(i["amount"] for i in items if i["direction"] == "OUT"),
             "items": [{"date": _safe(i["transaction_at"])[:10], "type": i["type"], "direction": i["direction"], "amount": i["amount"],
                        "counterparty": i["counterparty_name"], "memo": i["memo"], "new_balance": i["new_balance"]} for i in items[:SHOW]]}
    link = build_link("SCR-005", path_id=acc["id"], label="거래내역 더 보기", **{"from": p.from_date, "to": p.to_date, "q": u.query_text or u.merchant})
    return Result(facts, evidence=_tx_evidence(items), links=[link])


def list_recent_recipients(ctx: Ctx, u: Understanding) -> Result:
    items = transfer_service.recent_recipients(ctx.conn, ctx.user["id"])
    return Result({"items": [{"holder": i["holder_name_masked"], "account_num_masked": i["account_num_masked"],
                              "last_at": _safe(i["last_transferred_at"])[:10]} for i in items[:SHOW]], "count": len(items)})


def list_favorite_recipients(ctx: Ctx, u: Understanding) -> Result:
    items = transfer_service.list_favorites(ctx.conn, ctx.user["id"])
    return Result({"items": [{"alias": i["alias"], "holder": i["holder_name_masked"], "account_num_masked": i["account_num_masked"]}
                             for i in items[:SHOW * 2]], "count": len(items)})


def list_auto_transfers(ctx: Ctx, u: Understanding) -> Result:
    items = [i for i in transfer_service.list_auto_transfers(ctx.conn, ctx.user["id"]) if i["status"] == "ACTIVE"]
    return Result({"items": [{"to": i["to_holder_masked"], "amount": i["amount"], "memo": i["memo"], "cycle": i["cycle"], "run_day": i["run_day"],
                              "next_run_date": _safe(i["next_run_date"]), "last_result": i["last_result"]} for i in items],
                   "count": len(items)}, links=[build_link("SCR-007", label="자동이체 관리하러 가기")])


def list_cards(ctx: Ctx, u: Understanding) -> Result:
    items = card_service.list_cards(ctx.conn, ctx.user["id"])
    return Result({"items": [{"last4": i["last4"], "network": i["card_network"], "status": i["status"], "daily_limit": i["daily_limit"],
                              "overseas_enabled": i["overseas_enabled"]} for i in items], "count": len(items)},
                  links=[build_link("SCR-008")])


def card_payments(ctx: Ctx, u: Understanding) -> Result:
    card = resolve.resolve_card(ctx.conn, ctx.user["id"], u.card_hint)
    p = resolve.resolve_period(u.period, ctx.today, default="LAST_3_MONTHS")
    res = card_service.list_payments(ctx.conn, ctx.user["id"], card["id"], p.from_date, p.to_date, 1, FETCH)
    items = res["items"]
    last4 = card_service._view(card)["last4"]
    facts = {"card_last4": last4, "period": p.label, "total": res["total"], "sum": sum(i["amount"] for i in items), "truncated": res["total"] > FETCH,
             "items": [{"date": _safe(i["request_at"])[:10], "place": i["place"], "amount": i["amount"]} for i in items[:SHOW]]}
    ev = [{"tx_id": i["id"], "date": _safe(i["request_at"])[:10], "merchant": i["place"], "amount": i["amount"], "type": "CARD", "direction": "OUT"}
          for i in items[:SHOW]]
    return Result(facts, evidence=ev, links=[build_link("SCR-011", path_id=card["id"], label="카드 사용내역 더 보기")])


def list_notifications(ctx: Ctx, u: Understanding) -> Result:
    res = notification_service.list_notifications(ctx.conn, ctx.user["id"], False, SHOW)
    return Result({"unread_count": res["unread_count"],
                   "items": [{"type": i["type"], "message": i["message"], "date": _safe(i["created_at"])[:10], "read": i["read_at"] is not None}
                             for i in res["items"]]})


def login_history(ctx: Ctx, u: Understanding) -> Result:
    items = user_service.login_histories(ctx.conn, ctx.user["id"], SHOW)
    suspicious = ctx.conn.execute("SELECT count(*) AS n FROM notifications WHERE user_id = %s AND type = 'SUSPICIOUS_LOGIN'",
                                  (ctx.user["id"],)).fetchone()["n"]
    return Result({"items": [{"date": _safe(i["created_at"])[:16].replace("T", " "), "ip": _mask_ip(i["ip"]), "success": i["success"]} for i in items],
                   "suspicious_alerts": suspicious, "failed_recent": sum(1 for i in items if not i["success"])})


def close_check(ctx: Ctx, u: Understanding) -> Result:
    acc = resolve.resolve_account(ctx.conn, ctx.user["id"], u.account_hint)
    chk = account_service.close_check(ctx.conn, ctx.user["id"], acc["id"])
    links = [build_link("SCR-010", path_id=acc["id"])] if chk["closable"] else []
    return Result({"account": _acc_name(acc), "closable": chk["closable"], "reasons": [r["message"] for r in chk["reasons"]]}, links=links)


def products_info(ctx: Ctx, u: Understanding) -> Result:
    products = account_service.list_products(ctx.conn)
    hint = resolve._norm(u.product_hint)
    if hint:
        picked = [p for p in products if hint in resolve._norm(p["product_name"]) or resolve._norm(p["product_name"]) in hint
                  or any(k in hint for k in _product_keywords(p["product_name"]))]
        products = picked or products
    items = []
    for p in products:
        el = account_service.eligibility(ctx.conn, ctx.user, p["id"])
        items.append({"product_id": p["id"], "name": p["product_name"], "interest_rate": _safe(p["interest_rate"]), "description": p["description"],
                      "join_condition": p["join_condition"], "rate_condition": p["rate_condition"], "eligible": el["eligible"],
                      "reasons": [r["message"] for r in el["reasons"]], "reason_codes": [r["code"] for r in el["reasons"]]})
    return Result({"items": items, "count": len(items)}, sources=[{"title": i["name"], "type": "PRODUCT"} for i in items],
                  links=[build_link("SCR-004", product_id=items[0]["product_id"], label="계좌 개설하러 가기")] if len(items) == 1 and items[0]["eligible"] else [])


def _product_keywords(name: str) -> list[str]:
    return [w for w in ("청년", "파킹", "시니어", "기본", "고금리") if w in name]


def knowledge_qa(ctx: Ctx, u: Understanding, message: str) -> Result:
    from app.agent.rag import search as rag_search
    from app.agent.rag import label
    res = rag_search(ctx.conn, u.query_text or message)
    seen, sources = set(), []
    for p in res["passages"]:
        name = label(p)
        if name not in seen:  # 같은 출처가 여러 번 나오지 않게
            seen.add(name)
            sources.append({"title": name, "type": p["type"], "version": p.get("version")})
    return Result({"found": res["found"], "passages": res["passages"], "reason": res.get("reason")}, sources=sources)


# ---------- 소비 ----------

def _months(ctx: Ctx, u: Understanding) -> tuple[list[str], str]:
    p = resolve.resolve_period(u.period, ctx.today, default="THIS_MONTH")
    return p.months[-12:], p.label


def spending_summary(ctx: Ctx, u: Understanding) -> Result:
    months, label = _months(ctx, u)
    items = [spending_service.summary(ctx.conn, ctx.user["id"], m) for m in months]
    facts = {"period": label, "months": [{k: v[k] for k in ("month", "total", "count", "card_total", "transfer_other_total", "prev_total", "diff", "diff_rate")}
                                         for v in items], "total": sum(v["total"] for v in items), "count": sum(v["count"] for v in items)}
    return Result(facts, links=[build_link("SCR-014", month=months[-1])])


def spending_by_category(ctx: Ctx, u: Understanding) -> Result:
    months, label = _months(ctx, u)
    code = resolve.resolve_category(ctx.conn, u.category)
    agg: dict[str, dict] = {}
    for m in months:
        for i in spending_service.by_category(ctx.conn, ctx.user["id"], m)["items"]:
            a = agg.setdefault(i["code"], {"code": i["code"], "name": i["name"], "amount": 0, "count": 0})
            a["amount"] += i["amount"]
            a["count"] += i["count"]
    total = sum(a["amount"] for a in agg.values())
    items = sorted(agg.values(), key=lambda a: -a["amount"])
    for a in items:
        a["share"] = round(a["amount"] * 100 / total, 1) if total else 0.0
    facts = {"period": label, "total": total, "items": items}
    evidence = []
    if code:
        name = spending_service.category_table(ctx.conn)[code]["name"]
        hit = next((a for a in items if a["code"] == code), None)
        facts["category"] = {"code": code, "name": name, "amount": hit["amount"] if hit else 0, "count": hit["count"] if hit else 0,
                             "share": hit["share"] if hit else 0.0}
        for m in months:
            for t in spending_service.transactions(ctx.conn, ctx.user["id"], m, code, 1, SHOW)["items"]:
                evidence.append({"tx_id": t["id"], "date": _safe(t["at"])[:10], "merchant": t["merchant"], "amount": t["amount"],
                                 "type": t["kind"], "direction": "OUT"})
        evidence = evidence[:SHOW]
    return Result(facts, evidence=evidence, links=[build_link("SCR-014", month=months[-1])])


def spending_top_merchants(ctx: Ctx, u: Understanding) -> Result:
    months, label = _months(ctx, u)
    merged: dict[tuple, dict] = {}
    for m in months:
        for g in spending_service.top_merchants(ctx.conn, ctx.user["id"], m, 20)["items"]:
            a = merged.setdefault((g["merchant"], g["category"]), {"merchant": g["merchant"], "category_name": g["category_name"], "amount": 0, "count": 0})
            a["amount"] += g["amount"]
            a["count"] += g["count"]
    items = sorted(merged.values(), key=lambda g: -g["amount"])[:SHOW]
    return Result({"period": label, "items": items}, links=[build_link("SCR-014", month=months[-1])])


def spending_compare(ctx: Ctx, u: Understanding) -> Result:
    cur = resolve.resolve_period(u.period, ctx.today, default="THIS_MONTH")
    base = resolve.resolve_period(u.compare_period, ctx.today, default="LAST_MONTH")
    if len(cur.months) != 1 or len(base.months) != 1:
        raise Clarify("비교할 두 달을 알려 주세요. (예: 이번 달과 지난달)", ["period"])
    if cur.months[0] == base.months[0]:
        base = resolve.resolve_period(None, ctx.today, default="LAST_MONTH")
    res = spending_service.compare(ctx.conn, ctx.user["id"], base.months[0], cur.months[0])
    return Result({"month_a": res["month_a"], "month_b": res["month_b"], "total_a": res["total_a"], "total_b": res["total_b"],
                   "diff": res["diff"], "diff_rate": res["diff_rate"],
                   "items": [{"name": i["name"], "amount_a": i["amount_a"], "amount_b": i["amount_b"], "diff": i["diff"]} for i in res["items"][:SHOW]]},
                  links=[build_link("SCR-014", month=cur.months[0])])


def budget_status(ctx: Ctx, u: Understanding) -> Result:
    months, label = _months(ctx, u)
    code = resolve.resolve_category(ctx.conn, u.category)
    items = spending_service.list_budgets(ctx.conn, ctx.user["id"], months[-1])["items"]
    if code:
        items = [i for i in items if i["category_code"] == code]
    return Result({"month": months[-1], "items": [{k: i[k] for k in ("category_name", "amount", "spent", "remaining", "usage_pct", "status")} for i in items]},
                  links=[build_link("SCR-016", month=months[-1], label="예산 설정하러 가기")])


# ====================== 쓰기(확인 후 실행) ======================

def prepare_write(ctx: Ctx, action: str, u: Understanding) -> dict:
    """실행하지 않고 확인 카드에 보여 줄 내용(summary)과 실행 인자(params)를 만든다."""
    if action == "SET_BUDGET":
        if not u.amount or u.amount <= 0:
            raise Clarify("예산을 얼마로 설정할까요?", ["amount"])
        if u.amount > 1_000_000_000:
            raise Clarify("예산 금액이 너무 커요. 10억 원 이하로 알려 주세요.", ["amount"])
        p = resolve.resolve_period(u.period, ctx.today, default="THIS_MONTH")
        month = p.months[0]
        code = resolve.resolve_category(ctx.conn, u.category)
        label = spending_service.category_table(ctx.conn)[code]["name"] if code else "월 전체"
        return {"kind": action, "params": {"month": month, "category_code": code, "amount": u.amount},
                "summary": f"{int(month[5:])}월 {label} 예산을 {u.amount:,}원으로 설정할까요?"}
    if action == "RECATEGORIZE_MERCHANT":
        if not u.merchant:
            raise Clarify("어느 가맹점의 분류를 바꿀까요?", ["merchant"])
        code = resolve.resolve_category(ctx.conn, u.category, required=True)
        if code == spending_service.TRANSFER_CATEGORY:
            raise Clarify("'송금·이체'는 타인 이체 전용이라 가맹점에는 지정할 수 없어요. 다른 항목을 골라 주세요.", ["category"],
                          [c["name"] for c in spending_service.category_table(ctx.conn).values() if c["code"] != "TRANSFER"])
        name = spending_service.category_table(ctx.conn)[code]["name"]
        return {"kind": action, "params": {"merchant": u.merchant, "category_code": code},
                "summary": f"'{u.merchant}'을(를) '{name}'(으)로 분류할까요? 같은 가맹점의 다른 결제도 같은 항목으로 집계돼요."}
    if action == "TOGGLE_FAVORITE_ACCOUNT":
        acc = resolve.resolve_account(ctx.conn, ctx.user["id"], u.account_hint, purpose="를 즐겨찾기에 바꿀까요")
        on = u.on if u.on is not None else not acc["is_favorite"]
        return {"kind": action, "params": {"account_id": str(acc["id"]), "on": on},
                "summary": f"'{_acc_name(acc)}' 계좌를 즐겨찾기에서 {'추가' if on else '해제'}할까요?"}
    if action == "REQUEST_STATEMENT":
        acc = resolve.resolve_account(ctx.conn, ctx.user["id"], u.account_hint, purpose="의 거래내역을 보낼까요")
        if u.period is None:
            raise Clarify("어느 기간의 거래내역을 보내 드릴까요? (예: 지난달, 최근 3개월)", ["period"], ["지난달", "최근 3개월"])
        p = resolve.resolve_period(u.period, ctx.today)
        return {"kind": action, "params": {"account_id": str(acc["id"]), "from": p.from_date.isoformat(), "to": p.to_date.isoformat()},
                "summary": f"'{_acc_name(acc)}' 계좌의 {p.label} 거래내역을 {_mask_email(ctx.user['email'])}로 보낼까요?"}
    raise AppError(500, "UNKNOWN_ACTION", "알 수 없는 쓰기 동작입니다")


def execute_write(ctx: Ctx, pending: dict) -> dict:
    """사용자가 승인한 쓰기 동작을 실행한다. 실패하면 error 메시지를 담아 돌려준다."""
    k, p = pending["kind"], pending["params"]
    uid = ctx.user["id"]
    try:
        if k == "SET_BUDGET":
            r = spending_service.set_budget(ctx.conn, uid, p["month"], p["category_code"], p["amount"])
            return {"done": True, "kind": k, "category": r["category_name"], "amount": r["amount"], "month": r["month"], "spent": r["spent"],
                    "usage_pct": r["usage_pct"], "status": r["status"]}
        if k == "RECATEGORIZE_MERCHANT":
            r = spending_service.set_merchant_category(ctx.conn, uid, p["merchant"], p["category_code"])
            return {"done": True, "kind": k, "merchant": p["merchant"], "category": r["category_name"]}
        if k == "TOGGLE_FAVORITE_ACCOUNT":
            r = account_service.set_favorite(ctx.conn, uid, p["account_id"], p["on"])
            return {"done": True, "kind": k, "account": r["nickname"] or r["product_name"], "is_favorite": r["is_favorite"]}
        if k == "REQUEST_STATEMENT":
            r = account_service.request_statement(ctx.conn, ctx.user, p["account_id"], date.fromisoformat(p["from"]), date.fromisoformat(p["to"]), None)
            return {"done": r["status"] == "SENT", "kind": k, "status": r["status"], "count": r["count"], "email": _mask_email(r["email"]),
                    "error": None if r["status"] == "SENT" else r["message"]}
    except AppError as e:
        return {"done": False, "kind": k, "error": e.message}
    return {"done": False, "kind": k, "error": "지원하지 않는 동작입니다"}


# ====================== 화면 링크 ======================

def _transfer_slots(ctx: Ctx, u: Understanding, *, need: bool) -> tuple[dict, dict]:
    params, facts = {}, {}
    acc = None
    if u.account_hint:
        acc = resolve.resolve_account(ctx.conn, ctx.user["id"], u.account_hint, purpose="에서 보낼까요")
    else:
        rows = account_service.list_accounts(ctx.conn, ctx.user["id"])
        if len(rows) == 1:
            acc = {"id": rows[0]["id"]}
    if acc:
        params["from_account_id"] = acc["id"]
    rec = resolve.resolve_recipient(ctx.conn, ctx.user["id"], u.recipient_hint)
    if rec:
        params.update({k: v for k, v in rec.items() if k in ("recipient_id", "to_account_num")})
        facts["recipient"] = rec.get("label") or "입력하신 계좌"
    if u.amount:
        params["amount"] = u.amount
        facts["amount"] = u.amount
    if need:
        favs = resolve.favorite_names(ctx.conn, ctx.user["id"])
        if u.recipient_hint and not rec:
            raise Clarify(f"'{u.recipient_hint}'님을 자주 쓰는 받는 계좌에서 찾지 못했어요. 받는 계좌번호를 알려 주시거나 이체 화면에서 직접 입력해 주세요.",
                          ["recipient"], favs)
        if not rec and not u.amount:
            raise Clarify("누구에게 얼마를 보낼까요?", ["recipient", "amount"], favs)
        if not rec:
            raise Clarify("누구에게 보낼까요?", ["recipient"], favs)
        if not u.amount:
            raise Clarify("얼마를 보낼까요?", ["amount"])
    if u.memo:
        params["memo"] = u.memo
    return params, facts


def build_links(ctx: Ctx, action: str, u: Understanding) -> Result:
    """PIN·인증이 필요한 동작은 직접 하지 않고 해당 화면 링크만 만든다."""
    uid = ctx.user["id"]
    if action == "GO_TRANSFER":
        params, facts = _transfer_slots(ctx, u, need=True)
        return Result({"kind": action, **facts}, links=[build_link("SCR-006", label="이체 화면으로 이동", **params)])
    if action == "GO_AUTO_TRANSFER":
        params, facts = _transfer_slots(ctx, u, need=False)
        return Result({"kind": action, **facts}, links=[build_link("SCR-007", **params)])
    if action in ("GO_CHANGE_LIMIT", "GO_UNLOCK_ACCOUNT", "GO_CLOSE_ACCOUNT", "GO_ISSUE_CARD", "GO_ACCOUNT_DETAIL"):
        hint = u.account_hint
        if action == "GO_UNLOCK_ACCOUNT" and not hint:
            sus = [a for a in account_service.list_accounts(ctx.conn, uid) if a["status"] == "SUSPENDED"]
            if len(sus) == 1:
                hint = sus[0]["nickname"] or sus[0]["product_name"]
        acc = resolve.resolve_account(ctx.conn, uid, hint)
        name = _acc_name(acc)
        if action == "GO_CHANGE_LIMIT":
            lim = account_service.get_limits(ctx.conn, uid, acc["id"])
            return Result({"kind": action, "account": name, "daily_limit": lim["daily_limit"], "month_limit": lim["month_limit"]},
                          links=[build_link("SCR-009", path_id=acc["id"], focus="limit", label="이체한도 바꾸러 가기")])
        if action == "GO_UNLOCK_ACCOUNT":
            return Result({"kind": action, "account": name, "status": acc["status"]},
                          links=[build_link("SCR-009", path_id=acc["id"], focus="unlock", label="거래중지 해제하러 가기")])
        if action == "GO_CLOSE_ACCOUNT":
            chk = account_service.close_check(ctx.conn, uid, acc["id"])
            return Result({"kind": action, "account": name, "closable": chk["closable"], "reasons": [r["message"] for r in chk["reasons"]]},
                          links=[build_link("SCR-010", path_id=acc["id"], label="계좌 해지 화면으로 가기")] if chk["closable"] else
                          [build_link("SCR-005", path_id=acc["id"], label="계좌 상세 보기")])
        if action == "GO_ISSUE_CARD":
            return Result({"kind": action, "account": name}, links=[build_link("SCR-012", account_id=acc["id"], label="체크카드 발급하러 가기")])
        return Result({"kind": action, "account": name}, links=[build_link("SCR-005", path_id=acc["id"])])
    if action == "GO_OPEN_ACCOUNT":
        pid, name = None, None
        if u.product_hint:
            for p in account_service.list_products(ctx.conn):
                hint = resolve._norm(u.product_hint)
                if hint in resolve._norm(p["product_name"]) or any(k in hint for k in _product_keywords(p["product_name"])):
                    pid, name = p["id"], p["product_name"]
                    break
        return Result({"kind": action, "product": name}, links=[build_link("SCR-004", product_id=pid, label="계좌 개설하러 가기")])
    if action == "GO_CARD_MANAGE":
        card = resolve.resolve_card(ctx.conn, uid, u.card_hint)
        focus = u.focus if u.focus in ("limit", "lost", "suspend", "reissue", "cancel", "resume") else None
        label = {"lost": "카드 분실 신고하러 가기", "suspend": "카드 정지하러 가기", "reissue": "카드 재발급하러 가기",
                 "cancel": "카드 해지하러 가기", "limit": "카드 한도 바꾸러 가기", "resume": "카드 정지 해제하러 가기"}.get(focus, "카드 관리로 가기")
        return Result({"kind": action, "focus": focus, "card_last4": card_service._view(card)["last4"], "status": card["status"]},
                      links=[build_link("SCR-011", path_id=card["id"], focus=focus, label=label)])
    if action == "GO_PROFILE":
        focus = u.focus if u.focus in ("profile", "password", "withdraw", "logout") else "profile"
        facts = {"kind": action, "focus": focus}
        if focus == "withdraw":
            chk = profile_service.withdraw_check(ctx.conn, uid)
            facts.update({"allowed": chk["allowed"], "reasons": [r["message"] for r in chk["reasons"]]})
        label = {"profile": "내 정보 변경하러 가기", "password": "비밀번호 재설정하러 가기", "withdraw": "회원 탈퇴 화면으로 가기",
                 "logout": "로그아웃하러 가기"}[focus]
        return Result(facts, links=[build_link("SCR-013", focus=focus, label=label)])
    if action in ("GO_SIGNUP", "GO_LOGIN"):
        return Result({"kind": action}, links=[build_link("SCR-002" if action == "GO_SIGNUP" else "SCR-001")])
    if action in ("GO_SPENDING_REPORT", "GO_BUDGET_SETTING"):
        months, _ = _months(ctx, u)
        return Result({"kind": action, "month": months[-1]}, links=[build_link("SCR-014" if action == "GO_SPENDING_REPORT" else "SCR-016", month=months[-1])])
    raise AppError(500, "UNKNOWN_ACTION", "알 수 없는 화면 이동입니다")


# ====================== 실행 분기 ======================

READERS = {
    "LIST_ACCOUNTS": list_accounts, "ACCOUNT_DETAIL": account_detail, "ACCOUNT_LIMITS": account_limits,
    "SEARCH_TRANSACTIONS": search_transactions, "LIST_RECENT_RECIPIENTS": list_recent_recipients,
    "LIST_FAVORITE_RECIPIENTS": list_favorite_recipients, "LIST_AUTO_TRANSFERS": list_auto_transfers, "LIST_CARDS": list_cards,
    "CARD_PAYMENTS": card_payments, "LIST_NOTIFICATIONS": list_notifications, "LOGIN_HISTORY": login_history,
    "CLOSE_CHECK": close_check, "PRODUCTS_INFO": products_info, "SPENDING_SUMMARY": spending_summary,
    "SPENDING_BY_CATEGORY": spending_by_category, "SPENDING_TOP_MERCHANTS": spending_top_merchants,
    "SPENDING_COMPARE": spending_compare, "BUDGET_STATUS": budget_status,
}
