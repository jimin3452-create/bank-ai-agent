"""에이전트가 사용자의 말에서 뽑아내는 '행동'과 '값'의 형식 (docs/agent-spec.md 1.3 커버리지 표).

LLM은 이 형식으로만 답할 수 있다. 어떤 도구를 어떤 인자로 실행할지는 이 결과를 보고 정해진 코드가 결정한다.
"""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

# --- 직접 처리(조회) ---
QUERY_ACTIONS = (
    "LIST_ACCOUNTS", "ACCOUNT_DETAIL", "ACCOUNT_LIMITS", "SEARCH_TRANSACTIONS", "LIST_RECENT_RECIPIENTS",
    "LIST_FAVORITE_RECIPIENTS", "LIST_AUTO_TRANSFERS", "LIST_CARDS", "CARD_PAYMENTS", "LIST_NOTIFICATIONS",
    "LOGIN_HISTORY", "CLOSE_CHECK", "PRODUCTS_INFO", "KNOWLEDGE_QA", "SPENDING_SUMMARY", "SPENDING_BY_CATEGORY",
    "SPENDING_TOP_MERCHANTS", "SPENDING_COMPARE", "BUDGET_STATUS",
)
# --- 확인 후 직접 처리(가벼운 변경) ---
WRITE_ACTIONS = ("SET_BUDGET", "RECATEGORIZE_MERCHANT", "TOGGLE_FAVORITE_ACCOUNT", "REQUEST_STATEMENT")
# --- 화면 링크(PIN·인증이 필요하거나 되돌릴 수 없는 동작) ---
LINK_ACTIONS = (
    "GO_TRANSFER", "GO_AUTO_TRANSFER", "GO_CHANGE_LIMIT", "GO_UNLOCK_ACCOUNT", "GO_CLOSE_ACCOUNT", "GO_OPEN_ACCOUNT",
    "GO_ISSUE_CARD", "GO_CARD_MANAGE", "GO_PROFILE", "GO_SIGNUP", "GO_LOGIN", "GO_SPENDING_REPORT",
    "GO_BUDGET_SETTING", "GO_ACCOUNT_DETAIL",
)
OTHER_ACTIONS = ("SMALLTALK", "OUT_OF_SCOPE")
ALL_ACTIONS = QUERY_ACTIONS + WRITE_ACTIONS + LINK_ACTIONS + OTHER_ACTIONS

Action = Literal[
    "LIST_ACCOUNTS", "ACCOUNT_DETAIL", "ACCOUNT_LIMITS", "SEARCH_TRANSACTIONS", "LIST_RECENT_RECIPIENTS",
    "LIST_FAVORITE_RECIPIENTS", "LIST_AUTO_TRANSFERS", "LIST_CARDS", "CARD_PAYMENTS", "LIST_NOTIFICATIONS",
    "LOGIN_HISTORY", "CLOSE_CHECK", "PRODUCTS_INFO", "KNOWLEDGE_QA", "SPENDING_SUMMARY", "SPENDING_BY_CATEGORY",
    "SPENDING_TOP_MERCHANTS", "SPENDING_COMPARE", "BUDGET_STATUS",
    "SET_BUDGET", "RECATEGORIZE_MERCHANT", "TOGGLE_FAVORITE_ACCOUNT", "REQUEST_STATEMENT",
    "GO_TRANSFER", "GO_AUTO_TRANSFER", "GO_CHANGE_LIMIT", "GO_UNLOCK_ACCOUNT", "GO_CLOSE_ACCOUNT", "GO_OPEN_ACCOUNT",
    "GO_ISSUE_CARD", "GO_CARD_MANAGE", "GO_PROFILE", "GO_SIGNUP", "GO_LOGIN", "GO_SPENDING_REPORT",
    "GO_BUDGET_SETTING", "GO_ACCOUNT_DETAIL", "SMALLTALK", "OUT_OF_SCOPE",
]


class PeriodSpec(BaseModel):
    """기간. 날짜 계산은 모델이 하지 않고, 상대 표현이나 명시된 값만 적는다(실제 날짜는 코드가 계산한다)."""
    relative: Literal["TODAY", "YESTERDAY", "THIS_WEEK", "LAST_WEEK", "THIS_MONTH", "LAST_MONTH", "LAST_3_MONTHS"] | None = None
    month: str | None = Field(default=None, description="YYYY-MM")
    from_date: date | None = None
    to_date: date | None = None


class Understanding(BaseModel):
    actions: list[Action] = Field(default_factory=list, description="이번 말에서 해야 할 일(보통 1개, 최대 2개)")
    period: PeriodSpec | None = None
    compare_period: PeriodSpec | None = Field(default=None, description="비교 대상 기간(두 기간을 비교할 때)")
    account_hint: str | None = Field(default=None, description="계좌를 가리키는 말(별칭·상품명·끝자리·순서)")
    recipient_hint: str | None = Field(default=None, description="받는 사람을 가리키는 말(별칭·이름) 또는 사용자가 말한 계좌번호")
    amount: int | None = Field(default=None, description="원 단위 정수")
    memo: str | None = None
    category: str | None = Field(default=None, description="소비 카테고리(코드 또는 한글 이름)")
    merchant: str | None = None
    direction: Literal["IN", "OUT"] | None = None
    tx_types: list[Literal["DEPOSIT", "WITHDRAW", "TRANSFER", "AUTO_TRANSFER", "CARD"]] = Field(default_factory=list)
    min_amount: int | None = None
    max_amount: int | None = None
    query_text: str | None = Field(default=None, description="거래 검색어 또는 지식 검색 질문")
    card_hint: str | None = None
    product_hint: str | None = None
    on: bool | None = Field(default=None, description="즐겨찾기를 켜는지(true) 끄는지(false)")
    focus: Literal["profile", "password", "withdraw", "logout", "limit", "lost", "suspend", "reissue", "cancel", "resume"] | None = None
    confirmation: Literal["YES", "NO"] | None = Field(default=None, description="확인을 기다리는 요청에 대한 사용자의 답")
    reference_previous_turn: bool = Field(default=False, description="'그럼 지난달은?'처럼 이전 대화를 이어받는 말인지")

    def slots(self) -> dict:
        """actions를 뺀 값들(이전 대화에서 이어받을 때 쓴다)."""
        return self.model_dump(mode="json", exclude={"actions", "confirmation", "reference_previous_turn"}, exclude_none=True,
                               exclude_defaults=True)
