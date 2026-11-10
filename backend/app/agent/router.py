import uuid

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from app.agent import service
from app.common.deps import CurrentUser, Db

router = APIRouter(prefix="/api/agent")


class ChatRequest(BaseModel):
    session_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=service.MAX_MESSAGE)


class ConfirmRequest(BaseModel):
    session_id: uuid.UUID
    action_id: str = Field(min_length=8, max_length=64)
    approve: bool


@router.post("/chat")
def chat(body: ChatRequest, conn: Db, user: CurrentUser):
    return service.chat(conn, user, body.message, body.session_id)


@router.post("/confirm")
def confirm(body: ConfirmRequest, conn: Db, user: CurrentUser):
    return service.confirm(conn, user, body.session_id, body.action_id, body.approve)


@router.get("/sessions")
def sessions(conn: Db, user: CurrentUser):
    return service.list_sessions(conn, user["id"])


@router.get("/sessions/{session_id}/messages")
def messages(session_id: uuid.UUID, conn: Db, user: CurrentUser):
    return service.list_messages(conn, user["id"], session_id)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: uuid.UUID, conn: Db, user: CurrentUser):
    service.delete_session(conn, user["id"], session_id)
    return Response(status_code=204)
