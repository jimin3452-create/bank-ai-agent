# Bank AI Agent

모바일 웹 인터넷뱅킹에 소비패턴 관리 에이전트(챗 + 리포트 + RAG)를 붙이는 프로젝트.

## 문서
- [docs/product-spec.md](docs/product-spec.md): 금융앱 기본 기능 기획·설계
- [docs/agent-spec.md](docs/agent-spec.md): 소비패턴 관리 에이전트 기획
- [docs/term-mapping.md](docs/term-mapping.md): 한글명 = 영문 테이블·컬럼 매핑

## 폴더
| 폴더 | 내용 |
|---|---|
| `db/` | PostgreSQL 스키마(`001_init.sql` 기본, `002_spending.sql` 소비 확장, `003_rag.sql` RAG)와 `seed/` |
| `backend/` | Python + FastAPI. 기능별 폴더(`user`, `account`, `transfer`, `card`, `notification`, `spending`, `agent`) |
| `frontend/` | Next.js (모바일 웹) |
| `knowledge/` | RAG 지식 문서 원본(FAQ·소비 가이드 등) |
| `scripts/` | 가상 데이터 생성, 지식 문서 임베딩 적재 등 |

## 실행 (뼈대 단계)
```bash
cp .env.example .env      # 값 채우기
docker compose up -d      # PostgreSQL(pgvector) + Mailpit
```

구현은 아직 시작 전이다. 백엔드·프론트엔드 설치와 실행 방법은 구현하면서 이 문서에 추가한다.
