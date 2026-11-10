from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.common.db import close_pool, open_pool
from app.common.errors import register_error_handlers
from app.user.router import router as user_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    open_pool()
    yield
    close_pool()


app = FastAPI(title="Bank AI Agent API", lifespan=lifespan)
register_error_handlers(app)
app.include_router(user_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
