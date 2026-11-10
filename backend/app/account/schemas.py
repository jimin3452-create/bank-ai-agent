import re
import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

ACCOUNT_PW_RE = re.compile(r"^\d{4}$")
PIN_RE = re.compile(r"^\d{6}$")

Purpose = Literal["SALARY", "SAVING", "LIVING", "BUSINESS", "OTHER"]
IncomeSource = Literal["SALARY_INCOME", "BUSINESS_INCOME", "PENSION", "ALLOWANCE", "OTHER"]
TxType = Literal["DEPOSIT", "WITHDRAW", "TRANSFER", "AUTO_TRANSFER", "CARD"]


def _pin(v: str) -> str:
    if not PIN_RE.match(v):
        raise ValueError("PIN은 숫자 6자리여야 합니다")
    return v


class OpenAccountRequest(BaseModel):
    product_id: int
    account_password: str
    account_password_confirm: str
    purpose: Purpose
    income_source: IncomeSource
    nickname: str | None = Field(default=None, max_length=50)
    agreed_term_ids: list[int]

    @field_validator("account_password", "account_password_confirm")
    @classmethod
    def _pw(cls, v: str) -> str:
        if not ACCOUNT_PW_RE.match(v):
            raise ValueError("통장 비밀번호는 숫자 4자리여야 합니다")
        return v

    @model_validator(mode="after")
    def _same(self):
        if self.account_password != self.account_password_confirm:
            raise ValueError("통장 비밀번호 확인이 일치하지 않습니다")
        return self


class FavoriteRequest(BaseModel):
    is_favorite: bool


class NicknameRequest(BaseModel):
    nickname: str

    @field_validator("nickname")
    @classmethod
    def _nick(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 50:
            raise ValueError("별칭은 1~50자여야 합니다")
        return v


class LimitsRequest(BaseModel):
    daily_limit: int
    month_limit: int
    pin: str

    @field_validator("pin")
    @classmethod
    def _p(cls, v: str) -> str:
        return _pin(v)


class AccountPasswordRequest(BaseModel):
    account_password: str

    @field_validator("account_password")
    @classmethod
    def _pw(cls, v: str) -> str:
        if not ACCOUNT_PW_RE.match(v):
            raise ValueError("통장 비밀번호는 숫자 4자리여야 합니다")
        return v


class UnlockRequest(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not re.fullmatch(r"\d{6}", v):
            raise ValueError("인증번호는 숫자 6자리입니다")
        return v


class CloseRequest(BaseModel):
    pin: str

    @field_validator("pin")
    @classmethod
    def _p(cls, v: str) -> str:
        return _pin(v)


class StatementRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    email: EmailStr | None = None


class DevDepositRequest(BaseModel):
    account_id: uuid.UUID
    amount: int = Field(gt=0, le=1_000_000_000)
    counterparty_name: str = Field(default="시연 입금", min_length=1, max_length=100)
    memo: str | None = Field(default=None, max_length=100)
