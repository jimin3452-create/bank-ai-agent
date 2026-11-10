-- 소비 카테고리와 계좌 상품 시드 (docs/seed-data.md 1.2, 1.3)

INSERT INTO spending_categories (code, name) VALUES
	('FOOD', '식비'),
	('CAFE', '카페·간식'),
	('TRANSPORT', '교통'),
	('SHOPPING', '쇼핑'),
	('LIVING', '생활·마트'),
	('MEDICAL', '의료'),
	('CULTURE', '문화·여가'),
	('SUBSCRIPTION', '통신·구독'),
	('EDUCATION', '교육'),
	('TRANSFER', '송금·이체'),
	('ETC', '기타')
ON CONFLICT (code) DO NOTHING;

-- 금리는 안내용이며 이자 계산·지급은 범위 밖이다.
INSERT INTO account_products
	(product_name, interest_rate, description, product_type, min_age, max_age, max_accounts_per_user, join_condition, rate_condition)
SELECT * FROM (VALUES
	('기본 입출금통장', 0.100, '누구나 쉽게 만드는 기본 입출금통장입니다. 입출금과 이체, 체크카드 연결을 자유롭게 이용할 수 있습니다.',
		'DEMAND', 14, NULL::int, 5, '만 14세 이상 가입 가능, 1인 최대 5개까지 개설할 수 있습니다.', '우대금리 조건 없음'),
	('청년 우대 입출금통장', 2.000, '청년을 위한 우대금리 입출금통장입니다. 급여 이체 실적이 있으면 우대금리를 안내해 드립니다.',
		'DEMAND', 19, 34, 1, '만 19세 이상 만 34세 이하 가입 가능, 1인 1개만 개설할 수 있습니다.', '급여 이체 실적이 월 1회 이상이면 우대금리가 적용됩니다(안내용).'),
	('고금리 파킹통장', 2.800, '여유 자금을 넣어 두고 언제든 꺼내 쓸 수 있는 고금리 입출금통장입니다.',
		'DEMAND', 19, NULL::int, 1, '만 19세 이상 가입 가능, 1인 1개만 개설할 수 있습니다.', '잔액 100만원 이상 구간부터 우대금리가 적용됩니다(안내용).'),
	('시니어 우대 입출금통장', 1.500, '만 60세 이상 고객을 위한 우대 입출금통장입니다.',
		'DEMAND', 60, NULL::int, 1, '만 60세 이상 가입 가능, 1인 1개만 개설할 수 있습니다.', '우대금리 조건 없음')
) AS v(product_name, interest_rate, description, product_type, min_age, max_age, max_accounts_per_user, join_condition, rate_condition)
WHERE NOT EXISTS (SELECT 1 FROM account_products p WHERE p.product_name = v.product_name);
