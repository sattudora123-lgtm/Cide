import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import Settings
from app.core.context import request_id_var
from app.core.errors import AppError, CommitAndRaise, error_body
from app.core.logging import configure_logging
from app.core.rate_limit import RateLimiter
from app.core.security import hash_password
from app.storage.errors import StorageError, StorageIntegrityError
from app.storage.vault import EncryptedJsonStore

_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
logger = logging.getLogger("cide.access")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    transport = getattr(app.state, "http_transport", None)
    app.state.http = httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(settings.provider_timeout_seconds),
        follow_redirects=False,
    )
    try:
        yield
    finally:
        await app.state.http.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    active = settings or Settings()
    store = EncryptedJsonStore(active.resolved_data_dir(), active.data_key_bytes())
    store.initialize()
    app = FastAPI(
        title="CIDE Backend",
        version="0.1.0",
        description=(
            "Coordination API for CIDE. Data is stored in encrypted local JSON files. "
            "Host AI planning, voice, and browser automation are not implemented."
        ),
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )
    app.state.settings = active
    app.state.store = store
    app.state.rate_limiter = RateLimiter(active.login_rate_limit, active.login_rate_window_seconds)
    app.state.dummy_password_hash = hash_password(uuid4().hex + uuid4().hex)
    app.include_router(api_router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=active.cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    app.middleware("http")(request_middleware)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(CommitAndRaise, commit_and_raise_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(StorageIntegrityError, integrity_handler)
    app.add_exception_handler(StorageError, storage_handler)
    app.add_exception_handler(Exception, unhandled_handler)
    app.openapi = lambda: _openapi(app)
    return app


def _openapi(app: FastAPI) -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema.setdefault("components", {}).setdefault("schemas", {})
    schema["components"]["schemas"]["ErrorResponse"] = {
        "type": "object",
        "required": ["error"],
        "properties": {
            "error": {
                "type": "object",
                "required": ["code", "message"],
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "request_id": {"type": "string"},
                },
            }
        },
    }
    app.openapi_schema = schema
    return schema


async def request_middleware(request: Request, call_next):
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if _REQUEST_ID.fullmatch(incoming) else uuid4().hex
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        declared = request.headers.get("content-length")
        too_large = declared is not None and declared.isdigit() and int(declared) > request.app.state.settings.max_body_bytes
        if too_large:
            response = JSONResponse(
                status_code=413,
                content=error_body("payload_too_large", "Request body is too large"),
            )
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        logger.info(
            "method=%s path=%s status=%s duration_ms=%s request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            int((time.perf_counter() - started) * 1000),
            request_id,
        )
        return response
    finally:
        request_id_var.reset(token)


def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    response = JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))
    if exc.code == "rate_limited":
        response.headers["Retry-After"] = str(request.app.state.settings.login_rate_window_seconds)
    return response


def commit_and_raise_handler(_request: Request, exc: CommitAndRaise) -> JSONResponse:
    return JSONResponse(status_code=exc.error.status_code, content=error_body(exc.error.code, exc.error.message))


def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    parts: list[str] = []
    for error in exc.errors():
        location = [str(item) for item in error.get("loc", []) if item != "body"]
        field = ".".join(location) if location else "request"
        message = str(error.get("msg", "invalid"))
        raw_input = error.get("input")
        if isinstance(raw_input, str) and raw_input and raw_input in message:
            message = "invalid"
        parts.append(f"{field}: {message}")
    summary = "; ".join(parts[:8]) or "Request validation failed"
    return JSONResponse(status_code=422, content=error_body("validation_error", summary))


def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(status_code=exc.status_code, content=error_body(code, detail))


def integrity_handler(_request: Request, _exc: StorageIntegrityError) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=error_body("storage_integrity_error", "Encrypted storage failed integrity checks"),
    )


def storage_handler(_request: Request, _exc: StorageError) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=error_body("storage_unavailable", "Encrypted storage is unavailable"),
    )


def unhandled_handler(_request: Request, exc: Exception) -> JSONResponse:
    logging.getLogger("cide").error("unhandled error type=%s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content=error_body("internal_error", "The server could not complete the request"),
    )


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=8000)
