from typing import Literal

from fastapi import APIRouter, Request, Response

from app.common.deps import COOKIE_NAME, CurrentUser, Db
from app.config import settings
from app.user import service
from app.user.schemas import (EmailCodeRequest, EmailCodeVerifyRequest, LoginRequest, PasswordResetRequest,
                              PinLoginRequest, PinVerifyRequest, SignupRequest)

router = APIRouter(prefix="/api")


def _client(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", secure=settings.cookie_secure,
                        max_age=settings.jwt_minutes * 60, path="/")


@router.get("/terms")
def terms(conn: Db, category: Literal["SIGNUP", "ACCOUNT_OPEN"] = "SIGNUP"):
    return service.list_terms(conn, category)


@router.post("/auth/email-codes")
def send_email_code(body: EmailCodeRequest, conn: Db):
    service.send_code(conn, body.email, body.purpose)
    return {"sent": True}


@router.post("/auth/email-codes/verify")
def verify_email_code(body: EmailCodeVerifyRequest, conn: Db):
    service.verify_code(conn, body.email, body.purpose, body.code)
    return {"verified": True}


@router.get("/auth/check-duplicate")
def check_duplicate(field: Literal["login_id", "email", "phone"], value: str, conn: Db):
    return {"duplicate": service.check_duplicate(conn, field, value)}


@router.post("/auth/signup", status_code=201)
def signup(body: SignupRequest, conn: Db):
    return service.public_user(service.signup(conn, body))


@router.post("/auth/login")
def login(body: LoginRequest, request: Request, response: Response, conn: Db):
    ip, ua = _client(request)
    token, user = service.login_password(conn, body.login_id, body.password, ip, ua)
    _set_cookie(response, token)
    return {"user": user}


@router.post("/auth/login-pin")
def login_pin(body: PinLoginRequest, request: Request, response: Response, conn: Db):
    ip, ua = _client(request)
    token, user = service.login_pin(conn, body.login_id, body.pin, ip, ua)
    _set_cookie(response, token)
    return {"user": user}


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"logged_out": True}


@router.post("/auth/password-reset")
def password_reset(body: PasswordResetRequest, conn: Db):
    service.reset_password(conn, body.email, body.code, body.new_password)
    return {"reset": True}


@router.get("/me")
def me(user: CurrentUser):
    return service.public_user(user)


@router.post("/me/pin/verify")
def verify_pin(body: PinVerifyRequest, user: CurrentUser, conn: Db):
    service.verify_pin(conn, user, body.pin)
    return {"verified": True}


@router.get("/me/login-histories")
def login_histories(user: CurrentUser, conn: Db):
    return service.login_histories(conn, user["id"])
