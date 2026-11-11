"""지식 문서를 검색 단위(청크)로 나눈다. 모든 함수는 순수 함수라 DB·API 없이 테스트할 수 있다.

- 법령·약관: 조(條) 단위. 긴 조는 항(①②…) 단위로 다시 나눈다. 청크 앞에 `[법령명 제N조(제목)]`을 붙여 검색과 출처 표시에 쓴다.
- FAQ: 질문 하나 = 청크 하나. 가이드: `##` 섹션 하나 = 청크 하나(길면 문단 단위로 분할).
- 시중 상품(금감원 공시): 상품 하나 = 청크 하나. 숫자는 원본 값을 그대로 옮긴다.
"""
import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_CHARS = 900   # 청크 최대 길이(한글 기준). 임베딩 입력 한도와 검색 정밀도를 함께 고려한 값

LAW_TAG = re.compile(r"<(?:개정|신설|삭제|전문개정|본조신설|제목개정|단서신설|종전|시행일|본조삭제|후단신설|전단신설)[^>]*>")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


@dataclass
class Chunk:
    heading: str          # 출처 표시용 소제목(조문 번호·질문·상품명 등)
    text: str             # 검색·임베딩·답변 근거로 쓰는 본문


@dataclass
class Doc:
    source_type: str      # LAW / STANDARD_TERMS / MARKET_PRODUCT / KDIC_FAQ / FAQ / GUIDE / TERMS / PRODUCT
    title: str
    source_ref: str       # 파일 경로 또는 db:테이블:ID (문서를 식별하는 고유 값)
    version: str | None = None
    source_url: str | None = None
    chunks: list[Chunk] = field(default_factory=list)


# ---------- 공통 ----------

def _squash(text: str) -> str:
    return re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", text)).strip()


def _split_long(text: str, limit: int = MAX_CHARS) -> list[str]:
    """limit 안에 들어가도록 문단(빈 줄) → 줄 → 문장 순으로 나눈다."""
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    buf = ""
    units = re.split(r"\n\s*\n|\n", text)
    expanded: list[str] = []
    for u in units:
        if len(u) <= limit:
            expanded.append(u)
        else:  # 한 줄이 너무 길면 문장 끝에서 자른다
            sent = re.split(r"(?<=[.다요])\s+", u)
            cur = ""
            for s in sent:
                if len(cur) + len(s) + 1 > limit and cur:
                    expanded.append(cur)
                    cur = s
                else:
                    cur = f"{cur} {s}".strip()
            if cur:
                expanded.append(cur)
    for u in expanded:
        if buf and len(buf) + len(u) + 1 > limit:
            pieces.append(buf)
            buf = u
        else:
            buf = f"{buf}\n{u}".strip()
    if buf:
        pieces.append(buf)
    return pieces


def _split_by_paragraph_marks(body: str, limit: int) -> list[str]:
    """조문 본문을 항(①②…) 경계에서 limit 이내로 묶는다."""
    parts = re.split(rf"(?=[{CIRCLED}])", body)
    parts = [p for p in parts if p.strip()]
    out, buf = [], ""
    for p in parts:
        if buf and len(buf) + len(p) > limit:
            out.append(buf.strip())
            buf = p
        else:
            buf += p
    if buf.strip():
        out.append(buf.strip())
    final: list[str] = []
    for piece in out:
        final.extend(_split_long(piece, limit))
    return final


def _front_matter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "-")):
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip("'\"")
    return meta, text[m.end():]


def _article_chunks(label: str, num: str, title: str, body: str) -> list[Chunk]:
    heading = f"{num}({title})" if title else num
    prefix = f"[{label} {heading}]\n"
    body = _squash(body)
    if not body:
        return []
    pieces = _split_by_paragraph_marks(body, MAX_CHARS - len(prefix))
    chunks = []
    for i, piece in enumerate(pieces, 1):
        h = heading if len(pieces) == 1 else f"{heading} ({i}/{len(pieces)})"
        chunks.append(Chunk(h, prefix + piece))
    return chunks


# ---------- 법령(국가법령정보센터 마크다운) ----------

def clean_law_text(text: str) -> str:
    text = LAW_TAG.sub("", text)
    text = text.replace("**", "").replace("\\.", ".").replace("\\-", "-").replace("\\(", "(").replace("\\)", ")")
    return _squash(text)


def chunk_law(path: str, text: str) -> Doc:
    meta, body = _front_matter(text)
    title = meta.get("제목") or Path(path).stem
    kind = meta.get("법령구분", "")
    if kind and kind not in title and kind in ("시행령", "시행규칙"):
        title = f"{title} {kind}"
    doc = Doc("LAW", title, path, version=(meta.get("시행일자") or None), source_url=meta.get("출처"))
    head = re.compile(r"^#{3,6}\s*(제\d+조(?:의\d+)?)\s*(?:\(([^)]*)\))?\s*(.*)$")
    current: tuple[str, str] | None = None
    buf: list[str] = []

    def flush():
        if current and buf:
            doc.chunks.extend(_article_chunks(title, current[0], current[1], clean_law_text("\n".join(buf))))

    for line in body.splitlines():
        m = head.match(line)
        if m:
            flush()
            buf = []
            num, ttl, rest = m.group(1), (m.group(2) or "").strip(), clean_law_text(m.group(3) or "")
            current = None if (not ttl and rest.startswith("삭제")) else (num, ttl)  # 삭제된 조는 버린다
            if rest and current and not rest.startswith("삭제"):
                buf.append(rest)
        elif current is not None and not line.startswith("#"):
            buf.append(line)
    flush()
    return doc


# ---------- 표준약관 ----------

TERMS_ARTICLE = re.compile(r"(?m)^제(\d+)조(?:의(\d+))?\s*\(([^)]*)\)")


def chunk_terms(path: str, text: str, source_type: str = "STANDARD_TERMS") -> Doc:
    lines = [l for l in text.splitlines() if l.strip()]
    title = lines[0].strip() if lines else Path(path).stem
    version = None
    m = re.search(r"\((\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*개정\)", text[:600])
    if m:
        version = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    doc = Doc(source_type, title, path, version=version)
    matches = list(TERMS_ARTICLE.finditer(text))
    for i, m in enumerate(matches):
        start, end = m.end(), (matches[i + 1].start() if i + 1 < len(matches) else len(text))
        num = f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
        doc.chunks.extend(_article_chunks(title, num, m.group(3).strip(), text[start:end]))
    return doc


# ---------- FAQ ----------

def _drop_undecided(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if "[정책 미정" not in l)


def chunk_faq_md(path: str, text: str, title: str, source_type: str = "FAQ", version: str | None = None) -> Doc:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    doc = Doc(source_type, title, path, version=version)
    category = ""
    for block in re.split(r"(?m)^(?=#{2,3} )", text):
        if block.startswith("## ") and not block.startswith("### "):
            category = block.splitlines()[0][3:].strip()
            continue
        if not block.startswith("### "):
            continue
        q, _, a = block[4:].partition("\n")
        a = _squash(_drop_undecided(a))
        if q.strip() and a:
            cat = f"[{category}] " if category else ""
            doc.chunks.append(Chunk(q.strip(), f"{cat}질문: {q.strip()}\n답변: {a}"))
    return doc


def chunk_faq_csv(path: str, raw: bytes, title: str, source_type: str, version: str | None = None) -> Doc:
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.reader(io.StringIO(text)))
    doc = Doc(source_type, title, path, version=version)
    for r in rows[1:]:
        if len(r) < 4 or not r[2].strip() or not r[3].strip():
            continue
        q, a = re.sub(r"\s+", " ", r[2]).strip(), re.sub(r"[ \t]+", " ", r[3]).strip()
        for i, piece in enumerate(_split_long(a)):
            h = q if i == 0 else f"{q} ({i + 1})"
            doc.chunks.append(Chunk(h, f"질문: {q}\n답변: {piece}"))
    return doc


# ---------- 가이드 ----------

def chunk_guide_md(path: str, text: str, version: str | None = None) -> Doc:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    m = re.search(r"(?m)^# (.+)$", text)
    title = m.group(1).strip() if m else Path(path).stem
    doc = Doc("GUIDE", title, path, version=version)
    for block in re.split(r"(?m)^(?=## )", text):
        if not block.startswith("## "):
            continue
        sec, _, body = block[3:].partition("\n")
        body = _squash(body)
        if not body:
            continue
        pieces = _split_long(body, MAX_CHARS - len(title) - len(sec) - 6)
        for i, piece in enumerate(pieces, 1):
            h = sec.strip() if len(pieces) == 1 else f"{sec.strip()} ({i}/{len(pieces)})"
            doc.chunks.append(Chunk(h, f"[{title} - {sec.strip()}]\n{piece}"))
    return doc


# ---------- 시중 상품(금감원 공시 JSON) ----------

PRODUCT_KINDS = {
    "depositProductsSearch": "정기예금", "savingProductsSearch": "적금", "creditLoanProductsSearch": "개인신용대출",
    "mortgageLoanProductsSearch": "주택담보대출", "rentHouseLoanProductsSearch": "전세자금대출",
}
# 신용점수 구간 코드(금융감독원 API 명세 기준)
CREDIT_GRADES = {"crdt_grad_1": "900점 초과", "crdt_grad_4": "801~900점", "crdt_grad_5": "701~800점", "crdt_grad_6": "601~700점",
                 "crdt_grad_10": "501~600점", "crdt_grad_11": "401~500점", "crdt_grad_12": "301~400점", "crdt_grad_13": "300점 이하"}


def _clip(s, n: int = 320) -> str:
    s = re.sub(r"\s*\n\s*", " / ", str(s).strip())
    return s if len(s) <= n else s[:n].rstrip() + "…"


def _pct(v) -> str:
    return f"{v:g}%"


def _month(m: str) -> str:
    return f"{m[:4]}년 {int(m[4:6])}월" if m and len(m) >= 6 else (m or "")


def chunk_products_json(path: str, raw: str) -> Doc:
    key = Path(path).stem
    kind = PRODUCT_KINDS.get(key, key)
    data = json.loads(raw)
    options: dict[str, list[dict]] = {}
    for o in data.get("optionList", []):
        options.setdefault(o["fin_prdt_cd"], []).append(o)
    base = data.get("baseList", [])
    month = base[0].get("dcls_month") if base else None
    doc = Doc("MARKET_PRODUCT", f"시중 {kind} 상품 공시", path, version=_month(month) if month else None,
              source_url="금융감독원 금융상품 비교공시")
    for p in base:
        name = f"{p['kor_co_nm']} {p['fin_prdt_nm']}"
        lines = [f"[{name}] {kind} 상품 (공시 {_month(p.get('dcls_month', ''))}, 시중 은행 상품 정보)"]
        if p.get("join_way"):
            lines.append(f"가입 방법: {p['join_way']}")
        if key in ("depositProductsSearch", "savingProductsSearch"):
            if p.get("join_member"):
                lines.append(f"가입 대상: {_clip(p['join_member'])}")
            if p.get("spcl_cnd"):
                lines.append(f"우대 조건: {_clip(p['spcl_cnd'])}")
            if p.get("max_limit"):
                lines.append(f"가입 한도: {p['max_limit']:,}원")
            if p.get("etc_note"):
                lines.append(f"기타 안내: {_clip(p['etc_note'])}")
            if p.get("mtrt_int"):
                lines.append(f"만기 후 이자: {_clip(p['mtrt_int'], 200)}")
            rates = []
            for o in sorted(options.get(p["fin_prdt_cd"], []), key=lambda o: (o.get("rsrv_type_nm") or "", int(o.get("save_trm") or 0))):
                kindname = " ".join(x for x in (o.get("rsrv_type_nm"), o.get("intr_rate_type_nm")) if x)
                base_rate = _pct(o["intr_rate"]) if o.get("intr_rate") is not None else "없음"
                top = f", 최고 우대금리 {_pct(o['intr_rate2'])}" if o.get("intr_rate2") is not None else ""
                rates.append(f"{kindname} {o['save_trm']}개월 기본금리 {base_rate}{top}")
            if rates:
                lines.append("금리: " + "; ".join(rates))
        elif key == "creditLoanProductsSearch":
            lines.append(f"대출 종류: {p.get('crdt_prdt_type_nm', '')} (신용평가사 {p.get('cb_name', '')})")
            for o in options.get(p["fin_prdt_cd"], []):
                grades = [f"{label} {_pct(o[col])}" for col, label in CREDIT_GRADES.items() if o.get(col) is not None]
                avg = f", 평균 {_pct(o['crdt_grad_avg'])}" if o.get("crdt_grad_avg") is not None else ""
                if grades:
                    lines.append(f"{o.get('crdt_lend_rate_type_nm', '대출금리')} (신용점수 구간별): " + ", ".join(grades) + avg)
        else:  # 주택담보·전세자금 대출
            for field_name, label in (("loan_lmt", "대출 한도"), ("loan_inci_expn", "대출 부대비용"), ("erly_rpay_fee", "중도상환수수료"),
                                      ("dly_rate", "연체이자율")):
                if p.get(field_name):
                    lines.append(f"{label}: {_clip(p[field_name], 240)}")
            for o in options.get(p["fin_prdt_cd"], []):
                parts = " ".join(x for x in (o.get("mrtg_type_nm"), o.get("rpay_type_nm"), o.get("lend_rate_type_nm")) if x)
                lo, hi, avg = o.get("lend_rate_min"), o.get("lend_rate_max"), o.get("lend_rate_avg")
                if lo is not None and hi is not None:
                    lines.append(f"금리 ({parts}): {_pct(lo)}~{_pct(hi)}" + (f", 평균 {_pct(avg)}" if avg is not None else ""))
        text = "\n".join(lines)
        for i, piece in enumerate(_split_long(text, 1400), 1):
            # 나뉜 뒤 조각만 검색되어도 어느 상품인지 알 수 있게 상품명을 붙인다
            head = name if i == 1 else f"{name} ({i})"
            doc.chunks.append(Chunk(head, piece if i == 1 else f"[{name}] (이어서)\n{piece}"))
    return doc
