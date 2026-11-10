import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.card import service
from app.card.schemas import DevCardPaymentRequest, IssueCardRequest, PinRequest, SettingsRequest
from app.common.deps import CurrentUser, Db
from app.common.errors import AppError
from app.config import settings

router = APIRouter(prefix="/api")


@router.post("/cards", status_code=201)
def issue(body: IssueCardRequest, conn: Db, user: CurrentUser):
    return service.issue_card(conn, user, body)


@router.get("/cards")
def cards(conn: Db, user: CurrentUser, include_inactive: bool = False):
    return service.list_cards(conn, user["id"], include_inactive)


@router.get("/cards/{card_id}")
def card(card_id: uuid.UUID, conn: Db, user: CurrentUser):
    return service.card_detail(conn, user["id"], card_id)


@router.get("/cards/{card_id}/payments")
def payments(card_id: uuid.UUID, conn: Db, user: CurrentUser,
             from_date: Annotated[date | None, Query(alias="from")] = None,
             to_date: Annotated[date | None, Query(alias="to")] = None,
             page: Annotated[int, Query(ge=1)] = 1, size: Annotated[int, Query(ge=1, le=100)] = 20):
    return service.list_payments(conn, user["id"], card_id, from_date, to_date, page, size)


@router.patch("/cards/{card_id}/settings")
def change_settings(card_id: uuid.UUID, body: SettingsRequest, conn: Db, user: CurrentUser):
    return service.change_settings(conn, user, card_id, body.daily_limit, body.overseas_enabled, body.pin)


@router.post("/cards/{card_id}/suspend")
def suspend(card_id: uuid.UUID, body: PinRequest, conn: Db, user: CurrentUser):
    return service.suspend(conn, user, card_id, body.pin)


@router.post("/cards/{card_id}/resume")
def resume(card_id: uuid.UUID, body: PinRequest, conn: Db, user: CurrentUser):
    return service.resume(conn, user, card_id, body.pin)


@router.post("/cards/{card_id}/report-lost")
def report_lost(card_id: uuid.UUID, body: PinRequest, conn: Db, user: CurrentUser):
    return service.report_lost(conn, user, card_id, body.pin)


@router.post("/cards/{card_id}/reissue", status_code=201)
def reissue(card_id: uuid.UUID, body: PinRequest, conn: Db, user: CurrentUser):
    return service.reissue(conn, user, card_id, body.pin)


@router.post("/cards/{card_id}/cancel")
def cancel(card_id: uuid.UUID, body: PinRequest, conn: Db, user: CurrentUser):
    return service.cancel(conn, user, card_id, body.pin)


@router.post("/dev/card-payments", status_code=201)
def dev_card_payment(body: DevCardPaymentRequest, conn: Db, user: CurrentUser):
    """개발용 카드 결제 시뮬레이터. 운영(`APP_ENV`가 dev가 아님)에서는 막는다."""
    if settings.app_env != "dev":
        raise AppError(404, "NOT_FOUND", "찾을 수 없습니다")
    return service.simulate_payment(conn, user, body.card_id, body.amount, body.place, body.overseas)
