import re
import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

PIN_RE = re.compile(r"^\d{6}$")
DAILY_LIMIT_RANGE = (10_000, 10_000_000)
Network = Literal["VISA", "MASTER", "LOCAL"]


def _pin(v: str) -> str:
    if not PIN_RE.match(v):
        raise ValueError("PIN은 숫자 6자리여야 합니다")
    return v


class IssueCardRequest(BaseModel):
    account_id: uuid.UUID
    card_network: Network = "LOCAL"
    daily_limit: int = 1_000_000
    overseas_enabled: bool = False

    @field_validator("daily_limit")
    @classmethod
    def _limit(cls, v: int) -> int:
        if not DAILY_LIMIT_RANGE[0] <= v <= DAILY_LIMIT_RANGE[1]:
            raise ValueError(f"일일 사용한도는 {DAILY_LIMIT_RANGE[0]:,}원~{DAILY_LIMIT_RANGE[1]:,}원 사이여야 합니다")
        return v


class PinRequest(BaseModel):
    pin: str

    @field_validator("pin")
    @classmethod
    def _p(cls, v: str) -> str:
        return _pin(v)


class SettingsRequest(BaseModel):
    daily_limit: int | None = None
    overseas_enabled: bool | None = None
    pin: str

    @field_validator("pin")
    @classmethod
    def _p(cls, v: str) -> str:
        return _pin(v)

    @field_validator("daily_limit")
    @classmethod
    def _limit(cls, v: int | None) -> int | None:
        if v is not None and not DAILY_LIMIT_RANGE[0] <= v <= DAILY_LIMIT_RANGE[1]:
            raise ValueError(f"일일 사용한도는 {DAILY_LIMIT_RANGE[0]:,}원~{DAILY_LIMIT_RANGE[1]:,}원 사이여야 합니다")
        return v


class DevCardPaymentRequest(BaseModel):
    card_id: uuid.UUID
    amount: int = Field(gt=0, le=10_000_000)
    place: str = Field(min_length=1, max_length=100)
    overseas: bool = False

    @field_validator("place")
    @classmethod
    def _place(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("가맹점명을 입력해 주세요")
        return v
