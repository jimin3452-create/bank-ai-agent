"""가맹점명 정규화. 지점명이 달라도 같은 가맹점으로 묶고, 카테고리 룰 조회 키로 쓴다 (docs/seed-data.md 1.4)."""
import re

# 공백 뒤에 오는 지점 표기: 강남점, 선릉역점, 판교지점 ('서점'처럼 한 글자+점은 가맹점명의 일부로 본다)
_BRANCH = re.compile(r"\s+(?:[가-힣0-9]{2,}점|[가-힣0-9]+역점|[가-힣0-9]+지점|본점)$")


def strip_branch(name: str) -> str:
    """'스타벅스 강남점' -> '스타벅스'. 원래의 대소문자와 띄어쓰기는 유지한다(화면 표시용)."""
    return _BRANCH.sub("", name.strip())


def merchant_key(name: str) -> str:
    """'GS25 역삼점' -> 'gs25', 'SKT 통신요금' -> 'skt통신요금'. 룰·보정 조회 키."""
    return re.sub(r"[^0-9a-z가-힣]", "", strip_branch(name).lower())
