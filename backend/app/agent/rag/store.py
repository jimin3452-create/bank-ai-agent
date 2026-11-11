"""지식베이스 저장·검색 (PostgreSQL + pgvector). 벡터는 문자열 리터럴로 넘겨 별도 어댑터 없이 쓴다."""
import hashlib

from psycopg import Connection

from app.agent.rag.chunking import Doc
from app.agent.rag.embeddings import Embedder


def vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def doc_hash(doc: Doc) -> str:
    h = hashlib.sha256()
    for part in (doc.source_type, doc.title, doc.version or "", doc.source_url or ""):
        h.update(part.encode("utf-8"))
    for c in doc.chunks:
        h.update(c.heading.encode("utf-8"))
        h.update(c.text.encode("utf-8"))
    return h.hexdigest()


def upsert_document(conn: Connection, doc: Doc, embedder: Embedder, *, force: bool = False) -> str:
    """문서를 저장한다. 내용이 그대로면 임베딩 호출 없이 건너뛴다. 반환: 'skipped' | 'created' | 'updated'.

    임베딩을 먼저 만든 뒤에 DB를 바꾼다(API가 실패해도 기존 데이터가 깨지지 않는다).
    """
    if not doc.chunks:
        return "skipped"
    digest = doc_hash(doc)
    old = conn.execute("SELECT id, content_hash FROM knowledge_documents WHERE source_ref = %s", (doc.source_ref,)).fetchone()
    if old and old["content_hash"] == digest and not force:
        return "skipped"
    vectors = embedder.embed_documents([c.text for c in doc.chunks])
    if old:
        doc_id = old["id"]
        conn.execute("DELETE FROM knowledge_chunks WHERE document_id = %s", (doc_id,))
        conn.execute("UPDATE knowledge_documents SET source_type=%s, title=%s, version=%s, source_url=%s, content_hash=%s, updated_at=now() WHERE id=%s",
                     (doc.source_type, doc.title, doc.version, doc.source_url, digest, doc_id))
    else:
        doc_id = conn.execute(
            "INSERT INTO knowledge_documents (source_type, title, source_ref, version, source_url, content_hash) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (doc.source_type, doc.title, doc.source_ref, doc.version, doc.source_url, digest)).fetchone()["id"]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO knowledge_chunks (document_id, chunk_index, content, heading, embedding) VALUES (%s,%s,%s,%s,%s::vector)",
            [(doc_id, i, c.text, c.heading[:300], vec_literal(v)) for i, (c, v) in enumerate(zip(doc.chunks, vectors))])
    return "updated" if old else "created"


def delete_missing(conn: Connection, source_types: list[str], keep_refs: set[str]) -> int:
    """원본이 사라진 문서를 지운다(해당 출처 구분 안에서만)."""
    rows = conn.execute("SELECT id, source_ref FROM knowledge_documents WHERE source_type = ANY(%s)", (source_types,)).fetchall()
    gone = [r["id"] for r in rows if r["source_ref"] not in keep_refs]
    if gone:
        conn.execute("DELETE FROM knowledge_documents WHERE id = ANY(%s)", (gone,))  # 청크는 ON DELETE CASCADE
    return len(gone)


def search_chunks(conn: Connection, query_vec: list[float], source_types: list[str] | None, limit: int) -> list[dict]:
    """코사인 유사도 순으로 청크를 찾는다. score는 1에 가까울수록 비슷하다."""
    lit = vec_literal(query_vec)
    # HNSW 인덱스의 기본 탐색 폭(40)에서는 정답 청크를 놓치는 질문이 있었다(상위 10개 중 약 5%가 정확 검색과 달랐다).
    # 200으로 넓히면 이 규모에서는 정확 검색과 같은 결과가 나온다.
    conn.execute("SELECT set_config('hnsw.ef_search', '200', true)")
    return conn.execute(
        "SELECT c.id, c.heading, c.content, d.title, d.source_type, d.version, d.source_url, "
        "1 - (c.embedding <=> %s::vector) AS score FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id "
        "WHERE (%s::text[] IS NULL OR d.source_type = ANY(%s)) ORDER BY c.embedding <=> %s::vector LIMIT %s",
        (lit, source_types, source_types, lit, limit)).fetchall()


def stats(conn: Connection) -> list[dict]:
    return conn.execute(
        "SELECT d.source_type, count(DISTINCT d.id) AS documents, count(c.id) AS chunks FROM knowledge_documents d "
        "LEFT JOIN knowledge_chunks c ON c.document_id = d.id GROUP BY d.source_type ORDER BY d.source_type").fetchall()
