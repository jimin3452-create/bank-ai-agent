from typing import Annotated

import jwt
from fastapi import Depends, Request
from psycopg import Connection

from app.common.db import get_db
from app.common.errors import AppError
from app.common.security import decode_token

COOKIE_NAME = "access_token"

Db = Annotated[Connection, Depends(get_db)]


def get_current_user(request: Request, conn: Db) -> dict:
    """JWT 쿠키를 검증하고 사용자 행을 돌려준다. 잠금·탈퇴 회원은 거절한다."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise AppError(401, "UNAUTHENTICATED", "로그인이 필요합니다")
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise AppError(401, "TOKEN_EXPIRED", "로그인이 만료되었습니다. 다시 로그인해 주세요")
    except jwt.InvalidTokenError:
        raise AppError(401, "UNAUTHENTICATED", "로그인이 필요합니다")
    user = conn.execute("SELECT * FROM users WHERE id = %s", (payload["sub"],)).fetchone()
    if user is None or user["status"] == "WITHDRAWN":
        raise AppError(401, "UNAUTHENTICATED", "로그인이 필요합니다")
    if user["status"] == "LOCKED":
        raise AppError(403, "ACCOUNT_LOCKED", "계정이 잠겼습니다. 비밀번호 재설정으로 해제할 수 있어요")
    return user


CurrentUser = Annotated[dict, Depends(get_current_user)]
