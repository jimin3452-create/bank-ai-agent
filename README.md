# Bank AI Agent

은행 모바일 웹서비스 클론에 자연어 에이전트(챗 + RAG)와 소비패턴 관리를 붙이는 중간 프로젝트.

## 제출물 체크리스트
| 제출물 | 위치 | 상태 |
|---|---|---|
| 기획 자료 (기능 목록, 이용 흐름, DB 구조 등) | [docs/](docs/) | 작성됨 |
| 실행 코드 | `backend/`, `frontend/`, `db/`, `scripts/` | 구현됨 (백엔드 테스트 167개 통과) |
| 실행 안내(README) | 이 문서 | 작성됨 |
| 회고 | [docs/retrospective.md](docs/retrospective.md) | 작성됨 |

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
- **에이전트는 Gemini 키가 있어야 동작한다.** `.env`의 `GEMINI_API_KEY=` 뒤에 직접 넣는다(채팅·커밋에 올리지 말 것). 키가 없으면 `/api/agent/chat`은 503을 돌려준다. 모델은 `GEMINI_MODEL`로 바꾼다(기본값은 구현 시점의 공식 문서로 확인).
- 모델의 이해 품질 확인: `backend/.venv/Scripts/python scripts/eval_agent.py` (골든 질문 58개, 키 필요). 결과와 개선 과정은 [docs/agent-spec.md](docs/agent-spec.md) 6절 참조
- **RAG 지식베이스 적재**(DB가 떠 있고 키가 있어야 함): `backend/.venv/Scripts/python scripts/ingest_knowledge.py` — 법령·약관·시중 상품·FAQ·가이드와 이 앱의 약관·상품을 임베딩해 저장한다(약 40초, 내용이 그대로인 문서는 건너뜀). `--dry-run`은 키 없이 청크 수만 센다.
- RAG 검색 품질 확인: `backend/.venv/Scripts/python scripts/eval_rag.py -v` (정답이 정해진 질문 39개). 문서 출처와 사용 범위는 [knowledge/SOURCES.md](knowledge/SOURCES.md)
- 구현된 API:
  - 회원·인증: 약관, 이메일 인증번호, 회원가입, 로그인(ID/PW·PIN), 로그아웃, 비밀번호 재설정, 내 정보, PIN 확인, 접속 기록, 정보 변경(휴대폰·생년월일·이메일), PIN 변경, 회원 탈퇴(제한 사유 확인 포함)
  - 계좌: 상품 안내·가입 가능 여부, 계좌 개설, 목록·상세, 거래내역 조회·검색·상세, 거래내역 다운로드(CSV 메일), 즐겨찾기·별칭, 이체한도 조회·변경, 통장 비밀번호 확인(5회 오류 시 거래중지), 거래중지 해제, 해지 가능 여부·해지
  - 이체: 받는 분 확인, 즉시이체(PIN·중복 방지 키·한도·트랜잭션), 이체 결과 조회, 최근·자주 쓰는 계좌, 자동이체 등록·해지·실행(매일 09:00 KST 스케줄러, 개발용 즉시 실행 API 포함)
  - 카드: 체크카드 발급(번호 AES 암호화·끝 4자리만 표시), 목록·상세, 사용내역, 한도·해외결제 변경, 정지·정지 해제·분실 신고·재발급·해지(모두 PIN), 앱 내 알림
  - 개발용: 카드 결제 시뮬레이터, 입금 시뮬레이터, 자동이체 즉시 실행 (`APP_ENV=dev`에서만 동작)
  - 소비: 월 소비 요약(전월 대비), 카테고리별 집계, 가맹점 TOP, 일별 추이, 두 달 비교, 소비 거래 목록, 가맹점 카테고리 보정, 월·카테고리별 예산과 사용률, 예산 80%·100% 도달 알림 (소비 = 카드 결제 + 타인 명의 이체)
  - 에이전트(LangGraph): 자연어 챗(`/api/agent/chat`)과 승인 처리(`/api/agent/confirm`), 대화 세션 관리. 조회·소비 분석은 직접 답하고, 예산 설정·카테고리 보정·즐겨찾기·거래내역 메일은 승인 후 처리하며, 이체·카드 분실·해지 같은 동작은 화면 링크로 안내한다. 맥락 유지·되묻기·숫자 검증 포함
  - RAG(문서 검색): 약관·법령·시중 상품 공시·앱 FAQ·소비 가이드를 근거로 답하고, 실제로 쓴 문서의 출처를 붙인다. 근거가 없으면 지어내지 않고 모른다고 답한다

### 3. 프론트엔드
Node.js 20 이상(LTS)이 필요하다. 백엔드(8000번)가 먼저 떠 있어야 한다.
```bash
cd frontend
npm install
npm run dev      # http://localhost:3000  (/api/* 요청은 next.config.ts의 rewrites로 백엔드에 전달)
npm run build    # 운영 빌드 확인
```
- 데모 로그인: `demo_a` / `.env`의 `DEMO_PASSWORD`(또는 간편 PIN `DEMO_PIN`). 모바일 화면 폭(430px)에 맞춘 웹이다.
- 백엔드 주소를 바꾸려면 `API_ORIGIN` 환경변수를 지정한다(기본 `http://localhost:8000`).
- 화면: 로그인·회원가입·비밀번호 재설정, 홈, 계좌 개설·상세·관리·해지, 이체·자동이체, 카드 발급·관리, 소비 리포트·예산, 에이전트 챗, 내 정보, 개발용 시뮬레이터(`/dev`).
- 에이전트가 안내하는 화면 링크는 해당 화면을 값이 미리 채워진 상태로 연다(PIN은 항상 화면에서 직접 입력). 10분간 조작이 없으면 자동 로그아웃된다.

## 구현한 기능
기능 ID는 [docs/agent-spec.md](docs/agent-spec.md) 1.3절 기준이고, 구현한 API 목록은 위 "백엔드" 절에 있다.

| 영역 | 구현 내용 |
|---|---|
| 회원·인증 | 약관 동의, 이메일 인증번호, 회원가입, ID/PW·PIN 로그인, 5회 실패 시 잠금, 비밀번호 재설정, 정보 변경, 탈퇴 |
| 계좌 | 상품 안내·개설, 거래내역 조회·검색·CSV 메일, 이체한도, 통장 비밀번호 오류 누적 시 거래중지와 해제, 해지 |
| 이체 | 즉시이체(PIN·한도·중복 방지 키·잠금), 자동이체와 스케줄러 |
| 카드 | 체크카드 발급(번호 암호화), 한도·해외결제, 정지·분실·재발급·해지, 결제 시뮬레이터 |
| 소비 | 월·카테고리·가맹점·일별 집계, 두 달 비교, 예산과 80%·100% 알림 |
| 에이전트 | LangGraph 자연어 챗, 조회·소비 분석 직접 답변, 예산 등 쓰기는 승인 후 처리, 이체·카드 분실 등은 화면 링크로 안내 |
| RAG | 법령·약관·상품·FAQ 검색, 출처 표시, 근거 없으면 모른다고 답변 |
| 프론트엔드 | 모바일 폭 웹: 로그인, 홈, 계좌, 이체, 카드, 소비 리포트, 에이전트 챗 |

## 확인해 볼 사용 흐름
[docs/product-spec.md](docs/product-spec.md) 7절 FLOW 기준이다. 아래 흐름은 데모 계정 `demo_a`로 화면에서 따라 해 볼 수 있고, 각 흐름의 백엔드 동작은 자동 테스트로 확인했다.

1. 로그인(FLOW-002) → 홈에서 계좌 목록 확인
2. 이체(FLOW-005): 받는 계좌·금액 → 받는 분 확인 → PIN → 결과, 같은 요청을 다시 보내도 한 번만 처리
3. 계좌 관리(FLOW-007~009): 이체한도 변경, 거래중지 해제, 잔액이 남은 계좌 해지 시도(차단 확인)
4. 카드(FLOW-010): 발급, 정지, 분실 신고
5. 소비 리포트와 예산 → 에이전트 챗에서 "이번 달 카페에 얼마 썼어?", "청년 통장 가입 조건이 뭐야?"(출처 표시) 질문
6. 가입(FLOW-001)과 자동이체(FLOW-006)도 같은 방식으로 확인할 수 있다.

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

2026-11-23에 `backend`에서 `pytest`를 실행했다(실제 PostgreSQL 사용, 167개 통과). 아래 결과는 해당 테스트가 기대 결과를 단언하는지 읽고 확인한 것이다.

| 구분 | 상황 | 기대 결과 | 결과 | 확인한 테스트 |
|---|---|---|---|---|
| 실패 | 잔액 부족·한도 초과·거래중지 계좌로 이체 | 처리 차단, 잔액·원장 변경 없음 | 통과 | `test_transfer.py`의 `test_insufficient_balance_is_recorded_as_failed`, `test_daily_and_month_limits_count_pending_too`, `test_blocked_source_or_recipient` |
| 실패 | 같은 이체 요청을 두 번 전송 | 한 번만 처리 | 통과 | `test_same_key_is_processed_once_and_mismatch_rejected`, `test_concurrent_same_key_creates_one_transfer` |
| 실패 | 다른 회원의 계좌·카드 ID로 직접 조회 | 차단, 정보 미노출 | 통과 | `test_other_users_account_is_hidden_and_unauthenticated_blocked`(404), `test_list_and_detail_hide_full_number_and_check_owner` |
| 실패 | 로그인 5회 실패 | 계정 잠금 | 통과 | `test_login_fails_five_times_locks_and_reset_unlocks` |
| 실패 | 잔액이 남은 계좌 해지 | 제한 사유와 함께 차단 | 통과 | `test_close_blockers_and_close` |
| 실패 | 만료된 이메일 인증번호 사용 | 인증 실패 안내 | 통과 | `test_code_expired` |
| 실패 | 에이전트에 PIN을 말하며 이체 요청 | PIN 미사용, 이체 화면 링크만 안내 | 통과 | `test_pin_in_message_is_never_used_or_echoed` |
| 실패 | 문서에 없는 질문 | 근거 없음 안내, 지어내지 않음 | 통과 | `test_agent_no_match_and_search_outage` |
| 실패 | LLM 호출 실패 | 재시도 안내와 관련 화면 링크 | 통과 | `test_model_failure_gives_graceful_reply` |

확인 범위의 한계:
- 에이전트 관련 테스트(PIN, 문서 없음, LLM 실패)는 가짜 LLM(`tests/fake_llm.py`)으로 실행했다. 실제 Gemini로 이해 품질을 본 것은 `scripts/eval_agent.py` 골든 질문이며, 이번 제출 직전에는 다시 돌리지 않았다.
- 프론트엔드 화면은 자동 테스트가 없고, 위 표에는 백엔드·에이전트 동작만 기록했다. 제출 직전의 전체 화면 점검은 하지 못했다.

## 미해결 제한
[docs/agent-spec.md](docs/agent-spec.md) 12절 참조.
