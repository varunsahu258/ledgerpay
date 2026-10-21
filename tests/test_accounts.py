import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_create_and_get_account() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/accounts", json={"owner_name": "Ada Lovelace", "currency": "USD"}
        )
        assert created.status_code == 201
        body = created.json()
        assert body["owner_name"] == "Ada Lovelace"
        assert body["currency"] == "USD"
        assert isinstance(body["id"], int)
        assert body["created_at"]

        fetched = await client.get(f"/accounts/{body['id']}")
        assert fetched.status_code == 200
        assert fetched.json() == body


@pytest.mark.asyncio
async def test_create_account_rejects_invalid_currency() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/accounts", json={"owner_name": "Ada", "currency": "usd"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_health_and_missing_account_error_shape() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        health = await client.get("/health")
        missing = await client.get("/accounts/9223372036854775000")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert missing.status_code == 404
    assert missing.json() == {"code": "not_found", "message": "Account not found"}


@pytest.mark.asyncio
async def test_account_list_paginates_and_includes_current_balance() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/accounts", json={"owner_name": "List One", "currency": "USD"})
        second = await client.post("/accounts", json={"owner_name": "List Two", "currency": "USD"})
        page = await client.get("/accounts", params={"cursor": first.json()["id"], "limit": 1})
        console = await client.get("/console/")

    assert page.status_code == 200
    assert page.json()["items"][0]["id"] == second.json()["id"]
    assert page.json()["items"][0]["balance_minor"] == 0
    assert "LedgerPay Console" in console.text
