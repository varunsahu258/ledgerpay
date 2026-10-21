import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import normalize_database_url, settings
from app.db import SessionLocal
from app.main import app, demo_rate_limiter
from app.models.entities import Account


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/accounts", {"owner_name": "Rate test", "currency": "USD"}),
        ("/transfers", {}),
        (f"/transfers/{uuid4()}/reverse", {}),
    ],
)
@pytest.mark.asyncio
async def test_demo_rate_limit_applies_to_all_write_endpoints(
    path: str, body: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "demo_rate_limit_requests", 1)
    monkeypatch.setattr(settings, "demo_rate_limit_window_seconds", 60)
    monkeypatch.setattr(settings, "demo_max_accounts", 10_000)
    demo_rate_limiter.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(path, json=body)
        health = await client.get("/health")
        limited = await client.post(path, json=body)

    assert first.status_code != 429
    assert health.status_code == 200
    assert limited.status_code == 429
    assert limited.json() == {
        "code": "demo_rate_limited",
        "message": "Too many write requests from this IP; retry later",
    }
    assert limited.headers["retry-after"] == "60"
    demo_rate_limiter.clear()


@pytest.mark.asyncio
async def test_demo_account_cap_is_atomic_for_concurrent_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with SessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(Account))
    assert count is not None
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "demo_max_accounts", count + 1)
    monkeypatch.setattr(settings, "demo_rate_limit_requests", 100)
    demo_rate_limiter.clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    "/accounts",
                    json={"owner_name": f"Cap race {index}", "currency": "USD"},
                )
                for index in range(2)
            )
        )

    assert sorted(response.status_code for response in responses) == [201, 429]
    cap_error = next(response for response in responses if response.status_code == 429)
    assert cap_error.json() == {
        "code": "demo_account_limit_reached",
        "message": "This public demo has reached its account limit",
    }
    async with SessionLocal() as session:
        final_count = await session.scalar(select(func.count()).select_from(Account))
    assert final_count == count + 1
    demo_rate_limiter.clear()


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "postgres://user:pass@db.example/demo?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://user:pass@db.example/demo?ssl=require",
        ),
        (
            "postgresql://user:pass@db.example/demo?sslmode=verify-full",
            "postgresql+asyncpg://user:pass@db.example/demo?ssl=verify-full",
        ),
        (
            "postgresql+asyncpg://user:pass@localhost/demo",
            "postgresql+asyncpg://user:pass@localhost/demo",
        ),
    ],
)
def test_neon_postgres_urls_normalize_for_asyncpg(source: str, expected: str) -> None:
    assert normalize_database_url(source) == expected
