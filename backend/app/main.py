from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.account.router import router as account_router
from app.common.db import close_pool, open_pool
from app.common.errors import register_error_handlers
from app.config import settings
from app.transfer import scheduler
from app.transfer.router import router as transfer_router
from app.user.router import router as user_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    open_pool()
    if settings.scheduler_enabled:
        scheduler.start()  # 자동이체: 매일 09:00(KST)
    yield
    scheduler.stop()
    close_pool()


app = FastAPI(title="Bank AI Agent API", lifespan=lifespan)
register_error_handlers(app)
app.include_router(user_router)
app.include_router(account_router)
app.include_router(transfer_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
