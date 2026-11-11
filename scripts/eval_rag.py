"""RAG 검색 품질 평가: 질문마다 정답 문서가 상위 몇 번째로 나오는지(적중률)와, 관련 없는 질문이 걸러지는 유사도 기준을 측정한다.

실제 Gemini 임베딩과 적재된 지식베이스(scripts/ingest_knowledge.py)가 필요하다. 모델 답변이 아니라 '검색'만 평가한다.

사용:
  backend/.venv/Scripts/python scripts/eval_rag.py            # 전체 평가
  backend/.venv/Scripts/python scripts/eval_rag.py -v         # 놓친 질문의 상위 결과까지 출력
  backend/.venv/Scripts/python scripts/eval_rag.py --k 4

정답 판정: 상위 k개 결과의 `제목 + 소제목`에 기대 문자열 중 하나라도 들어 있으면 적중이다.
"""
import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.agent.rag import store  # noqa: E402
from app.agent.rag.embeddings import get_embedder  # noqa: E402
from app.config import settings  # noqa: E402

# (질문, [기대 문자열(제목+소제목에 포함)])
CASES = [
    # --- 이 앱 FAQ ---
    ("거래중지는 어떻게 풀어?", ["거래중지는 어떻게 풀어요"]),
    ("로그인 5번 틀려서 계정이 잠겼어", ["계정이 잠겼어요"]),
    ("비밀번호 까먹었어요", ["비밀번호를 잊어버렸어요"]),
    ("이체한도 바꾸고 싶어요", ["이체한도는 얼마이고 바꿀 수 있나요"]),
    ("자동이체가 실패하면 어떻게 돼?", ["자동이체는 언제 실행되고 실패하면"]),
    ("카드를 잃어버렸을 때 어떻게 해?", ["카드를 잃어버렸어요"]),
    ("체크카드 해외결제 켜고 싶어", ["카드 한도나 해외결제를 바꾸고 싶어요"]),
    ("예산 알림은 언제 와?", ["예산은 어떻게 설정하고 알림은 언제 오나요"]),
    ("내 다른 계좌로 보낸 것도 소비에 들어가?", ["내 다른 계좌로 보낸 돈도 소비인가요"]),
    ("AI가 대신 이체해 줄 수 있어?", ["챗으로 이체해 줄 수 있나요"]),
    ("대화 기록은 얼마나 보관돼?", ["대화 기록은 얼마나 보관"]),
    ("청년 통장은 누가 가입할 수 있어?", ["청년 우대 입출금통장"]),
    ("이 앱에 넣은 돈도 예금자보호가 돼?", ["예금자보호가 되나요"]),
    ("이메일 인증번호가 만료됐어요", ["이메일 인증번호는 얼마 동안"]),
    ("자동 로그아웃은 왜 되는 거야?", ["왜 자동으로 로그아웃되나요"]),
    # --- 예금보험공사 FAQ ---
    ("착오송금 반환지원은 언제까지 신청해야 해?", ["착오송금 발생 이후 언제까지 신청"]),
    ("착오송금 반환지원 대상 금액이 얼마야?", ["대상 금액은 얼마까지"]),
    # --- 법령 ---
    ("접근매체를 남에게 빌려주면 안 되는 이유", ["전자금융거래법 제6조"]),
    ("카드 분실 신고하면 그 뒤 손해는 누가 책임져?", ["제10조(접근매체의 분실과 도난 책임)"]),
    ("거래에 오류가 있으면 정정을 요구할 수 있어?", ["제8조(오류의 정정 등)", "오류가 있다고 생각되면"]),
    ("금융거래 비밀은 어떻게 보호돼?", ["제4조(금융거래의 비밀보장)", "비밀보장"]),
    ("금융거래는 왜 실명으로 해야 해?", ["제3조(금융실명거래)", "실명으로 가입해야"]),
    ("보이스피싱 당했을 때 지급정지 신청", ["전기통신금융사기"]),
    ("예금자보호 한도는 얼마야?", ["제32조(보험금의 계산 등)", "예금자보호가 되나요"]),
    ("금융상품 청약철회가 가능한 경우", ["제46조(청약의 철회)", "청약철회"]),
    ("금융소비자의 위법계약해지권", ["위법계약"]),
    ("금융회사의 설명의무", ["설명의무"]),
    ("적합성 원칙이 뭐야", ["적합성"]),
    ("금융상품 광고할 때 지켜야 할 규제", ["광고"]),
    # --- 표준약관 ---
    ("통장이나 카드를 재발급할 때 절차", ["제14조(통장, 카드의 재발급 등)"]),
    ("예금거래에서 비밀번호는 어떻게 신고해?", ["제5조(인감, 비밀번호 등의 신고)"]),
    ("대출에서 기한의 이익을 잃는 경우", ["기한전의 채무변제의무"]),
    # --- 시중 상품(공시) ---
    ("우리은행 WON플러스예금 금리 알려줘", ["우리은행 WON플러스예금"]),
    ("우리SUPER주거래적금 우대 조건이 뭐야", ["우리SUPER주거래적금"]),
    ("전세자금대출 중도상환수수료", ["전세자금대출"]),
    ("신용대출 신용점수별 금리", ["신용대출"]),
    # --- 소비 가이드 ---
    ("예산을 어떻게 세우면 좋을까?", ["예산 세우기"]),
    ("고정지출과 변동지출 차이가 뭐야", ["소비 관리 기초"]),
    ("소비를 줄이는 방법 알려줘", ["소비 줄이기 일반 팁"]),
]
# 관련 없는 질문: 유사도 기준을 넘지 않아야 한다
NEGATIVES = ["오늘 서울 날씨 어때?", "비트코인 시세가 얼마야", "주말에 갈 만한 맛집 추천해줘", "파이썬에서 리스트 정렬하는 법",
             "어제 축구 경기 결과 알려줘", "지하철 2호선 노선도"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=settings.rag_top_k)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    emb = get_embedder()
    if emb is None:
        print("GEMINI_API_KEY가 .env에 없습니다.")
        return 2
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        total_chunks = sum(r["chunks"] for r in store.stats(conn))
        print(f"임베딩 모델: {settings.gemini_embedding_model} ({settings.embedding_dim}차원) · 청크 {total_chunks}개 · k={args.k} · 현재 기준 {settings.rag_min_score}\n")
        ranks, top1, misses = [], [], []
        for n, (q, expect) in enumerate(CASES, 1):
            rows = store.search_chunks(conn, emb.embed_query(q), None, 10)
            rank = next((i for i, r in enumerate(rows, 1) if any(e in f"{r['title']} {r['heading']}" for e in expect)), None)
            ranks.append(rank)
            top1.append(rows[0]["score"])
            hit = rank is not None and rank <= args.k
            print(f"[{n:2}] {'OK  ' if hit else 'MISS'} 순위 {rank or '-':>2} 점수 {rows[0]['score']:.3f}  {q}")
            if not hit:
                misses.append((q, rows[:3]))
        n_total = len(CASES)
        hit1 = sum(1 for r in ranks if r == 1)
        hitk = sum(1 for r in ranks if r is not None and r <= args.k)
        mrr = statistics.mean((1 / r) if r else 0 for r in ranks)
        # 정답 순위가 잡힌 질문들의 '정답 청크' 유사도(= 기준을 정할 때 살려야 하는 점수)
        correct_scores = []
        for (q, expect), rank in zip(CASES, ranks):
            if rank:
                rows = store.search_chunks(conn, emb.embed_query(q), None, 10)
                correct_scores.append(rows[rank - 1]["score"])
        print(f"\n적중 @1: {hit1}/{n_total} ({hit1 * 100 // n_total}%)  @{args.k}: {hitk}/{n_total} ({hitk * 100 // n_total}%)  MRR: {mrr:.3f}")
        print("\n--- 관련 없는 질문의 최고 유사도(낮을수록 좋음) ---")
        neg = []
        for q in NEGATIVES:
            s = store.search_chunks(conn, emb.embed_query(q), None, 1)[0]
            neg.append(s["score"])
            print(f"  {s['score']:.3f}  {q}   → ({s['title']} {s['heading']})"[:130])
        lo = min(correct_scores) if correct_scores else 0
        print(f"\n정답 청크 유사도: 최소 {lo:.3f}, 5% 분위 {sorted(correct_scores)[max(0, int(len(correct_scores) * 0.05))]:.3f}, 중앙값 {statistics.median(correct_scores):.3f}")
        print(f"무관 질문 최고 유사도: 최대 {max(neg):.3f}, 평균 {statistics.mean(neg):.3f}")
        mid = (max(neg) + sorted(correct_scores)[max(0, int(len(correct_scores) * 0.05))]) / 2
        print(f"→ 제안 기준(최대 무관 점수와 정답 5% 분위의 중간): {mid:.3f}")
        if args.verbose:
            for q, rows in misses:
                print(f"\n놓친 질문: {q}")
                for r in rows:
                    print(f"   {r['score']:.3f} {r['title']} | {r['heading']}"[:130])
    return 0


if __name__ == "__main__":
    sys.exit(main())
