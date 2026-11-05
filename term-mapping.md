# 용어 매핑표 (한글명 = 영문 테이블·컬럼명)

기준: `Internet Banking_2026-11-05T06_15_28.588Z.sql` (PostgreSQL). 한글 설명은 SQL의 COMMENT를 그대로 옮겼고, 영문은 SQL 이름과 동일하다.

## 1. 테이블

| 한글명 | 영문 테이블명 |
|---|---|
| 회원 | users |
| 이메일 인증번호 | verification_codes |
| 약관 | terms |
| 약관 동의 | term_agreements |
| 로그인 접속 기록 | login_histories |
| 알림 | notifications |
| 계좌 상품 | account_products |
| 계좌 | accounts |
| 거래원장(거래내역) | account_transactions |
| 거래내역 다운로드 신청 | statement_requests |
| 자주 쓰는 받는 계좌 | favorite_recipients |
| 이체 | transfers |
| 자동이체 | auto_transfers |
| 체크카드 | cards |
| 카드 결제내역 | card_payments |

## 2. 컬럼

### 회원 = users

| 한글명 | 영문 컬럼명 | 타입 |
|---|---|---|
| 회원 ID | id | UUID |
| 로그인 아이디 | login_id | VARCHAR(30) |
| 이메일 | email | VARCHAR(255) |
| 이름 | user_name | VARCHAR(50) |
| 생년월일 | birth | DATE |
| 휴대폰 번호 | phone_num | VARCHAR(20) |
| 비밀번호 (해시) | password_hash | VARCHAR(255) |
| 간편비밀번호 PIN 6자리 (해시) | pin | VARCHAR(255) |
| 로그인 실패 횟수 | login_fail_count | INT |
| PIN 실패 횟수 | pin_fail_count | INT |
| 회원 상태 | status | VARCHAR(20) |
| 가입일시 | created_at | TIMESTAMPTZ |
| 탈퇴일시 | withdrawn_at | TIMESTAMPTZ |

### 이메일 인증번호 = verification_codes

| 한글명 | 영문 컬럼명 | 타입 |
|---|---|---|
| 인증번호 ID | id | BIGINT |
| 받는 이메일 | email | VARCHAR(255) |
| 인증 목적 | purpose | VARCHAR(20) |
| 인증번호 (해시) | code_hash | VARCHAR(255) |
| 만료일시 | expires_at | TIMESTAMPTZ |
| 시도 횟수 | attempts | INT |
| 인증 완료일시 | verified_at | TIMESTAMPTZ |

### 약관 = terms

| 한글명 | 영문 컬럼명 | 타입 |
|---|---|---|
| 약관 ID | id | BIGINT |
| 약관 제목 | title | VARCHAR(200) |
| 약관 내용 | content | TEXT |
| 약관 버전 | version | VARCHAR(20) |
| 필수 여부 | required | BOOLEAN |
| 약관 구분 | category | VARCHAR(20) |

### 약관 동의 = term_agreements

| 한글명 | 영문 컬럼명 | 타입 |
|---|---|---|
| 약관동의 ID | id | BIGINT |
| 회원 ID | user_id | UUID |
| 약관 ID | term_id | BIGINT |
| 동의 여부 | agreed | BOOLEAN |
| 동의일시 | agreed_at | TIMESTAMPTZ |

### 로그인 접속 기록 = login_histories

| 한글명 | 영문 컬럼명 | 타입 |
|---|---|---|
| 접속기록 ID | id | BIGINT |
| 회원 ID | user_id | UUID |
| 접속 IP | ip | VARCHAR(45) |
| 접속 기기·브라우저 | user_agent | VARCHAR(500) |
| 로그인 성공 여부 | success | BOOLEAN |
| 접속일시 | created_at | TIMESTAMPTZ |

### 알림 = notifications

| 한글명 | 영문 컬럼명 | 타입 |
|---|---|---|
| 알림 ID | id | BIGINT |
| 회원 ID | user_id | UUID |
| 알림 종류 | type | VARCHAR(30) |
| 알림 내용 | message | VARCHAR(500) |
| 읽은 일시 | read_at | TIMESTAMPTZ |
| 알림 생성일시 | created_at | TIMESTAMPTZ |

### 계좌 상품 = account_products

| 한글명 | 영문 컬럼명 | 타입 |
|---|---|---|
| 상품 ID | id | BIGINT |
| 상품명 | product_name | VARCHAR(100) |
| 연 금리 (%) | interest_rate | NUMERIC(5,3) |
| 상품 설명 | description | TEXT |

### 계좌 = accounts

| 한글명 | 영문 컬럼명 | 타입 |
|---|---|---|
| 계좌 ID | id | UUID |
| 소유 회원 ID | user_id | UUID |
| 상품 ID | product_id | BIGINT |
| 계좌번호 (xxx-xxxx-xxxx) | account_num | VARCHAR(13) |
| 통장 비밀번호 4자리 (해시) | account_password | VARCHAR(255) |
| 통장 비밀번호 실패 횟수 | password_fail_count | INT |
| 잔액 (원) | balance | BIGINT |
| 계좌 별칭 | nickname | VARCHAR(50) |
| 즐겨찾기 여부 | is_favorite | BOOLEAN |
| 1일 이체한도 (원) | daily_limit | BIGINT |
| 1달 이체한도 (원) | month_limit | BIGINT |
| 개설 목적·거래정보 | opening_info | JSONB |
| 계좌 상태 | status | VARCHAR(20) |
| 개설일시 | created_at | TIMESTAMPTZ |
| 해지일시 | closed_at | TIMESTAMPTZ |

### 거래원장(거래내역) = account_transactions

| 한글명 | 영문 컬럼명 | 타입 |
|---|---|---|
| 거래 ID | id | BIGINT |
| 계좌 ID | account_id | UUID |
| 이체 ID | transfer_id | UUID |
| 카드결제 ID | card_payment_id | BIGINT |
| 거래 유형 | transaction_type | VARCHAR(20) |
| 입출금 구분 | transaction_direction | VARCHAR(3) |
| 거래 금액 (원) | amount | BIGINT |
| 거래 후 잔액 (원) | new_balance | BIGINT |
| 상대방 이름 (카드는 가맹점명) | counterparty_name | VARCHAR(100) |
| 상대방 계좌번호 | counterparty_account | VARCHAR(13) |
| 적요 | memo | VARCHAR(100) |
| 거래일시 | transaction_at | TIMESTAMPTZ |

### 거래내역 다운로드 신청 = statement_requests

| 한글명 | 영문 컬럼명 | 타입 |
|---|---|---|
| 다운로드 신청 ID | id | BIGINT |
| 계좌 ID | account_id | UUID |
| 조회 시작일 | from_date | DATE |
| 조회 종료일 | to_date | DATE |
| 받을 이메일 | email | VARCHAR(255) |
| 처리 상태 | status | VARCHAR(20) |
| 신청일시 | created_at | TIMESTAMPTZ |

### 자주 쓰는 받는 계좌 = favorite_recipients

| 한글명 | 영문 컬럼명 | 타입 |
|---|---|---|
| 즐겨찾기 ID | id | BIGINT |
| 회원 ID | user_id | UUID |
| 받는 계좌번호 | account_num | VARCHAR(13) |
| 예금주 | holder_name | VARCHAR(50) |
| 별칭 | alias | VARCHAR(50) |

### 이체 = transfers

| 한글명 | 영문 컬럼명 | 타입 |
|---|---|---|
| 이체 ID | id | UUID |
| 중복 방지 키 | idempotency_key | VARCHAR(100) |
| 출금 계좌 ID | from_account_id | UUID |
| 입금 계좌 ID | to_account_id | UUID |
| 자동이체 ID | auto_transfer_id | UUID |
| 이체 금액 (원) | amount | BIGINT |
| 메모 | memo | VARCHAR(100) |
| 처리 상태 | status | VARCHAR(20) |
| 실패 사유 | fail_reason | VARCHAR(200) |
| 요청일시 | request_at | TIMESTAMPTZ |
| 완료일시 | complete_at | TIMESTAMPTZ |

### 자동이체 = auto_transfers

| 한글명 | 영문 컬럼명 | 타입 |
|---|---|---|
| 자동이체 ID | id | UUID |
| 출금 계좌 ID | from_account_id | UUID |
| 입금 계좌 ID | to_account_id | UUID |
| 이체 금액 (원) | amount | BIGINT |
| 메모 | memo | VARCHAR(100) |
| 주기 | cycle | VARCHAR(10) |
| 실행일 | run_day | INT |
| 시작일 | start_date | DATE |
| 종료일 | end_date | DATE |
| 다음 실행일 | next_run_date | DATE |
| 상태 | status | VARCHAR(20) |
| 등록일시 | created_at | TIMESTAMPTZ |

### 체크카드 = cards

| 한글명 | 영문 컬럼명 | 타입 |
|---|---|---|
| 카드 ID | id | UUID |
| 연결 계좌 ID | account_id | UUID |
| 카드번호 (암호화, 화면은 끝 4자리만) | card_number | VARCHAR(255) |
| 유효기간 (MM/YY) | expiry_date | VARCHAR(5) |
| 카드 브랜드 | card_network | VARCHAR(20) |
| 1일 사용한도 (원) | daily_limit | BIGINT |
| 해외결제 허용 여부 | overseas_enabled | BOOLEAN |
| 재발급 전 카드 ID | reissued_from_id | UUID |
| 카드 상태 | status | VARCHAR(20) |
| 발급일시 | created_at | TIMESTAMPTZ |

### 카드 결제내역 = card_payments

| 한글명 | 영문 컬럼명 | 타입 |
|---|---|---|
| 카드결제 ID | id | BIGINT |
| 카드 ID | card_id | UUID |
| 결제 금액 (원) | amount | BIGINT |
| 가맹점명 | place | VARCHAR(100) |
| 결제 요청일시 | request_at | TIMESTAMPTZ |
| 결제 완료일시 | complete_at | TIMESTAMPTZ |

## 3. 코드값 (한글 = 영문 코드)

### users.status (회원 상태)

| 한글 | 코드 |
|---|---|
| 정상 | ACTIVE |
| 잠금 | LOCKED |
| 탈퇴 | WITHDRAWN |

### verification_codes.purpose (인증 목적)

| 한글 | 코드 |
|---|---|
| 가입 | SIGNUP |
| 거래중지 해제 | UNLOCK_ACCOUNT |
| 비밀번호 재설정 | RESET_PW |

### terms.category (약관 구분)

| 한글 | 코드 |
|---|---|
| 회원가입 | SIGNUP |
| 계좌개설 | ACCOUNT_OPEN |

### notifications.type (알림 종류)

| 한글 | 코드 |
|---|---|
| 카드결제 | CARD_PAYMENT |
| 이상접속 | SUSPICIOUS_LOGIN |
| 자동이체 실패 | AUTO_TRANSFER_FAIL |

### accounts.status (계좌 상태)

| 한글 | 코드 |
|---|---|
| 정상 | ACTIVE |
| 거래중지 | SUSPENDED |
| 해지 | CLOSED |

### account_transactions.transaction_type (거래 유형)

| 한글 | 코드 |
|---|---|
| 입금 | DEPOSIT |
| 출금 | WITHDRAW |
| 이체 | TRANSFER |
| 자동이체 | AUTO_TRANSFER |
| 카드 | CARD |

### account_transactions.transaction_direction (입출금 구분)

| 한글 | 코드 |
|---|---|
| 입금 | IN |
| 출금 | OUT |

### statement_requests.status (처리 상태)

| 한글 | 코드 |
|---|---|
| 접수 | REQUESTED |
| 발송완료 | SENT |
| 실패 | FAILED |

### transfers.status (처리 상태)

| 한글 | 코드 |
|---|---|
| 처리중 | PENDING |
| 성공 | SUCCESS |
| 실패 | FAILED |

### auto_transfers.cycle (주기)

| 한글 | 코드 |
|---|---|
| 매주 | WEEKLY |
| 매월 | MONTHLY |

### auto_transfers.status (상태)

| 한글 | 코드 |
|---|---|
| 사용중 | ACTIVE |
| 종료 | ENDED |
| 해지 | CANCELED |

### cards.card_network (카드 브랜드)

| 한글 | 코드 |
|---|---|
| - | VISA |
| - | MASTER |
| - | LOCAL |

### cards.status (카드 상태)

| 한글 | 코드 |
|---|---|
| 정상 | ACTIVE |
| 정지 | SUSPENDED |
| 분실 | LOST |
| 재발급됨 | REISSUED |
| 해지 | CANCELED |

## 4. 참고

- 한글명은 SQL 주석 기준이며, 기획서 본문에서는 같은 뜻의 표현(예: 통장 비밀번호=account_password)을 쓴다.
- 같은 컬럼명(예: amount, status)이 여러 테이블에 있어, 쓸 때는 `테이블.컬럼`으로 구분한다.
- 실행일(auto_transfers.run_day)은 코드값이 아니라 숫자다: 매주 0(월)~6(일), 매월 1~31.
