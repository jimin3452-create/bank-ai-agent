"""도구 결과(facts)를 한국어 문장으로 만든다(결정적). 모델이 문장을 다듬더라도 숫자가 틀리면 이 문장으로 되돌린다.

숫자는 도구가 계산한 값만 쓴다. 모델 응답은 numbers_are_grounded로 검사해 facts에 없는 숫자가 있으면 버린다.
"""
import re
from datetime import date

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
STATUS_KO = {"ACTIVE": "정상", "SUSPENDED": "정지", "LOST": "분실", "CLOSED": "해지", "CANCELED": "해지", "REISSUED": "재발급됨"}
ACCOUNT_STATUS_KO = {"ACTIVE": "정상", "SUSPENDED": "거래중지", "CLOSED": "해지"}

SMALLTALK = ("안녕하세요! 계좌·거래내역 조회, 소비 분석, 예산 설정을 도와드려요. "
             "이체나 카드 분실 신고처럼 인증이 필요한 일은 해당 화면으로 안내해 드릴게요.")
OUT_OF_SCOPE = ("그런 요청은 도와드리기 어려워요. 투자·금융상품 추천, 대출·세금 상담, 다른 사람의 정보 조회, 앱과 무관한 질문은 답하지 않아요. "
                "대신 내 계좌·거래내역이나 이번 달 소비, 예산을 확인해 드릴까요?")
LLM_ERROR = "지금은 분석할 수 없어요. 잠시 후 다시 시도해 주시거나, 아래 화면에서 직접 확인해 주세요."
NO_KNOWLEDGE = ("제가 가진 안내 문서에서는 해당 내용을 찾지 못했어요. "
                "앱 사용 방법이나 약관·상품 안내, 계좌·소비 관련 질문은 도와드릴 수 있어요.")


def won(n: int) -> str:
    return f"{n:,}원"


def short_date(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.month}월 {d.day}일"


def _month(label: str) -> int:
    return int(label[5:7])


def _signed(n: int) -> str:
    return f"+{n:,}원" if n > 0 else f"-{abs(n):,}원" if n < 0 else "변동 없음"


def _cycle(i: dict) -> str:
    return f"매주 {WEEKDAYS[i['run_day']]}요일" if i["cycle"] == "WEEKLY" else f"매월 {i['run_day']}일"


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)


def clarify(question: str, options: list[str]) -> str:
    return question + (f"\n(예: {', '.join(options[:12])})" if options else "")


# ---------- 조회 ----------

def render(action: str, f: dict) -> str:
    fn = _RENDERERS.get(action)
    return fn(f) if fn else ""


def _accounts(f):
    if not f["count"]:
        return "개설된 계좌가 없어요. 계좌 개설을 도와드릴까요?"
    lines = [f"{i['nickname']} ({i['account_num_masked']}): {won(i['balance'])}" + (" · 거래중지" if i["status"] == "SUSPENDED" else "") +
             (" ★" if i["is_favorite"] else "") for i in f["items"][:5]]
    return f"계좌는 {f['count']}개이고 잔액 합계는 {won(f['total_balance'])}이에요.\n" + _bullets(lines)


def _account_detail(f):
    return (f"'{f['nickname']}' 계좌({f['account_num_masked']})는 {f['product_name']}이고, 잔액은 {won(f['balance'])}, 상태는 {ACCOUNT_STATUS_KO.get(f['status'], f['status'])}이에요. "
            f"연 금리는 {f['interest_rate']}%예요. 이체한도는 1일 {won(f['daily_limit'])}, 1달 {won(f['month_limit'])}이고 오늘 {won(f['used_today'])}을 썼어요.")


def _limits(f):
    return (f"'{f['nickname']}' 계좌의 이체한도는 1일 {won(f['daily_limit'])}, 1달 {won(f['month_limit'])}이에요. "
            f"오늘 {won(f['used_today'])}, 이번 달 {won(f['used_month'])}을 썼고 오늘 남은 한도는 {won(f['remaining_today'])}이에요.")


def _transactions(f):
    if not f["total"]:
        return f"'{f['account']}' 계좌의 {f['period']} 기간에는 조건에 맞는 거래가 없어요."
    kind = {"IN": "입금", "OUT": "출금"}
    lines = [f"{short_date(i['date'])} {i['counterparty'] or i['type']} {kind.get(i['direction'], '')} {won(i['amount'])}" for i in f["items"]]
    note = " (건수가 많아 최근 100건 기준이에요)" if f["truncated"] else ""
    return (f"'{f['account']}' 계좌의 {f['period']} 기간에 조건에 맞는 거래는 {f['total']}건이에요{note}. "
            f"입금 합계 {won(f['sum_in'])}, 출금 합계 {won(f['sum_out'])}이에요.\n" + _bullets(lines))


def _recipients(f):
    if not f["count"]:
        return "저장되거나 최근에 보낸 받는 계좌가 없어요."
    lines = [(f"{i['alias']} · {i['holder']}" if i.get("alias") else i["holder"]) + f" ({i['account_num_masked']})" +
             (f" · 마지막 {short_date(i['last_at'])}" if i.get("last_at") else "") for i in f["items"]]
    return f"받는 계좌는 {f['count']}개예요.\n" + _bullets(lines)


def _auto(f):
    if not f["count"]:
        return "사용 중인 자동이체가 없어요."
    lines = [f"{i['to']}에게 {won(i['amount'])} · {_cycle(i)} · 다음 실행 {short_date(i['next_run_date'])}" +
             (f" · 최근 {'성공' if i['last_result'] == 'SUCCESS' else '실패'}" if i["last_result"] else "") for i in f["items"]]
    return f"사용 중인 자동이체는 {f['count']}건이에요.\n" + _bullets(lines)


def _cards(f):
    if not f["count"]:
        return "사용 중인 체크카드가 없어요. 카드를 발급받으시겠어요?"
    lines = [f"끝 {i['last4']} ({i['network']}) · {STATUS_KO.get(i['status'], i['status'])} · 일일 한도 {won(i['daily_limit'])} · 해외결제 {'켜짐' if i['overseas_enabled'] else '꺼짐'}"
             for i in f["items"]]
    return f"체크카드는 {f['count']}장이에요.\n" + _bullets(lines)


def _card_payments(f):
    if not f["total"]:
        return f"끝 {f['card_last4']} 카드의 {f['period']} 기간 사용내역이 없어요."
    lines = [f"{short_date(i['date'])} {i['place']} {won(i['amount'])}" for i in f["items"]]
    note = " (건수가 많아 최근 100건 기준이에요)" if f["truncated"] else ""
    return f"끝 {f['card_last4']} 카드의 {f['period']} 기간 사용내역은 {f['total']}건, 합계 {won(f['sum'])}이에요{note}.\n" + _bullets(lines)


def _notifications(f):
    if not f["items"]:
        return "받은 알림이 없어요."
    lines = [f"{short_date(i['date'])} {i['message']}" + ("" if i["read"] else " (안 읽음)") for i in f["items"]]
    return f"안 읽은 알림은 {f['unread_count']}개예요. 최근 알림이에요.\n" + _bullets(lines)


def _login_history(f):
    if not f["items"]:
        return "접속 기록이 없어요."
    lines = [f"{i['date']} · IP {i['ip']} · {'성공' if i['success'] else '실패'}" for i in f["items"]]
    warn = f" 이상 접속 알림이 {f['suspicious_alerts']}건 있었어요. 본인이 아니라면 비밀번호를 바꿔 주세요." if f["suspicious_alerts"] else " 이상 접속 알림은 없어요."
    return "최근 접속 기록이에요." + warn + "\n" + _bullets(lines)


def _close_check(f):
    if f["closable"]:
        return f"'{f['account']}' 계좌는 지금 해지할 수 있는 상태예요. 해지는 되돌릴 수 없어서 화면에서 PIN으로 확인해야 해요."
    return f"'{f['account']}' 계좌는 지금 해지할 수 없어요.\n" + _bullets(f["reasons"])


def _products(f):
    if not f["items"]:
        return "안내할 상품이 없어요."
    lines = []
    for i in f["items"]:
        elig = "가입할 수 있어요" if i["eligible"] else "지금은 가입할 수 없어요(" + "; ".join(i["reasons"]) + ")"
        lines.append(f"{i['name']}: 연 {i['interest_rate']}% · {i['join_condition']} · {i['rate_condition']} · 내 가입 여부: {elig}")
    return "계좌 상품 안내예요. 금리는 안내용이에요.\n" + _bullets(lines)


def _excerpt(text: str, limit: int = 380) -> str:
    """청크 앞의 `[제목]` 머리줄을 떼고 문장 끝에서 자른다."""
    body = re.sub(r"^\[[^\]]*\]\s*", "", text.strip())
    body = re.sub(r"\s+", " ", body)
    if len(body) <= limit:
        return body
    cut = body[:limit]
    end = max(cut.rfind("다. "), cut.rfind("요. "), cut.rfind(". "))
    return (cut[:end + 1] if end > limit // 2 else cut.rstrip()) + " …"


def _knowledge(f):
    """모델 없이 쓸 수 있는 결정적 답변: 가장 관련 있는 문서의 핵심 부분을 그대로 보여 준다."""
    if not f["found"]:
        if f.get("reason") in ("embedder-unavailable", "embedding-failed"):
            return "지금은 안내 문서를 검색할 수 없어요. 잠시 후 다시 시도해 주세요."
        return NO_KNOWLEDGE
    first = f["passages"][0]
    return f"관련 안내예요. ({first['heading'].split(' (')[0]})\n{_excerpt(first['text'])}"


LAW_NOTE = "※ 일반적인 법령·약관 안내이며 개별 사안에 대한 법률 자문이 아니에요."
MARKET_NOTE = "※ 시중 은행 상품은 공시 기준 정보이며 추천이 아니에요. 가입 전에 해당 은행에서 최신 조건을 확인해 주세요."


def knowledge_footer(f: dict, sources: list[dict]) -> str:
    """출처와 안내 문구는 모델이 아니라 서버가 붙인다(모델이 출처를 지어내지 못하게)."""
    if not f.get("found") or not sources:
        return ""
    lines = ["출처: " + " / ".join(s["title"] for s in sources[:3])]
    if any(p["type"] in ("LAW", "STANDARD_TERMS") for p in f["passages"]):
        lines.append(LAW_NOTE)
    if any(p["type"] == "MARKET_PRODUCT" for p in f["passages"]):
        lines.append(MARKET_NOTE)
    return "\n".join(lines)


# ---------- 소비 ----------

def _spending_summary(f):
    if len(f["months"]) == 1:
        m = f["months"][0]
        text = f"{_month(m['month'])}월 소비는 {won(m['total'])}이에요 (카드 {won(m['card_total'])} + 타인 이체 {won(m['transfer_other_total'])}, {m['count']}건)."
        if m["prev_total"]:
            text += f" 전월보다 {_signed(m['diff'])}" + (f"({m['diff_rate']}%)" if m["diff_rate"] is not None else "") + "이에요."
        return text
    lines = [f"{_month(m['month'])}월: {won(m['total'])} ({m['count']}건)" for m in f["months"]]
    return f"{f['period']} 소비는 모두 {won(f['total'])}이에요 ({f['count']}건).\n" + _bullets(lines)


def _spending_by_category(f):
    if not f["total"]:
        return f"{f['period']}에는 소비 내역이 없어요."
    if f.get("category"):
        c = f["category"]
        return f"{f['period']} {c['name']} 소비는 {won(c['amount'])}이에요 ({c['count']}건, 전체의 {c['share']}%)."
    lines = [f"{i['name']}: {won(i['amount'])} ({i['share']}%)" for i in f["items"][:5]]
    return f"{f['period']} 소비는 {won(f['total'])}이에요. 항목별로는 이렇게 나뉘어요.\n" + _bullets(lines)


def _top_merchants(f):
    if not f["items"]:
        return f"{f['period']}에는 소비 내역이 없어요."
    return f"{f['period']}에 가장 많이 쓴 곳이에요.\n" + _bullets([f"{i['merchant']}: {won(i['amount'])} ({i['count']}건)" for i in f["items"]])


def _compare(f):
    text = f"{_month(f['month_a'])}월 {won(f['total_a'])}에서 {_month(f['month_b'])}월 {won(f['total_b'])}으로 {_signed(f['diff'])}" + \
           (f"({f['diff_rate']}%)" if f["diff_rate"] is not None else "") + " 달라졌어요."
    ups = [i for i in f["items"] if i["diff"] > 0][:3]
    if ups:
        text += "\n가장 늘어난 항목이에요.\n" + _bullets([f"{i['name']}: {_signed(i['diff'])}" for i in ups])
    return text


def _budget(f):
    if not f["items"]:
        return f"{_month(f['month'])}월에 설정된 예산이 없어요. 예산을 정해 드릴까요?"
    status = {"OK": "여유 있음", "WARN": "80% 이상 사용", "OVER": "예산 초과"}
    lines = [f"{i['category_name']}: 예산 {won(i['amount'])} 중 {won(i['spent'])} 사용 ({i['usage_pct']}%) · {status[i['status']]}" for i in f["items"]]
    return f"{_month(f['month'])}월 예산 현황이에요.\n" + _bullets(lines)


# ---------- 쓰기 결과 ----------

def render_write(f: dict) -> str:
    if not f.get("done"):
        return f"처리하지 못했어요: {f.get('error') or '알 수 없는 오류'}"
    k = f["kind"]
    if k == "SET_BUDGET":
        return f"{_month(f['month'])}월 {f['category']} 예산을 {won(f['amount'])}으로 설정했어요. 지금까지 {won(f['spent'])}({f['usage_pct']}%)을 썼어요."
    if k == "RECATEGORIZE_MERCHANT":
        return f"'{f['merchant']}'을(를) '{f['category']}'(으)로 분류했어요. 소비 리포트에 바로 반영돼요."
    if k == "TOGGLE_FAVORITE_ACCOUNT":
        return f"'{f['account']}' 계좌를 즐겨찾기에서 {'추가' if f['is_favorite'] else '해제'}했어요."
    if k == "REQUEST_STATEMENT":
        return f"거래내역 {f['count']}건을 {f['email']}로 보냈어요. 메일함을 확인해 주세요."
    return "처리했어요."


# ---------- 화면 링크 ----------

def render_link(f: dict) -> str:
    k = f["kind"]
    if k == "GO_TRANSFER":
        who = f"{f['recipient']}님께 " if f.get("recipient") else ""
        amt = f"{won(f['amount'])} " if f.get("amount") else ""
        return f"{who}{amt}이체는 이체 화면에서 PIN으로 확인한 뒤 진행할 수 있어요. 말씀하신 받는 분과 금액은 미리 채워 두었어요."
    if k == "GO_AUTO_TRANSFER":
        return "자동이체는 등록할 때 PIN 확인이 필요해서 자동이체 화면에서 진행해 주세요. 알려 주신 내용은 미리 채워 두었어요."
    if k == "GO_CHANGE_LIMIT":
        return (f"'{f['account']}' 계좌의 현재 이체한도는 1일 {won(f['daily_limit'])}, 1달 {won(f['month_limit'])}이에요. "
                "한도 변경은 PIN 확인이 필요해서 화면에서 진행해 주세요.")
    if k == "GO_UNLOCK_ACCOUNT":
        if f["status"] == "SUSPENDED":
            return f"'{f['account']}' 계좌는 거래중지 상태예요. 이메일 인증번호로 본인확인을 하면 해제할 수 있어요. 아래 화면에서 진행해 주세요."
        return f"'{f['account']}' 계좌는 현재 거래중지 상태가 아니에요. 필요하면 계좌 관리 화면에서 확인해 주세요."
    if k == "GO_CLOSE_ACCOUNT":
        if f["closable"]:
            return f"'{f['account']}' 계좌는 해지할 수 있는 상태예요. 해지는 되돌릴 수 없어서 화면에서 PIN으로 확인한 뒤 진행해 주세요."
        return f"'{f['account']}' 계좌는 지금 해지할 수 없어요.\n" + _bullets(f["reasons"])
    if k == "GO_OPEN_ACCOUNT":
        prod = f"{f['product']} " if f.get("product") else ""
        return f"{prod}계좌 개설은 약관 동의와 통장 비밀번호 설정이 필요해서 개설 화면에서 진행해 주세요."
    if k == "GO_ISSUE_CARD":
        return f"'{f['account']}' 계좌에 연결할 체크카드는 발급 화면에서 신청해 주세요."
    if k == "GO_CARD_MANAGE":
        if f.get("focus") == "lost":
            return (f"카드를 잃어버리셨군요. 바로 카드 화면에서 분실 신고를 해 주세요. PIN 확인 후 끝 {f['card_last4']} 카드가 즉시 사용 정지돼요.")
        return f"끝 {f['card_last4']} 카드의 변경은 PIN 확인이 필요해서 카드 화면에서 진행해 주세요."
    if k == "GO_PROFILE":
        if f["focus"] == "withdraw":
            return ("회원 탈퇴는 아래 화면에서 진행할 수 있어요." if f["allowed"] else "지금은 탈퇴할 수 없어요.\n" + _bullets(f["reasons"]))
        return {"profile": "내 정보 변경은 PIN 확인이 필요해서 내 정보 화면에서 진행해 주세요.",
                "password": "비밀번호는 이메일 인증번호로 본인확인 후 재설정할 수 있어요.",
                "logout": "로그아웃은 아래 화면에서 할 수 있어요."}[f["focus"]]
    if k == "GO_SIGNUP":
        return "회원가입은 아래 화면에서 진행해 주세요."
    if k == "GO_LOGIN":
        return "로그인은 아래 화면에서 해 주세요."
    if k == "GO_SPENDING_REPORT":
        return "소비 리포트에서 항목별 비중과 추이를 한눈에 볼 수 있어요."
    if k == "GO_BUDGET_SETTING":
        return "예산은 설정 화면에서 월 전체와 항목별로 정할 수 있어요."
    if k == "GO_ACCOUNT_DETAIL":
        return f"'{f['account']}' 계좌 화면으로 이동할 수 있어요."
    return ""


_RENDERERS = {
    "LIST_ACCOUNTS": _accounts, "ACCOUNT_DETAIL": _account_detail, "ACCOUNT_LIMITS": _limits, "SEARCH_TRANSACTIONS": _transactions,
    "LIST_RECENT_RECIPIENTS": _recipients, "LIST_FAVORITE_RECIPIENTS": _recipients, "LIST_AUTO_TRANSFERS": _auto,
    "LIST_CARDS": _cards, "CARD_PAYMENTS": _card_payments, "LIST_NOTIFICATIONS": _notifications, "LOGIN_HISTORY": _login_history,
    "CLOSE_CHECK": _close_check, "PRODUCTS_INFO": _products, "KNOWLEDGE_QA": _knowledge, "SPENDING_SUMMARY": _spending_summary,
    "SPENDING_BY_CATEGORY": _spending_by_category, "SPENDING_TOP_MERCHANTS": _top_merchants, "SPENDING_COMPARE": _compare,
    "BUDGET_STATUS": _budget,
}


# ---------- 문장 정리 ----------

def plain_text(text: str) -> str:
    """모델이 쓴 마크다운 기호를 없앤다(앱 화면은 마크다운을 렌더링하지 않는다). 목록은 '- '로 통일한다."""
    text = re.sub(r"\*\*(.+?)\*\*", lambda m: m.group(1), text)
    text = re.sub(r"(?m)^[ \t]*[*•]\s+", "- ", text)
    text = re.sub(r"(?m)^#{1,6}\s+", "", text)
    return text.replace("`", "").strip()


# ---------- 숫자 검증 ----------

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _normalize(token: str) -> str:
    t = token.replace(",", "")
    return t[:-2] if t.endswith(".0") else t


def collect_numbers(obj) -> set[str]:
    """facts 안의 모든 숫자(문자열 속 숫자 포함)."""
    found: set[str] = set()
    if isinstance(obj, bool) or obj is None:
        return found
    if isinstance(obj, (int, float)):
        found.add(_normalize(str(obj)))
    elif isinstance(obj, str):
        for t in _NUM.findall(obj):
            found.add(_normalize(t))
            if "." in t:  # '22.12.31'처럼 점으로 이어 쓴 날짜는 22, 12, 31 각각을 근거로 인정한다
                found.update(p for p in t.replace(",", "").split(".") if p)
        for m in re.finditer(r"['‘’](\d{2})(?!\d)", obj):  # '22 같은 두 자리 연도 줄임 표기는 2022도 같은 뜻이다
            found.add("20" + m.group(1))
    elif isinstance(obj, dict):
        for v in obj.values():
            found |= collect_numbers(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            found |= collect_numbers(v)
    return found


def numbers_are_grounded(reply: str, facts, extra: str = "", strict: bool = False) -> bool:
    """답변의 모든 숫자가 도구 결과(또는 사용자가 직접 말한 값)에 있는지 확인한다.

    기본은 날짜·월 같은 작은 수(0~31)를 허용한다. strict=True면 예외 없이 모든 숫자가 근거에 있어야 한다
    (법령·약관 답변에서 '2주'를 '30일'로 바꾸는 식의 오류를 막기 위해 문서 기반 답변에 쓴다).
    """
    allowed = collect_numbers(facts) | {_normalize(t) for t in _NUM.findall(extra)}
    for tok in _NUM.findall(reply):
        n = _normalize(tok)
        if n in allowed:
            continue
        try:
            if not strict and "." not in n and 0 <= int(n) <= 31:
                continue
        except ValueError:
            pass
        return False
    return True
