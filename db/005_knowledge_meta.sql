-- RAG 지식베이스 보강 (docs/agent-spec.md RAG 절)
-- 003_rag.sql 이후에 적용한다.

ALTER TABLE "knowledge_documents"
	-- 원문 출처 주소 (법령 원문 링크 등)
	ADD COLUMN IF NOT EXISTS "source_url" VARCHAR(500),
	-- 청크 내용의 해시. 같으면 다시 임베딩하지 않는다(적재 스크립트가 사용)
	ADD COLUMN IF NOT EXISTS "content_hash" VARCHAR(64);

ALTER TABLE "knowledge_chunks"
	-- 출처 표시용 소제목 (예: 제9조(전자금융거래 계약의 효력), FAQ 질문, 상품명)
	ADD COLUMN IF NOT EXISTS "heading" VARCHAR(300);

COMMENT ON COLUMN "knowledge_documents"."source_type" IS
	'출처 구분: TERMS 이 앱 약관 / PRODUCT 이 앱 상품 / FAQ 이 앱 FAQ / GUIDE 소비관리 가이드 / LAW 법령 / STANDARD_TERMS 표준약관 / MARKET_PRODUCT 시중 상품(공시) / KDIC_FAQ 예금보험공사 FAQ';
COMMENT ON COLUMN "knowledge_documents"."source_url" IS '원문 출처 주소';
COMMENT ON COLUMN "knowledge_documents"."content_hash" IS '청크 내용 해시(변경이 없으면 재임베딩 생략)';
COMMENT ON COLUMN "knowledge_chunks"."heading" IS '출처 표시용 소제목';
