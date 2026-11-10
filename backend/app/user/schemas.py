import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr, field_validator

LOGIN_ID_RE = re.compile(r"^[a-z0-9_]{4,30}$")
PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)\S{8,64}$")
PIN_RE = re.compile(r"^\d{6}$")
PHONE_RE = re.compile(r"^01[016789]-\d{3,4}-\d{4}$")


def _check_password(v: str) -> str:
    if not PASSWORD_RE.match(v):
        raise ValueError("비밀번호는 공백 없이 영문과 숫자를 포함해 8~64자여야 합니다")
    return v


def _check_pin(v: str) -> str:
    if not PIN_RE.match(v):
        raise ValueError("PIN은 숫자 6자리여야 합니다")
    return v


class EmailCodeRequest(BaseModel):
    email: EmailStr
    purpose: Literal["SIGNUP", "RESET_PW"]


class EmailCodeVerifyRequest(EmailCodeRequest):
    code: str

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not re.fullmatch(r"\d{6}", v):
            raise ValueError("인증번호는 숫자 6자리입니다")
        return v


class SignupRequest(BaseModel):
    login_id: str
    password: str
    pin: str
    email: EmailStr
    user_name: str
    phone_num: str
    birth: date | None = None
    agreed_term_ids: list[int]

    @field_validator("login_id")
    @classmethod
    def _login_id(cls, v: str) -> str:
        if not LOGIN_ID_RE.match(v):
            raise ValueError("아이디는 영문 소문자·숫자·밑줄 4~30자여야 합니다")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return _check_password(v)

    @field_validator("pin")
    @classmethod
    def _pin(cls, v: str) -> str:
        return _check_pin(v)

    @field_validator("user_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 50:
            raise ValueError("이름은 1~50자여야 합니다")
        return v

    @field_validator("phone_num")
    @classmethod
    def _phone(cls, v: str) -> str:
        if not PHONE_RE.match(v):
            raise ValueError("휴대폰 번호 형식이 올바르지 않습니다 (예: 010-1234-5678)")
        return v

    @field_validator("birth")
    @classmethod
    def _birth(cls, v: date | None) -> date | None:
        if v is not None and not (date(1900, 1, 1) <= v <= date.today()):
            raise ValueError("생년월일이 올바르지 않습니다")
        return v


class LoginRequest(BaseModel):
    login_id: str
    password: str


class PinLoginRequest(BaseModel):
    login_id: str
    pin: str

    @field_validator("pin")
    @classmethod
    def _pin(cls, v: str) -> str:
        return _check_pin(v)


class PinVerifyRequest(BaseModel):
    pin: str

    @field_validator("pin")
    @classmethod
    def _pin(cls, v: str) -> str:
        return _check_pin(v)


class PasswordResetRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not re.fullmatch(r"\d{6}", v):
            raise ValueError("인증번호는 숫자 6자리입니다")
        return v

    @field_validator("new_password")
    @classmethod
    def _password(cls, v: str) -> str:
        return _check_password(v)
