"""RAG 지식 검색. 4단계에서 pgvector 검색과 Gemini 임베딩으로 채운다.

지금은 지식베이스가 준비되지 않았다고 정직하게 알려 주는 자리 표시자다(없는 내용을 지어내지 않기 위해).
"""
from psycopg import Connection


def search(conn: Connection, query: str, source_types: list[str] | None = None, k: int = 4) -> dict:
    """{"found": bool, "passages": [{"title","type","text","version"}], "reason": str|None}"""
    return {"found": False, "passages": [], "reason": "knowledge-base-not-ready"}
