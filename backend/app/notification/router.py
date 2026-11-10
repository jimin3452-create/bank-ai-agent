from typing import Annotated

from fastapi import APIRouter, Query

from app.common.deps import CurrentUser, Db
from app.notification import service

router = APIRouter(prefix="/api")


@router.get("/notifications")
def notifications(conn: Db, user: CurrentUser, unread: bool = False,
                  limit: Annotated[int, Query(ge=1, le=100)] = 30):
    return service.list_notifications(conn, user["id"], unread, limit)


@router.put("/notifications/read-all")
def read_all(conn: Db, user: CurrentUser):
    return service.mark_all_read(conn, user["id"])


@router.put("/notifications/{notification_id}/read")
def read(notification_id: int, conn: Db, user: CurrentUser):
    return service.mark_read(conn, user["id"], notification_id)
