-- 가맹점 -> 카테고리 공통 룰 (docs/seed-data.md 1.4)
-- merchant_key는 정규화한 값: 소문자·공백 제거, 지점명 제거, 특수문자 제거.
-- user_id가 NULL인 공통 룰이며 source는 RULE이다.

INSERT INTO merchant_category_map (user_id, merchant_key, category_id, source)
SELECT NULL, m.merchant_key, c.id, 'RULE'
FROM (VALUES
	('FOOD', '맥도날드'), ('FOOD', '롯데리아'), ('FOOD', '김밥천국'), ('FOOD', '본죽'), ('FOOD', '배달의민족'),
	('FOOD', '요기요'), ('FOOD', '맘스터치'), ('FOOD', '교촌치킨'), ('FOOD', '서브웨이'), ('FOOD', '한솥도시락'),
	('CAFE', '스타벅스'), ('CAFE', '투썸플레이스'), ('CAFE', '이디야커피'), ('CAFE', '메가커피'),
	('CAFE', '컴포즈커피'), ('CAFE', '빽다방'), ('CAFE', '파리바게뜨'), ('CAFE', '뚜레쥬르'),
	('TRANSPORT', '카카오t'), ('TRANSPORT', '서울교통공사'), ('TRANSPORT', '코레일'), ('TRANSPORT', '티머니'),
	('TRANSPORT', '쏘카'), ('TRANSPORT', 'gs칼텍스'), ('TRANSPORT', 'sk에너지'),
	('SHOPPING', '쿠팡'), ('SHOPPING', '무신사'), ('SHOPPING', '올리브영'), ('SHOPPING', '다이소'),
	('SHOPPING', '11번가'), ('SHOPPING', '지마켓'), ('SHOPPING', '자라'),
	('LIVING', '이마트'), ('LIVING', '홈플러스'), ('LIVING', '롯데마트'), ('LIVING', 'gs25'),
	('LIVING', 'cu'), ('LIVING', '세븐일레븐'), ('LIVING', '컬리'),
	('MEDICAL', '온누리약국'), ('MEDICAL', '서울내과의원'), ('MEDICAL', '365치과'), ('MEDICAL', '올리브약국'),
	('CULTURE', 'cgv'), ('CULTURE', '메가박스'), ('CULTURE', '롯데시네마'), ('CULTURE', '교보문고'),
	('CULTURE', '예스24'), ('CULTURE', '인터파크티켓'),
	('SUBSCRIPTION', '넷플릭스'), ('SUBSCRIPTION', '유튜브프리미엄'), ('SUBSCRIPTION', '멜론'),
	('SUBSCRIPTION', '스포티파이'), ('SUBSCRIPTION', 'skt통신요금'), ('SUBSCRIPTION', 'kt통신요금'),
	('SUBSCRIPTION', '쿠팡와우'),
	('EDUCATION', '인프런'), ('EDUCATION', '클래스101'), ('EDUCATION', '영어회화학원'), ('EDUCATION', '패스트캠퍼스')
) AS m(category_code, merchant_key)
JOIN spending_categories c ON c.code = m.category_code
WHERE NOT EXISTS (
	SELECT 1 FROM merchant_category_map x
	WHERE x.user_id IS NULL AND x.merchant_key = m.merchant_key
);
