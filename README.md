# Bank AI Agent

은행 모바일 웹서비스 클론에 자연어 에이전트(챗 + RAG)와 소비패턴 관리를 붙이는 중간 프로젝트.

## 제출물 체크리스트
| 제출물 | 위치 | 상태 |
|---|---|---|
| 기획 자료 (기능 목록, 이용 흐름, DB 구조 등) | [docs/](docs/) | 작성됨 |
| 실행 코드 | `backend/`, `frontend/`, `db/`, `scripts/` | 구현 전 |
| 실행 안내(README) | 이 문서 | 구현 후 완성 |
| 회고 | [docs/retrospective.md](docs/retrospective.md) | 진행 기록 중 |

## 문서
| 문서 | 내용 |
|---|---|
| [docs/product-spec.md](docs/product-spec.md) | 금융앱 기본 기능 기획·설계 (기능 목록, 이용 흐름, 화면, 테스트, DB) |
| [docs/agent-spec.md](docs/agent-spec.md) | 자연어 에이전트 기획 (기능 커버리지, 소비 정의, LangGraph, RAG) |
| [docs/decisions.md](docs/decisions.md) | 미정이던 정책값의 확정안 |
| [docs/api-spec.md](docs/api-spec.md) | API 명세와 화면 링크 허용 목록 |
| [docs/agent-prompts.md](docs/agent-prompts.md) | 에이전트 프롬프트·되묻기 규칙 |
| [docs/seed-data.md](docs/seed-data.md) | 가상 데이터 설계 |
| [docs/term-mapping.md](docs/term-mapping.md) | 한글명 = 영문 테이블·컬럼 매핑 |

## 폴더
| 폴더 | 내용 |
|---|---|
| `db/` | PostgreSQL 스키마 `001_init.sql`(기본), `002_spending.sql`(소비), `003_rag.sql`(RAG), `004_product_conditions.sql`(상품 가입 조건)와 `seed/` |
| `backend/` | Python + FastAPI. 기능별 폴더(`user`, `account`, `transfer`, `card`, `notification`, `spending`, `agent`) |
| `frontend/` | Next.js (모바일 웹) |
| `knowledge/` | RAG 지식 문서 원본(FAQ·소비 가이드) |
| `scripts/` | 가상 데이터 생성, 지식 문서 적재 |

## 기술스택
Python 3.12 · FastAPI · PostgreSQL 16(pgvector) · SQL 직접 작성(`psycopg`) · LangGraph/LangChain · Gemini API · Next.js · Docker Compose

## 실행 방법 (구현하면서 채운다)
### 1. DB와 가상 데이터 (구현됨)
Docker Desktop이 필요하다. PostgreSQL은 호스트 포트 **5433**(컨테이너 안은 5432)을 쓴다. PC에 이미 PostgreSQL이 5432를 쓰고 있어도 충돌하지 않는다.
```bash
docker compose up -d                       # PostgreSQL(pgvector) + Mailpit, 최초 기동 시 db/001~004 자동 적용
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install "psycopg[binary]" argon2-cffi cryptography
# 고정 시드 적용 (약관·상품·카테고리·가맹점 룰)
for f in db/seed/*.sql; do docker compose cp "$f" db:/tmp/ && docker compose exec -T db psql -U bank -d bank -v ON_ERROR_STOP=1 -q -f "/tmp/$(basename $f)"; done
backend/.venv/Scripts/python scripts/seed_demo.py       # 가상 회원·계좌·카드·거래 생성 (.env가 없으면 자동 생성)
backend/.venv/Scripts/python scripts/verify_spending.py # 소비 집계·원장 잔액 검증
```
- 가상 회원은 `demo_a`(주 시연), `demo_b`, `demo_c`이고 비밀번호·PIN은 `.env`의 `DEMO_*` 값이다.
- 맥/리눅스에서는 `backend/.venv/bin/python`을 쓴다.

### 2. 백엔드 (회원·인증까지 구현됨)
```bash
cd backend
.venv/Scripts/python -m pip install fastapi uvicorn pydantic-settings "psycopg[binary,pool]" pyjwt argon2-cffi cryptography "pydantic[email]" pytest httpx
.venv/Scripts/python -m uvicorn app.main:app --reload   # http://localhost:8000/docs 에서 API 확인
.venv/Scripts/python -m pytest -q                       # 테스트(실제 DB 사용, docker compose up 상태여야 함)
```
- 인증번호 메일은 Mailpit(http://localhost:8025)에서 확인한다.
- 구현된 API:
  - 회원·인증: 약관, 이메일 인증번호, 회원가입, 로그인(ID/PW·PIN), 로그아웃, 비밀번호 재설정, 내 정보, PIN 확인, 접속 기록
  - 계좌: 상품 안내·가입 가능 여부, 계좌 개설, 목록·상세, 거래내역 조회·검색·상세, 거래내역 다운로드(CSV 메일), 즐겨찾기·별칭, 이체한도 조회·변경, 통장 비밀번호 확인(5회 오류 시 거래중지), 거래중지 해제, 해지 가능 여부·해지
  - 이체: 받는 분 확인, 즉시이체(PIN·중복 방지 키·한도·트랜잭션), 이체 결과 조회, 최근·자주 쓰는 계좌, 자동이체 등록·해지·실행(매일 09:00 KST 스케줄러, 개발용 즉시 실행 API 포함)
  - 나머지(카드·소비·에이전트)는 [docs/api-spec.md](docs/api-spec.md) 기준으로 구현 예정이다.

### 3. 프론트엔드
설치와 실행 명령은 구현 후 여기에 적는다.

## 구현한 기능
(구현 후 작성. 기능 ID는 [docs/agent-spec.md](docs/agent-spec.md) 1.3절 기준)

## 확인해 볼 사용 흐름
(구현 후 작성. [docs/product-spec.md](docs/product-spec.md) 7절 FLOW-001~010 기준으로 데모 계정 `demo_a`로 확인)

## 자연어 요청 예시
| 요청 | 기대 동작 |
|---|---|
| "이번 달 카페에 얼마 썼어?" → "지난달은?" | 소비 조회, 후속 질문 맥락 유지 |
| "이체해줘" | 받는 사람·금액을 되묻고, 이체 화면 링크로 안내 |
| "서준한테 5만원 보내줘" | 받는 계좌·금액이 채워진 이체 화면 링크 |
| "식비 예산 40만원으로 설정해줘" | 확인 후 예산 저장 |
| "청년 통장 가입 조건이 뭐야?" | 상품 정보·약관 검색(RAG)으로 답변, 출처 표시 |
| "거래중지는 어떻게 풀어?" | FAQ 근거로 안내와 해당 화면 링크 |
| "카드 분실했어" | 카드 분실 신고 화면 링크와 긴급 안내 |

## 동작 확인 결과
구현한 기능과 직접 선정한 실패 상황의 확인 결과를 아래에 기록한다. (테스트 ID는 [docs/product-spec.md](docs/product-spec.md) 10절, [docs/agent-spec.md](docs/agent-spec.md) 10절)

| 구분 | 상황 | 기대 결과 | 결과 |
|---|---|---|---|
| 실패 | 잔액 부족·한도 초과·거래중지 계좌로 이체 | 처리 차단, 잔액·원장 변경 없음 | 미실행 |
| 실패 | 같은 이체 요청을 두 번 전송 | 한 번만 처리 | 미실행 |
| 실패 | 다른 회원의 계좌·카드 ID로 직접 조회 | 차단, 정보 미노출 | 미실행 |
| 실패 | 로그인 5회 실패 | 계정 잠금 | 미실행 |
| 실패 | 잔액이 남은 계좌 해지 | 제한 사유와 함께 차단 | 미실행 |
| 실패 | 만료된 이메일 인증번호 사용 | 인증 실패 안내 | 미실행 |
| 실패 | 에이전트에 PIN을 말하며 이체 요청 | PIN 미사용, 이체 화면 링크만 안내 | 미실행 |
| 실패 | 문서에 없는 질문 | 근거 없음 안내, 지어내지 않음 | 미실행 |
| 실패 | LLM 호출 실패 | 재시도 안내와 관련 화면 링크 | 미실행 |

## 미해결 제한
[docs/agent-spec.md](docs/agent-spec.md) 12절 참조.
