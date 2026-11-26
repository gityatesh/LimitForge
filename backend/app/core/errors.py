"""One error format for the whole API (FR-34):
{"error_code": "...", "message": "...", "details": [...]}  -- never a stack trace or SQL."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("finora")


class AppError(Exception):
    """Raise this anywhere in the code; the handler below turns it into the JSON envelope."""

    def __init__(self, status_code: int, error_code: str, message: str, details: list | None = None):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details or []


def envelope(status: int, code: str, message: str, details: list | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error_code": code, "message": message, "details": details or []})


# Short-hands so routers read cleanly
def not_found(what: str = "Resource") -> AppError:
    return AppError(404, "NOT_FOUND", f"{what} not found.")


def forbidden(message: str = "You do not have permission to perform this action.") -> AppError:
    return AppError(403, "FORBIDDEN", message)


def conflict(code: str, message: str) -> AppError:
    return AppError(409, code, message)


def unprocessable(code: str, message: str, details: list | None = None) -> AppError:
    return AppError(422, code, message, details)


_HTTP_CODES = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED",
               429: "TOO_MANY_REQUESTS"}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return envelope(exc.status_code, exc.error_code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"),
             "message": str(e["msg"]).removeprefix("Value error, ")}
            for e in exc.errors()
        ]
        return envelope(422, "VALIDATION_ERROR", "One or more fields are invalid.", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        msg = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return envelope(exc.status_code, _HTTP_CODES.get(exc.status_code, "HTTP_ERROR"), msg)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error")  # the full trace stays in the server log only
        return envelope(500, "INTERNAL_ERROR", "An unexpected error occurred. Please try again.")