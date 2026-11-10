"""사용자가 말한 값을 실제 대상으로 바꾼다(기간·계좌·카드·카테고리·받는 사람).

날짜 계산과 대상 찾기는 모델이 아니라 이 코드가 한다. 못 찾거나 여러 개라 모호하면 Clarify로 되묻는다.
"""
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from psycopg import Connection

from app.account import service as account_service
from app.agent.schemas import PeriodSpec
from app.spending import service as spending_service
from app.transfer import service as transfer_service

ORDINALS = {"첫": 1, "첫째": 1, "첫번째": 1, "1번": 1, "하나": 1, "둘": 2, "둘째": 2, "두번째": 2, "2번": 2,
            "셋": 3, "셋째": 3, "세번째": 3, "3번": 3}
CATEGORY_SYNONYMS = {
    "FOOD": ["식비", "식사", "밥", "음식", "식당", "배달", "외식", "점심", "저녁"],
    "CAFE": ["카페", "커피", "간식", "디저트", "빵"],
    "TRANSPORT": ["교통", "버스", "지하철", "택시", "주유", "차비", "기름"],
    "SHOPPING": ["쇼핑", "옷", "의류", "온라인"],
    "LIVING": ["생활", "마트", "편의점", "장보기", "식료품"],
    "MEDICAL": ["의료", "병원", "약국", "치과", "한의원"],
    "CULTURE": ["문화", "여가", "영화", "책", "공연", "서점", "취미"],
    "SUBSCRIPTION": ["구독", "통신", "통신비", "넷플릭스", "정기결제"],
    "EDUCATION": ["교육", "학원", "강의", "수업"],
    "TRANSFER": ["송금", "이체", "월세", "용돈"],
    "ETC": ["기타"],
}


@dataclass
class Clarify(Exception):
    """정보가 부족하거나 모호해서 사용자에게 되물어야 할 때."""
    question: str
    missing: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)


@dataclass
class Period:
    from_date: date
    to_date: date
    label: str
    months: list[str]      # 걸쳐 있는 달(YYYY-MM)


def _month_first(d: date) -> date:
    return d.replace(day=1)


def _months_between(a: date, b: date) -> list[str]:
    out, cur = [], _month_first(a)
    while cur <= b:
        out.append(cur.strftime("%Y-%m"))
        cur = spending_service.next_month(cur)
    return out


def resolve_period(spec: PeriodSpec | None, today: date, default: str = "THIS_MONTH") -> Period:
    """상대 표현·월·명시 날짜를 실제 날짜 범위로 바꾼다."""
    if spec is None or not any([spec.relative, spec.month, spec.from_date, spec.to_date]):
        spec = PeriodSpec(relative=default)
    if spec.from_date or spec.to_date:
        start, end = spec.from_date or spec.to_date, spec.to_date or spec.from_date
        if start > end:
            raise Clarify("기간의 시작일이 종료일보다 늦어요. 기간을 다시 알려 주세요.", ["period"])
        return Period(start, end, f"{start.month}월 {start.day}일~{end.month}월 {end.day}일", _months_between(start, end))
    if spec.month:
        first = spending_service.parse_month(spec.month)
        last = spending_service.next_month(first) - timedelta(days=1)
        return Period(first, min(last, max(today, first)), f"{first.year}년 {first.month}월", [spec.month])
    rel = spec.relative
    if rel == "TODAY":
        return Period(today, today, "오늘", [today.strftime("%Y-%m")])
    if rel == "YESTERDAY":
        d = today - timedelta(days=1)
        return Period(d, d, "어제", [d.strftime("%Y-%m")])
    if rel == "THIS_WEEK":
        start = today - timedelta(days=today.weekday())
        return Period(start, today, "이번 주", _months_between(start, today))
    if rel == "LAST_WEEK":
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
        return Period(start, end, "지난주", _months_between(start, end))
    if rel == "LAST_MONTH":
        first = spending_service.prev_month(_month_first(today))
        last = spending_service.next_month(first) - timedelta(days=1)
        return Period(first, last, f"{first.month}월(지난달)", [first.strftime("%Y-%m")])
    if rel == "LAST_3_MONTHS":
        start = account_service.months_ago(today, 3)
        return Period(start, today, "최근 3개월", _months_between(start, today))
    first = _month_first(today)  # THIS_MONTH
    return Period(first, today, f"{today.month}월(이번 달)", [first.strftime("%Y-%m")])


# ---------- 계좌·카드 ----------

def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _list_names(items: list[dict], key: str = "nickname") -> list[str]:
    return [i.get(key) or i.get("product_name") or "(이름 없음)" for i in items]


def resolve_account(conn: Connection, user_id, hint: str | None, *, purpose: str = "") -> dict:
    """힌트(별칭·상품명·끝 4자리·순서)로 본인 계좌를 하나 고른다. 하나로 정할 수 없으면 되묻는다."""
    rows = conn.execute(
        "SELECT a.*, p.product_name FROM accounts a JOIN account_products p ON p.id = a.product_id "
        "WHERE a.user_id = %s AND a.status <> 'CLOSED' ORDER BY a.is_favorite DESC, a.created_at, a.id", (user_id,)).fetchall()
    if not rows:
        raise Clarify("사용 중인 계좌가 없어요. 먼저 계좌를 개설해 주세요.", ["account"])
    h = _norm(hint)
    if h:
        digits = re.sub(r"\D", "", h)
        found = [a for a in rows if h in _norm(a["nickname"]) or (a["nickname"] and _norm(a["nickname"]) in h)
                 or h in _norm(a["product_name"]) or (len(digits) >= 3 and a["account_num"].replace("-", "").endswith(digits[-4:]))]
        if not found:
            for word, n in ORDINALS.items():
                if word in h and n <= len(rows):
                    found = [rows[n - 1]]
                    break
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise Clarify(f"'{hint}'에 해당하는 계좌가 여러 개예요. 어느 계좌인가요?", ["account"],
                          [f"{a['nickname'] or a['product_name']}({account_service.mask_account_num(a['account_num'])})" for a in found])
        raise Clarify(f"'{hint}'에 해당하는 계좌를 찾지 못했어요. 어느 계좌인가요?", ["account"], _list_names(rows))
    if len(rows) == 1:
        return rows[0]
    raise Clarify(f"어느 계좌{purpose}인가요?", ["account"], _list_names(rows))


def resolve_card(conn: Connection, user_id, hint: str | None) -> dict:
    rows = conn.execute(
        "SELECT c.*, a.nickname AS account_nickname FROM cards c JOIN accounts a ON a.id = c.account_id "
        "WHERE a.user_id = %s AND c.status IN ('ACTIVE','SUSPENDED','LOST') ORDER BY c.created_at DESC", (user_id,)).fetchall()
    if not rows:
        raise Clarify("사용 중인 체크카드가 없어요. 카드를 먼저 발급받아 주세요.", ["card"])
    from app.card import service as card_service
    h = _norm(hint)
    if h:
        digits = re.sub(r"\D", "", h)
        found = [c for c in rows if (len(digits) >= 4 and card_service._view(c)["last4"] == digits[-4:])
                 or (c["account_nickname"] and _norm(c["account_nickname"]) in h)]
        if len(found) == 1:
            return found[0]
    if len(rows) == 1:
        return rows[0]
    raise Clarify("어느 카드인가요? 끝 4자리와 함께 알려 주세요.", ["card"],
                  [f"끝 {card_service._view(c)['last4']}({c['account_nickname'] or '카드'})" for c in rows])


# ---------- 카테고리 ----------

def resolve_category(conn: Connection, text: str | None, *, required: bool = False) -> str | None:
    """한글 이름·코드·동의어를 카테고리 코드로 바꾼다."""
    cats = spending_service.category_table(conn)
    if not text:
        if required:
            raise Clarify("어떤 항목인가요?", ["category"], [c["name"] for c in cats.values()])
        return None
    t = _norm(text)
    for code, c in cats.items():
        if t == code.lower() or t == _norm(c["name"]):
            return code
    for code, words in CATEGORY_SYNONYMS.items():
        if any(w in t for w in words):
            return code
    for code, c in cats.items():
        if _norm(c["name"]) in t or any(part and part in t for part in _norm(c["name"]).split("·")):
            return code
    raise Clarify(f"'{text}'는 어떤 항목인지 알 수 없어요. 아래에서 골라 주세요.", ["category"], [c["name"] for c in cats.values()])


# ---------- 받는 사람 ----------

ACCOUNT_NUM = re.compile(r"\d{3}-\d{4}-\d{4}")


def resolve_recipient(conn: Connection, user_id, hint: str | None) -> dict | None:
    """즐겨찾는 받는 계좌의 별칭·이름, 또는 사용자가 직접 말한 계좌번호로 받는 사람을 찾는다.

    반환: {"recipient_id": 즐겨찾기 ID} 또는 {"to_account_num": 사용자가 말한 번호}. 못 찾으면 None.
    """
    if not hint:
        return None
    m = ACCOUNT_NUM.search(hint)
    if m:
        return {"to_account_num": m.group()}
    h = _norm(hint)
    favs = conn.execute("SELECT id, alias, holder_name FROM favorite_recipients WHERE user_id = %s ORDER BY id DESC", (user_id,)).fetchall()
    found = [f for f in favs if h and (h in _norm(f["alias"]) or _norm(f["alias"]) in h or h in _norm(f["holder_name"]) or _norm(f["holder_name"]) in h)
             and (f["alias"] or f["holder_name"])]
    if len(found) == 1:
        return {"recipient_id": found[0]["id"], "label": found[0]["alias"] or transfer_service.mask_name(found[0]["holder_name"])}
    if len(found) > 1:
        raise Clarify(f"'{hint}'에 해당하는 받는 분이 여러 명이에요. 누구인가요?", ["recipient"],
                      [f["alias"] or transfer_service.mask_name(f["holder_name"]) for f in found])
    return None


def favorite_names(conn: Connection, user_id) -> list[str]:
    return [f["alias"] or transfer_service.mask_name(f["holder_name"]) for f in
            conn.execute("SELECT alias, holder_name FROM favorite_recipients WHERE user_id = %s ORDER BY id DESC LIMIT 5", (user_id,)).fetchall()]
