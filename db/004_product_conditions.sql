-- 계좌 상품 가입 조건 확장 (docs/decisions.md 2절, 공지 "상품별 금리와 가입 조건")
-- 001_init.sql 이후에 적용한다.

ALTER TABLE "account_products"
	-- 상품 유형: DEMAND 입출금
	ADD COLUMN IF NOT EXISTS "product_type" VARCHAR(20) NOT NULL DEFAULT 'DEMAND',
	-- 가입 가능 최소 만 나이 (NULL이면 제한 없음)
	ADD COLUMN IF NOT EXISTS "min_age" INT,
	-- 가입 가능 최대 만 나이 (NULL이면 제한 없음)
	ADD COLUMN IF NOT EXISTS "max_age" INT,
	-- 회원당 최대 개설 수
	ADD COLUMN IF NOT EXISTS "max_accounts_per_user" INT NOT NULL DEFAULT 5,
	-- 가입 조건 설명 (화면·RAG 표시용)
	ADD COLUMN IF NOT EXISTS "join_condition" TEXT,
	-- 우대금리 조건 설명
	ADD COLUMN IF NOT EXISTS "rate_condition" TEXT,
	-- 신규 가입 가능 여부
	ADD COLUMN IF NOT EXISTS "is_active" BOOLEAN NOT NULL DEFAULT true;

COMMENT ON COLUMN "account_products"."product_type" IS '상품 유형: DEMAND 입출금';
COMMENT ON COLUMN "account_products"."min_age" IS '가입 가능 최소 만 나이 (NULL이면 제한 없음)';
COMMENT ON COLUMN "account_products"."max_age" IS '가입 가능 최대 만 나이 (NULL이면 제한 없음)';
COMMENT ON COLUMN "account_products"."max_accounts_per_user" IS '회원당 최대 개설 수';
COMMENT ON COLUMN "account_products"."join_condition" IS '가입 조건 설명';
COMMENT ON COLUMN "account_products"."rate_condition" IS '우대금리 조건 설명';
COMMENT ON COLUMN "account_products"."is_active" IS '신규 가입 가능 여부';
