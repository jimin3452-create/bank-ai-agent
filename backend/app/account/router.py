import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.account import service
from app.account.schemas import (AccountPasswordRequest, CloseRequest, FavoriteRequest, LimitsRequest,
                                 NicknameRequest, OpenAccountRequest, StatementRequest, TxType, UnlockRequest)
from app.common.deps import CurrentUser, Db

router = APIRouter(prefix="/api")


@router.get("/products")
def products(conn: Db, user: CurrentUser):
    return service.list_products(conn)


@router.get("/products/{product_id}/eligibility")
def product_eligibility(product_id: int, conn: Db, user: CurrentUser):
    return service.eligibility(conn, user, product_id)


@router.post("/accounts", status_code=201)
def open_account(body: OpenAccountRequest, conn: Db, user: CurrentUser):
    return service.open_account(conn, user, body)


@router.get("/accounts")
def accounts(conn: Db, user: CurrentUser, include_closed: bool = False):
    return service.list_accounts(conn, user["id"], include_closed)


@router.get("/accounts/{account_id}")
def account(account_id: uuid.UUID, conn: Db, user: CurrentUser):
    return service.account_detail(conn, user["id"], account_id)


@router.get("/accounts/{account_id}/transactions")
def transactions(account_id: uuid.UUID, conn: Db, user: CurrentUser,
                 from_date: Annotated[date | None, Query(alias="from")] = None,
                 to_date: Annotated[date | None, Query(alias="to")] = None,
                 direction: Literal["ALL", "IN", "OUT"] = "ALL",
                 type: Annotated[list[TxType] | None, Query()] = None,
                 min_amount: Annotated[int | None, Query(ge=0)] = None,
                 max_amount: Annotated[int | None, Query(ge=0)] = None,
                 q: Annotated[str | None, Query(max_length=50)] = None,
                 sort: Literal["latest", "oldest"] = "latest",
                 page: Annotated[int, Query(ge=1)] = 1,
                 size: Annotated[int, Query(ge=1, le=100)] = 20):
    return service.list_transactions(conn, user["id"], account_id, from_date=from_date, to_date=to_date,
                                     direction=direction, types=type or [], min_amount=min_amount,
                                     max_amount=max_amount, q=q, sort=sort, page=page, size=size)


@router.get("/accounts/{account_id}/transactions/{tx_id}")
def transaction(account_id: uuid.UUID, tx_id: int, conn: Db, user: CurrentUser):
    return service.transaction_detail(conn, user["id"], account_id, tx_id)


@router.post("/accounts/{account_id}/statements", status_code=201)
def request_statement(account_id: uuid.UUID, body: StatementRequest, conn: Db, user: CurrentUser):
    return service.request_statement(conn, user, account_id, body.from_date, body.to_date, body.email)


@router.get("/accounts/{account_id}/statements")
def statements(account_id: uuid.UUID, conn: Db, user: CurrentUser):
    return service.list_statements(conn, user["id"], account_id)


@router.put("/accounts/{account_id}/favorite")
def favorite(account_id: uuid.UUID, body: FavoriteRequest, conn: Db, user: CurrentUser):
    return service.set_favorite(conn, user["id"], account_id, body.is_favorite)


@router.put("/accounts/{account_id}/nickname")
def nickname(account_id: uuid.UUID, body: NicknameRequest, conn: Db, user: CurrentUser):
    return service.set_nickname(conn, user["id"], account_id, body.nickname)


@router.get("/accounts/{account_id}/limits")
def limits(account_id: uuid.UUID, conn: Db, user: CurrentUser):
    return service.get_limits(conn, user["id"], account_id)


@router.put("/accounts/{account_id}/limits")
def change_limits(account_id: uuid.UUID, body: LimitsRequest, conn: Db, user: CurrentUser):
    return service.change_limits(conn, user, account_id, body.daily_limit, body.month_limit, body.pin)


@router.post("/accounts/{account_id}/verify-password")
def verify_password(account_id: uuid.UUID, body: AccountPasswordRequest, conn: Db, user: CurrentUser):
    service.verify_account_password(conn, user["id"], account_id, body.account_password)
    return {"verified": True}


@router.post("/accounts/{account_id}/unlock/email-code")
def unlock_email_code(account_id: uuid.UUID, conn: Db, user: CurrentUser):
    service.send_unlock_code(conn, user, account_id)
    return {"sent": True}


@router.post("/accounts/{account_id}/unlock")
def unlock(account_id: uuid.UUID, body: UnlockRequest, conn: Db, user: CurrentUser):
    return service.unlock_account(conn, user, account_id, body.code)


@router.get("/accounts/{account_id}/close-check")
def close_check(account_id: uuid.UUID, conn: Db, user: CurrentUser):
    return service.close_check(conn, user["id"], account_id)


@router.post("/accounts/{account_id}/close")
def close(account_id: uuid.UUID, body: CloseRequest, conn: Db, user: CurrentUser):
    return service.close_account(conn, user, account_id, body.pin)
