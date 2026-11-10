import re

from pydantic import BaseModel, Field, field_validator

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class MerchantCategoryRequest(BaseModel):
    merchant: str = Field(min_length=1, max_length=100)
    category_code: str = Field(min_length=1, max_length=30)


class BudgetRequest(BaseModel):
    month: str
    category_code: str | None = None   # 없으면 월 전체 예산
    amount: int = Field(gt=0, le=1_000_000_000)

    @field_validator("month")
    @classmethod
    def _month(cls, v: str) -> str:
        if not MONTH_RE.match(v):
            raise ValueError("월 형식이 올바르지 않습니다 (예: 2026-11)")
        return v
