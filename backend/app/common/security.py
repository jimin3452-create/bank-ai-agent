from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import settings

_hasher = PasswordHasher()


def hash_secret(value: str) -> str:
    """비밀번호·PIN·통장 비밀번호·인증번호 해시."""
    return _hasher.hash(value)


def verify_secret(hashed: str, value: str) -> bool:
    try:
        return _hasher.verify(hashed, value)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def create_token(user_id: str) -> str:
    exp = datetime.now(tz=timezone.utc) + timedelta(minutes=settings.jwt_minutes)
    return jwt.encode({"sub": str(user_id), "exp": exp}, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    """만료면 jwt.ExpiredSignatureError, 위조·형식 오류면 jwt.InvalidTokenError."""
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
