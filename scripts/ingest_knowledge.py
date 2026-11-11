"""지식베이스 적재: knowledge/ 문서와 DB(이 앱의 약관·상품)를 청크로 나눠 Gemini로 임베딩하고 pgvector에 저장한다.

- 내용이 그대로인 문서는 건너뛴다(임베딩 호출·비용 없음). 문서를 고치면 그 문서만 다시 만든다.
- GEMINI_API_KEY가 필요하다(.env). --dry-run은 키 없이 청크 개수만 센다.

사용:
  backend/.venv/Scripts/python scripts/ingest_knowledge.py                # 전체
  backend/.venv/Scripts/python scripts/ingest_knowledge.py --dry-run      # 청크 수만 확인
  backend/.venv/Scripts/python scripts/ingest_knowledge.py --only faq guide db
  backend/.venv/Scripts/python scripts/ingest_knowledge.py --force        # 내용이 같아도 다시 임베딩
  backend/.venv/Scripts/python scripts/ingest_knowledge.py --stats        # 현재 적재 현황
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.agent.rag import chunking, store  # noqa: E402
from app.agent.rag.chunking import Chunk, Doc  # noqa: E402
from app.agent.rag.embeddings import get_embedder  # noqa: E402
from app.config import settings  # noqa: E402

K = ROOT / "knowledge"
GROUPS = ["faq", "guide", "db", "terms", "laws", "products"]


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def file_docs(group: str) -> list[Doc]:
    docs: list[Doc] = []
    if group == "laws":
        for f in sorted((K / "laws").glob("*.md")):
            docs.append(chunking.chunk_law(rel(f), f.read_text(encoding="utf-8")))
    elif group == "terms":
        for f in sorted((K / "terms").glob("*.md")):
            docs.append(chunking.chunk_terms(rel(f), f.read_text(encoding="utf-8")))
    elif group == "products":
        for f in sorted((K / "products").glob("*.json")):
            docs.append(chunking.chunk_products_json(rel(f), f.read_text(encoding="utf-8")))
    elif group == "faq":
        for f in sorted((K / "faq").glob("*.md")):
            docs.append(chunking.chunk_faq_md(rel(f), f.read_text(encoding="utf-8"), "가상은행 자주 묻는 질문", "FAQ"))
        for f in sorted((K / "faq").glob("*.csv")):
            docs.append(chunking.chunk_faq_csv(rel(f), f.read_bytes(), "예금보험공사 착오송금 반환지원 FAQ", "KDIC_FAQ"))
    elif group == "guide":
        for f in sorted((K / "guide").glob("*.md")):
            docs.append(chunking.chunk_guide_md(rel(f), f.read_text(encoding="utf-8")))
    return docs


def db_docs(conn) -> list[Doc]:
    """이 앱의 약관(terms)과 계좌 상품(account_products)."""
    docs: list[Doc] = []
    for t in conn.execute("SELECT id, title, content, version, category FROM terms ORDER BY id").fetchall():
        d = chunking.chunk_terms(f"db:terms:{t['id']}", f"{t['title']}\n{t['content']}", source_type="TERMS")
        d.title, d.version = t["title"], t["version"]
        if not d.chunks:  # 조문 형식이 아닌 짧은 약관은 통째로 한 청크
            d.chunks = [Chunk(t["title"], f"[{t['title']}]\n{t['content'].strip()}")]
        docs.append(d)
    products = conn.execute("SELECT * FROM account_products WHERE is_active ORDER BY id").fetchall()
    if products:
        d = Doc("PRODUCT", "가상은행 입출금통장 상품 안내", "db:account_products")
        for p in products:
            lines = [f"[{p['product_name']}] 가상은행 입출금통장 상품 (금리는 안내용이며 이자 지급은 하지 않아요)",
                     f"연 금리: {float(p['interest_rate']):g}%", f"가입 조건: {p['join_condition']}"]
            if p["rate_condition"]:
                lines.append(f"우대 조건: {p['rate_condition']}")
            if p["description"]:
                lines.append(f"상품 설명: {p['description']}")
            d.chunks.append(Chunk(p["product_name"], "\n".join(lines)))
        docs.append(d)
    return docs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", choices=GROUPS, help="적재할 묶음")
    ap.add_argument("--dry-run", action="store_true", help="청크 수만 세고 저장하지 않는다")
    ap.add_argument("--force", action="store_true", help="내용이 같아도 다시 임베딩한다")
    ap.add_argument("--stats", action="store_true", help="현재 적재 현황만 보여 준다")
    args = ap.parse_args()

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        if args.stats:
            for r in store.stats(conn):
                print(f"{r['source_type']:16} 문서 {r['documents']:3}  청크 {r['chunks']:5}")
            return 0
        groups = args.only or GROUPS
        docs: list[Doc] = []
        for g in groups:
            docs += db_docs(conn) if g == "db" else file_docs(g)
        total = sum(len(d.chunks) for d in docs)
        print(f"대상 문서 {len(docs)}개, 청크 {total}개")
        if args.dry_run:
            by: dict[str, int] = {}
            for d in docs:
                by[d.source_type] = by.get(d.source_type, 0) + len(d.chunks)
            for k, v in sorted(by.items()):
                print(f"  {k:16} {v:5}")
            return 0
        embedder = get_embedder()
        if embedder is None:
            print("GEMINI_API_KEY가 .env에 없습니다. 키를 넣은 뒤 다시 실행해 주세요. (--dry-run은 키 없이 가능)")
            return 2
        counts = {"created": 0, "updated": 0, "skipped": 0}
        started = time.time()
        for i, d in enumerate(docs, 1):
            result = store.upsert_document(conn, d, embedder, force=args.force)
            conn.commit()
            counts[result] += 1
            print(f"[{i:3}/{len(docs)}] {result:8} {d.source_type:15} {d.title[:34]:36} 청크 {len(d.chunks):4}  ({time.time() - started:5.0f}s)", flush=True)
        if args.only is None:  # 전체 적재일 때만 원본이 사라진 문서를 정리한다
            gone = store.delete_missing(conn, sorted({d.source_type for d in docs}), {d.source_ref for d in docs})
            conn.commit()
            if gone:
                print(f"원본이 없어진 문서 {gone}개 삭제")
        if counts["created"] or counts["updated"]:
            conn.execute("ANALYZE knowledge_chunks")  # 적재 직후 통계를 갱신해 검색 계획이 정확해지게 한다
            conn.commit()
        print(f"\n완료: 새로 {counts['created']} / 갱신 {counts['updated']} / 건너뜀 {counts['skipped']}  ·  임베딩 API 호출 {getattr(embedder, 'calls', '-')}회")
        for r in store.stats(conn):
            print(f"  {r['source_type']:16} 문서 {r['documents']:3}  청크 {r['chunks']:5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
