import re
import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ACCOUNT_NUM_RE = re.compile(r"^\d{3}-\d{4}-\d{4}$")
PIN_RE = re.compile(r"^\d{6}$")
MAX_AMOUNT = 1_000_000_000


def _account_num(v: str) -> str:
    if not ACCOUNT_NUM_RE.match(v):
        raise ValueError("계좌번호 형식이 올바르지 않습니다 (예: 123-4567-8901)")
    return v


def _pin(v: str) -> str:
    if not PIN_RE.match(v):
        raise ValueError("PIN은 숫자 6자리여야 합니다")
    return v


class TransferRequest(BaseModel):
    from_account_id: uuid.UUID
    to_account_num: str
    amount: int = Field(gt=0, le=MAX_AMOUNT)
    memo: str | None = Field(default=None, max_length=100)
    pin: str

    @field_validator("to_account_num")
    @classmethod
    def _num(cls, v: str) -> str:
        return _account_num(v)

    @field_validator("pin")
    @classmethod
    def _p(cls, v: str) -> str:
        return _pin(v)


class FavoriteRecipientRequest(BaseModel):
    account_num: str
    alias: str | None = Field(default=None, max_length=50)

    @field_validator("account_num")
    @classmethod
    def _num(cls, v: str) -> str:
        return _account_num(v)


class AutoTransferRequest(BaseModel):
    from_account_id: uuid.UUID
    to_account_num: str
    amount: int = Field(gt=0, le=MAX_AMOUNT)
    memo: str | None = Field(default=None, max_length=100)
    cycle: Literal["WEEKLY", "MONTHLY"]
    run_day: int
    start_date: date
    end_date: date | None = None
    pin: str

    @field_validator("to_account_num")
    @classmethod
    def _num(cls, v: str) -> str:
        return _account_num(v)

    @field_validator("pin")
    @classmethod
    def _p(cls, v: str) -> str:
        return _pin(v)

    @field_validator("run_day")
    @classmethod
    def _run_day(cls, v: int, info) -> int:
        cycle = info.data.get("cycle")
        if cycle == "WEEKLY" and not 0 <= v <= 6:
            raise ValueError("매주 실행일은 0(월)~6(일)이어야 합니다")
        if cycle == "MONTHLY" and not 1 <= v <= 31:
            raise ValueError("매월 실행일은 1~31이어야 합니다")
        return v

    @field_validator("end_date")
    @classmethod
    def _end_date(cls, v: date | None, info) -> date | None:
        start = info.data.get("start_date")
        if v is not None and start is not None and v < start:
            raise ValueError("종료일은 시작일보다 빠를 수 없습니다")
        return v


class CancelRequest(BaseModel):
    pin: str

    @field_validator("pin")
    @classmethod
    def _p(cls, v: str) -> str:
        return _pin(v)


class RunAutoRequest(BaseModel):
    today: date | None = None
