"""RAG 지식 검색: 질문을 임베딩해 지식베이스에서 근거 문서를 찾는다.

유사도가 기준(`rag_min_score`)에 못 미치면 '근거 없음'으로 돌려준다 — 관련 없는 문서로 억지로 답하지 않기 위해서다.
검색 결과는 모델에게 '참고 데이터'로만 전달되며, 문서 안의 지시문은 따르지 않는다(agent/llm.py의 프롬프트).
"""
from psycopg import Connection

from app.agent.rag import store
from app.agent.rag.embeddings import get_embedder
from app.config import settings

MAX_PASSAGE_CHARS = 1000


def search(conn: Connection, query: str, source_types: list[str] | None = None, k: int | None = None,
           min_score: float | None = None) -> dict:
    """{"found": bool, "passages": [{title, heading, type, version, source_url, text, score}], "reason": str|None}"""
    k = k or settings.rag_top_k
    min_score = settings.rag_min_score if min_score is None else min_score
    embedder = get_embedder()
    if embedder is None:
        return {"found": False, "passages": [], "reason": "embedder-unavailable"}
    try:
        qvec = embedder.embed_query(query)
    except Exception:
        return {"found": False, "passages": [], "reason": "embedding-failed"}
    rows = store.search_chunks(conn, qvec, source_types, k * 3)
    passages, seen = [], set()
    for r in rows:
        if r["score"] < min_score:
            continue
        key = (r["title"], r["heading"])
        if key in seen:
            continue
        seen.add(key)
        passages.append({"title": r["title"], "heading": r["heading"], "type": r["source_type"], "version": r["version"],
                         "source_url": r["source_url"], "text": r["content"][:MAX_PASSAGE_CHARS], "score": round(float(r["score"]), 3)})
        if len(passages) >= k:
            break
    return {"found": bool(passages), "passages": passages, "reason": None if passages else "no-match"}


def label(p: dict) -> str:
    """출처 표시용 이름. 법령·약관은 조문까지, 시중 상품은 상품명과 공시 구분까지 보여 준다."""
    import re
    heading = re.sub(r"\s*\(\d+/\d+\)$", "", p.get("heading") or "")  # 긴 조문을 나눈 (1/3) 표시는 뺀다
    t, title, ver = p.get("type"), p.get("title") or "", p.get("version")
    if t in ("LAW", "STANDARD_TERMS"):
        return f"{title} {heading}".strip() + (f" ({ver} 시행)" if t == "LAW" and ver else "")
    if t == "MARKET_PRODUCT":
        return f"{heading} (시중 은행 공시{f', {ver}' if ver else ''})"
    if t == "FAQ":
        return "가상은행 FAQ"
    if t == "GUIDE":
        return f"소비 관리 가이드({title})"
    return title or heading
