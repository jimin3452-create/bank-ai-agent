import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response

from app.common.deps import CurrentUser, Db
from app.common.errors import AppError
from app.config import settings
from app.transfer import service
from app.transfer.schemas import (AutoTransferRequest, CancelRequest, FavoriteRecipientRequest, RunAutoRequest,
                                  TransferRequest)

router = APIRouter(prefix="/api")


@router.get("/recipients/lookup")
def lookup(conn: Db, user: CurrentUser, account_num: Annotated[str, Query(pattern=r"^\d{3}-\d{4}-\d{4}$")]):
    return service.lookup_recipient(conn, user["id"], account_num)


@router.post("/transfers", status_code=201)
def transfer(body: TransferRequest, response: Response, conn: Db, user: CurrentUser,
             idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    result, replayed = service.transfer_now(conn, user, body, idempotency_key)
    if replayed:
        response.status_code = 200  # 이미 처리된 같은 요청: 새로 처리하지 않고 기존 결과를 돌려준다
    return {**result, "replayed": replayed}


@router.get("/transfers/by-key/{key}")
def transfer_by_key(key: str, conn: Db, user: CurrentUser):
    return service.get_transfer_by_key(conn, user["id"], key)


@router.get("/transfers/{transfer_id}")
def transfer_detail(transfer_id: uuid.UUID, conn: Db, user: CurrentUser):
    return service.get_transfer(conn, user["id"], transfer_id)


@router.get("/recipients/recent")
def recent(conn: Db, user: CurrentUser):
    return service.recent_recipients(conn, user["id"])


@router.get("/recipients/favorites")
def favorites(conn: Db, user: CurrentUser):
    return service.list_favorites(conn, user["id"])


@router.post("/recipients/favorites", status_code=201)
def add_favorite(body: FavoriteRecipientRequest, conn: Db, user: CurrentUser):
    return service.add_favorite(conn, user["id"], body.account_num, body.alias)


@router.delete("/recipients/favorites/{favorite_id}", status_code=204)
def delete_favorite(favorite_id: int, conn: Db, user: CurrentUser):
    service.delete_favorite(conn, user["id"], favorite_id)


@router.get("/auto-transfers")
def auto_transfers(conn: Db, user: CurrentUser):
    return service.list_auto_transfers(conn, user["id"])


@router.post("/auto-transfers", status_code=201)
def create_auto_transfer(body: AutoTransferRequest, conn: Db, user: CurrentUser):
    return service.create_auto_transfer(conn, user, body)


@router.post("/auto-transfers/{auto_id}/cancel")
def cancel_auto_transfer(auto_id: uuid.UUID, body: CancelRequest, conn: Db, user: CurrentUser):
    return service.cancel_auto_transfer(conn, user, auto_id, body.pin)


@router.post("/dev/run-auto-transfers")
def dev_run_auto_transfers(body: RunAutoRequest, conn: Db, user: CurrentUser):
    """개발용: 자동이체 스케줄러를 지금 실행한다(`today`로 날짜를 흉내낼 수 있다). 운영에서는 막는다."""
    if settings.app_env != "dev":
        raise AppError(404, "NOT_FOUND", "찾을 수 없습니다")
    return service.run_due_auto_transfers(conn, body.today)
