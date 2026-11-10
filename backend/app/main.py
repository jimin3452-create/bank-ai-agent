from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.account.router import router as account_router
from app.agent import service as agent_service
from app.agent.router import router as agent_router
from app.card.router import router as card_router
from app.common.db import close_pool, open_pool
from app.common.errors import register_error_handlers
from app.config import settings
from app.notification.router import router as notification_router
from app.spending.router import router as spending_router
from app.transfer import scheduler
from app.transfer.router import router as transfer_router
from app.user.router import router as user_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    open_pool()
    agent_service.start()  # 대화 상태 저장소(체크포인터)와 에이전트 그래프
    if settings.scheduler_enabled:
        scheduler.start()  # 자동이체: 매일 09:00(KST)
    yield
    scheduler.stop()
    agent_service.stop()
    close_pool()


app = FastAPI(title="Bank AI Agent API", lifespan=lifespan)
register_error_handlers(app)
app.include_router(user_router)
app.include_router(account_router)
app.include_router(transfer_router)
app.include_router(card_router)
app.include_router(notification_router)
app.include_router(spending_router)
app.include_router(agent_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
