from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.routes import router
from app.core.config import settings
from app.core.demo_safety import PerIPWriteRateLimiter, is_write_endpoint, seed_token_matches
from app.db import engine

app = FastAPI(
    title="LedgerPay",
    version="0.1.0",
    summary="An auditable double-entry money transfer API",
    description=(
        "All amounts are integer minor units. Transfers are idempotent, lock account balances "
        "in ascending account ID order, and append balanced ledger entries. PostgreSQL is required."
    ),
    openapi_tags=[
        {"name": "Accounts", "description": "Account creation, lookup, pagination, and balances."},
        {"name": "Ledger", "description": "Append-only account transaction history."},
        {"name": "Transfers", "description": "Idempotent transfers and linked reversals."},
    ],
)
app.include_router(router)
app.mount(
    "/console",
    StaticFiles(directory=Path(__file__).parent / "static" / "console", html=True),
    name="console",
)
demo_rate_limiter = PerIPWriteRateLimiter()


@app.middleware("http")
async def public_demo_write_limit(request: Request, call_next: RequestResponseEndpoint) -> Response:
    if settings.demo_mode and is_write_endpoint(request.method, request.url.path):
        if not seed_token_matches(
            request.headers.get("X-Demo-Seed-Token"), settings.demo_seed_token
        ):
            client_ip = request.client.host if request.client is not None else "unknown"
            limited = await demo_rate_limiter.is_limited(
                client_ip,
                limit=settings.demo_rate_limit_requests,
                window_seconds=settings.demo_rate_limit_window_seconds,
            )
            if limited:
                return JSONResponse(
                    status_code=429,
                    content={
                        "code": "demo_rate_limited",
                        "message": "Too many write requests from this IP; retry later",
                    },
                    headers={"Retry-After": str(settings.demo_rate_limit_window_seconds)},
                )
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    del request, exc
    return JSONResponse(
        status_code=422,
        content={"code": "validation_error", "message": "Request validation failed"},
    )


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    del request
    detail = str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": "not_found" if exc.status_code == 404 else "http_error",
            "message": detail,
        },
        headers=exc.headers,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"status": "ok"}
