# API 명세 (초안)

> 작성일: 2026-11-10 | 백엔드: FastAPI | 자동 생성 문서: 서버 실행 후 `/docs`
> 정책값은 `decisions.md`, 기능 ID는 `product-spec.md`·`agent-spec.md`를 따른다.

## 1. 공통 규칙

- 기본 경로 `/api`. 인증은 로그인 시 발급되는 JWT(httpOnly 쿠키). 표의 "인증"이 `필요`인 API는 쿠키가 없거나 만료되면 401.
- **소유자 검증**: 계좌·카드·거래 ID를 받는 모든 API는 JWT의 사용자 ID와 서버의 소유자 ID를 비교하고, 다르면 404(존재 여부를 알려주지 않음).
- 요청·응답은 JSON. 금액은 원 단위 정수, 시각은 ISO 8601(KST 오프셋 포함).
- 변경 API(이체·발급·해지 등)는 중복 제출 방지를 위해 `Idempotency-Key` 헤더를 받는다(이체는 필수).
- 오류 응답: `{"code": "INSUFFICIENT_BALANCE", "message": "잔액이 부족합니다", "field": null}`.

| HTTP | 코드 예시 |
|---|---|
| 400 | `VALIDATION_ERROR`, `LIMIT_EXCEEDED`, `INSUFFICIENT_BALANCE`, `ACCOUNT_STATUS_BLOCKED` |
| 401 | `UNAUTHENTICATED`, `TOKEN_EXPIRED`, `INVALID_PIN` |
| 403 | `ACCOUNT_LOCKED`(회원 잠금) |
| 404 | `NOT_FOUND` (타인 리소스 포함) |
| 409 | `DUPLICATE_REQUEST`, `DUPLICATE_VALUE`, `CLOSE_NOT_ALLOWED` |
| 429 | `TOO_MANY_REQUESTS`(인증번호 재발송 등) |

## 2. 회원·인증 (A)

| 메서드 | 경로 | 설명 | 기능 ID | 인증 |
|---|---|---|---|---|
| GET | `/api/terms?category=SIGNUP` | 약관 목록 | A1 | 불필요 |
| POST | `/api/auth/email-codes` | 인증번호 발송 `{email, purpose}` | A1, A3, B3.3 | 목적별(가입·재설정은 불필요) |
| POST | `/api/auth/email-codes/verify` | 인증번호 확인 `{email, purpose, code}` | A1, A3, B3.3 | 〃 |
| POST | `/api/auth/signup` | 회원가입 | A1 | 불필요 |
| GET | `/api/auth/check-duplicate?field=login_id\|email\|phone&value=` | 중복 확인 | A1 | 불필요 |
| POST | `/api/auth/login` | ID/PW 로그인 | A2.1 | 불필요 |
| POST | `/api/auth/login-pin` | ID + PIN 로그인 | A2.1 | 불필요 |
| POST | `/api/auth/logout` | 로그아웃(쿠키 삭제) | A2.3 | 필요 |
| GET | `/api/me` | 내 정보 | A3 | 필요 |
| POST | `/api/me/email-code` | 이메일 변경용 인증번호를 **새 이메일**로 발송 `{email}` (목적 `CHANGE_EMAIL`) | A3 | 필요 |
| PATCH | `/api/me` | 정보 변경 `{pin, phone_num?, birth?, email?, email_code?}`. 모든 변경에 PIN 필요, 이메일은 새 이메일 인증번호도 필요, 이름은 변경 불가(보내면 400) | A3 | 필요 |
| POST | `/api/me/pin/verify` | PIN 확인(민감 동작 전 인증) | 공통 | 필요 |
| PUT | `/api/me/pin` | PIN 변경 `{current_pin, new_pin}`. 현재 PIN이 틀리면 실패 횟수가 쌓여 5회째에 잠금 | A3 | 필요 |
| POST | `/api/auth/password-reset` | 비밀번호 재설정(인증번호 확인 후) | A3 | 불필요 |
| GET | `/api/me/withdraw-check` | 탈퇴 가능 여부와 제한 사유(잔액·카드·자동이체) | A3 | 필요 |
| POST | `/api/me/withdraw` | 회원 탈퇴 `{pin}`. 본문이 필요해 DELETE 대신 POST를 쓴다. 성공하면 쿠키를 지움 | A3 | 필요 |
| GET | `/api/me/login-histories` | 접속 기록 | A2.4 | 필요 |

## 3. 계좌 (B)

| 메서드 | 경로 | 설명 | 기능 ID |
|---|---|---|---|
| GET | `/api/products` | 상품 목록(금리·가입 조건 포함) | B1.1 |
| GET | `/api/products/{id}/eligibility` | 내가 이 상품에 가입 가능한지 확인(연령·개설 수) | B1.1 |
| GET | `/api/terms?category=ACCOUNT_OPEN` | 계좌개설 약관 | B1.2 |
| POST | `/api/accounts` | 계좌 개설 `{product_id, account_password, opening_info, agreed_term_ids}` | B1.1~B1.8 |
| GET | `/api/accounts` | 내 계좌 목록(즐겨찾기 우선, 번호 마스킹, 해지 계좌는 `?include_closed=true`일 때만) | B2.1 |
| GET | `/api/accounts/{id}` | 계좌 상세(상태·한도·잔액) | B2.2, B2.8 |
| GET | `/api/accounts/{id}/transactions` | 거래내역 `?from&to&direction&type&min_amount&max_amount&q&sort&page` | B2.3~B2.6 |
| GET | `/api/accounts/{id}/transactions/{txId}` | 거래 상세 | B2.4 |
| POST | `/api/accounts/{id}/statements` | 거래내역 다운로드 신청 `{from, to, email?}`. CSV를 이메일로 바로 보내고 `{id, status: SENT\|FAILED, count, message}`를 돌려줌 | B2.7 |
| GET | `/api/accounts/{id}/statements` | 신청 내역·상태 | B2.7 |
| PUT | `/api/accounts/{id}/favorite` | 즐겨찾기 등록·해제 `{is_favorite}` | B3.1 |
| PUT | `/api/accounts/{id}/nickname` | 별칭 변경 | B2.1 |
| PUT | `/api/accounts/{id}/limits` | 이체한도 변경(PIN) `{daily_limit, month_limit}` | B3.2 |
| GET | `/api/accounts/{id}/limits` | 한도·오늘/이번 달 사용량 | B2.8, B3.2 |
| POST | `/api/accounts/{id}/unlock/email-code` | 거래중지 해제용 인증번호를 내 이메일로 발송(거래중지 상태에서만) | B3.3.2 |
| POST | `/api/accounts/{id}/unlock` | 거래중지 해제 `{code}` | B3.3.2 |
| GET | `/api/accounts/{id}/close-check` | 해지 가능 여부와 제한 사유 | B4.1 |
| POST | `/api/accounts/{id}/close` | 해지(PIN) | B4.2~B4.3 |
| POST | `/api/accounts/{id}/verify-password` | 통장 비밀번호 확인(실패 횟수 누적) | B1.3, 공통 |

## 4. 이체 (C)

| 메서드 | 경로 | 설명 | 기능 ID |
|---|---|---|---|
| GET | `/api/recipients/lookup?account_num=` | 받는 분 확인(마스킹된 예금주) | C1.1 |
| POST | `/api/transfers` | 즉시이체 `{from_account_id, to_account_num, amount, memo?, pin}` + **`Idempotency-Key` 헤더(8~100자, 필수)**. 처음 처리하면 201, 같은 키를 다시 보내면 새로 처리하지 않고 기존 결과를 200(`replayed: true`)으로 돌려줌. 같은 키에 다른 내용을 보내면 409. 잔액·한도·상태 오류는 400이며 이체가 `FAILED`로 기록됨 | C1.1~C1.2 |
| GET | `/api/transfers/by-key/{key}` | 중복 방지 키로 결과 조회(응답 유실 대비, 보낸 사람만) | C1.1 |
| GET | `/api/transfers/{id}` | 이체 상세 | C1 |
| GET | `/api/recipients/recent` | 최근 받은 계좌(이체 내역에서 조회) | C3 |
| GET | `/api/recipients/favorites` | 자주 쓰는 받는 계좌 | C3 |
| POST | `/api/recipients/favorites` | 등록 `{account_num, alias}` | C3 |
| DELETE | `/api/recipients/favorites/{id}` | 해제 | C3 |
| GET | `/api/auto-transfers` | 자동이체 목록 | C2.1 |
| POST | `/api/auto-transfers` | 등록(PIN) `{from_account_id, to_account_num, amount, memo?, cycle, run_day, start_date, end_date?, pin}`. 시작일은 **내일 이후**만 가능(등록 당일 실행 없음) | C2.1 |
| POST | `/api/auto-transfers/{id}/cancel` | 해지(PIN) `{pin}`. 본문이 필요해 DELETE 대신 POST를 쓴다 | C2.3 |

## 5. 카드 (D)

| 메서드 | 경로 | 설명 | 기능 ID |
|---|---|---|---|
| POST | `/api/cards` | 발급 `{account_id, daily_limit, overseas_enabled, card_network}` | D1.1 |
| GET | `/api/cards` | 목록(끝 4자리만 표시, 사용 가능한 카드만. 해지·재발급된 카드까지 보려면 `?include_inactive=true`) | D1.2 |
| GET | `/api/cards/{id}` | 상세 | D1.3 |
| GET | `/api/cards/{id}/payments` | 사용내역 `?from&to` | D1.3 |
| PATCH | `/api/cards/{id}/settings` | 한도·해외결제 변경(PIN) | D1.3 |
| POST | `/api/cards/{id}/suspend` | 정지(PIN) | D1.3 |
| POST | `/api/cards/{id}/resume` | 정지 해제(PIN) | D1.8 |
| POST | `/api/cards/{id}/report-lost` | 분실 신고(PIN) | D1.3 |
| POST | `/api/cards/{id}/reissue` | 재발급(PIN) | D1.4 |
| POST | `/api/cards/{id}/cancel` | 해지(PIN) | D1.7 |
| GET | `/api/notifications` | 알림 목록 `?unread=` | D1.5, A2.4, C2.1 |
| PUT | `/api/notifications/{id}/read` | 읽음 처리(본인 알림만) | D1.5 |
| PUT | `/api/notifications/read-all` | 모두 읽음 처리 | D1.5 |

## 6. 소비(E)

| 메서드 | 경로 | 설명 | 기능 ID |
|---|---|---|---|
| GET | `/api/spending/summary?month=2026-10` | 월 총소비·전월 대비·건수 | E1 |
| GET | `/api/spending/by-category?month=` | 카테고리별 금액·비중 | E1 |
| GET | `/api/spending/top-merchants?month=&n=5` | 가맹점 TOP | E1 |
| GET | `/api/spending/daily?month=` | 일별 추이 | E1 |
| GET | `/api/spending/transactions?month=&category=` | 소비 거래 목록(근거) | E1, E5 |
| GET | `/api/budgets?month=` | 예산과 사용률 | E3 |
| PUT | `/api/budgets` | 예산 설정 `{month, category_code?, amount}` | E3 |
| DELETE | `/api/budgets/{id}` | 예산 삭제 | E3 |
| GET | `/api/spending/categories` | 카테고리 목록 | E5 |
| GET | `/api/spending/compare?month_a=&month_b=` | 두 달 비교(총액·카테고리별 증감, 증가 큰 순) | E1, 에이전트 `compare_periods` |
| GET | `/api/spending/unclassified?month=` | 룰·보정에 없어 '기타'로 보이는 가맹점 목록 | E5 |
| PUT | `/api/spending/merchant-category` | 가맹점 카테고리 보정 `{merchant, category_code}`. 지점명이 달라도 같은 가맹점으로 보정되고(정규화 키), 그 회원에게만 적용됨. `TRANSFER`는 지정 불가 | E5 |
| DELETE | `/api/spending/merchant-category?merchant=` | 사용자 보정 되돌리기(공통 룰은 지울 수 없음) | E5 |

## 7. 에이전트

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/agent/chat` | 메시지 전송 `{session_id?, message}` → 응답 |
| POST | `/api/agent/confirm` | 쓰기 승인·취소 `{session_id, action_id, approve}` → 응답 |
| GET | `/api/agent/sessions` | 최근 대화 세션 목록 |
| GET | `/api/agent/sessions/{id}/messages` | 대화 기록 |
| DELETE | `/api/agent/sessions/{id}` | 대화 삭제 |

**응답 형식**
```json
{
  "session_id": "uuid",
  "reply": "이번 달 카페에는 87,400원을 쓰셨어요.",
  "evidence": [{"tx_id": 1204, "date": "2026-11-03", "merchant": "스타벅스", "amount": 5600}],
  "sources": [{"title": "이체한도 안내", "type": "FAQ"}],
  "links": [{"label": "이체하러 가기", "screen_id": "SCR-006", "route": "/transfer?to=...&amount=50000"}],
  "pending_action": {"action_id": "uuid", "summary": "식비 월 예산을 400,000원으로 설정할까요?"}
}
```
- `evidence`·`sources`·`links`·`pending_action`은 해당할 때만 포함한다.
- `links`의 `route`는 아래 **화면 허용 목록**에 있는 경로만 서버가 만든다. 모델이 만든 URL은 사용하지 않는다.

**화면 허용 목록(링크 대상)**

| screen_id | 경로 | 미리 채울 수 있는 값 |
|---|---|---|
| SCR-001 | `/login` | - |
| SCR-002 | `/signup` | - |
| SCR-003 | `/home` | - |
| SCR-004 | `/accounts/new` | `product_id` |
| SCR-005 | `/accounts/{id}` | `from`, `to`, `type`, `q` |
| SCR-006 | `/transfer` | `from_account_id`, `to_account_num`, `amount`, `memo` |
| SCR-007 | `/auto-transfers` | `from_account_id`, `to_account_num`, `amount`, `cycle`, `run_day` |
| SCR-008 | `/cards` | - |
| SCR-009 | `/accounts/{id}/manage` | `focus=limit\|unlock\|favorite` |
| SCR-010 | `/accounts/{id}/close` | - |
| SCR-011 | `/cards/{id}` | `focus=limit\|lost\|suspend\|reissue\|cancel` |
| SCR-012 | `/cards/new` | `account_id` |
| SCR-013 | `/me` | `focus=profile\|password\|withdraw` |
| SCR-014 | `/spending` | `month` |
| SCR-015 | `/agent` | - |
| SCR-016 | `/spending/budget` | `month` |

링크에 넣는 값은 이체 금액·받는 계좌처럼 사용자가 말한 값뿐이며, PIN·비밀번호·인증번호는 어떤 링크에도 넣지 않는다.

## 8. 개발용 API (운영 제외, `APP_ENV=dev`에서만)

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/dev/card-payments` | 카드 결제 시뮬레이터 `{card_id, amount, place, overseas}`. 승인되면 카드 결제·거래원장·`CARD_PAYMENT` 알림이 만들어지고 계좌에서 바로 차감됨. 거절 사유(`CARD_STATUS_BLOCKED`, `ACCOUNT_STATUS_BLOCKED`, `OVERSEAS_DISABLED`, `INSUFFICIENT_BALANCE`, `LIMIT_EXCEEDED`)는 400이며 아무것도 기록하지 않음. 본인 카드만 사용 가능 |
| POST | `/api/dev/deposits` | 입금 시뮬레이터 `{account_id, amount, counterparty_name, memo}` |
| POST | `/api/dev/run-auto-transfers` | 자동이체 스케줄러 즉시 실행 `{today?}`(시연·테스트용, `today`로 실행 기준 날짜를 흉내냄). 로그인 필요, `APP_ENV=dev`에서만 동작 |
| GET | `/health` | 헬스 체크 |
