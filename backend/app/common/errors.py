from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """API 오류. docs/api-spec.md의 오류 응답 형식({code, message, field})으로 변환된다."""

    def __init__(self, status: int, code: str, message: str, field: str | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.field = field


def error_body(code: str, message: str, field: str | None = None) -> dict:
    return {"code": code, "message": message, "field": field}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=error_body(exc.code, exc.message, exc.field))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first["loc"] if p not in ("body", "query", "path"))
        message = first.get("msg", "입력값이 올바르지 않습니다")
        if message.startswith("Value error, "):
            message = message[len("Value error, "):]
        return JSONResponse(status_code=400, content=error_body("VALIDATION_ERROR", message, field or None))
