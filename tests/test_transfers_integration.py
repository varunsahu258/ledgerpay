import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from app.db import SessionLocal
from app.main import app
from app.models.entities import Account, Balance, Transfer
from app.schemas.account import AccountCreate
from app.services.accounts import AccountService


async def _make_account(owner: str, currency: str = "USD", balance_minor: int = 0) -> int:
    async with SessionLocal() as session:
        account = await AccountService(session).create(
            AccountCreate(owner_name=owner, currency=currency)
        )
        account_id = account.id
        if balance_minor:
            await session.execute(
                update(Account)
                .where(Account.id == account_id)
                .values(opening_balance_minor=balance_minor)
            )
            await session.execute(
                update(Balance)
                .where(Balance.account_id == account_id)
                .values(balance_minor=balance_minor)
            )
            await session.commit()
        return account_id


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_transfer_success_writes_result() -> None:
    source = await _make_account("transfer-source", balance_minor=10_000)
    destination = await _make_account("transfer-destination")
    async with _client() as client:
        response = await client.post(
            "/transfers",
            headers={"Idempotency-Key": f"transfer-success-{uuid.uuid4()}"},
            json={"from_account": source, "to_account": destination, "amount_minor": 1250},
        )
    assert response.status_code == 201
    assert response.json()["status"] == "completed"
    async with SessionLocal() as session:
        source_balance = await session.get(Balance, source)
        destination_balance = await session.get(Balance, destination)
        assert source_balance is not None and source_balance.balance_minor == 8750
        assert destination_balance is not None and destination_balance.balance_minor == 1250


@pytest.mark.asyncio
async def test_transfer_insufficient_funds_is_422() -> None:
    source = await _make_account("poor-source")
    destination = await _make_account("poor-destination")
    async with _client() as client:
        key = f"transfer-insufficient-{uuid.uuid4()}"
        response = await client.post(
            "/transfers",
            headers={"Idempotency-Key": key},
            json={"from_account": source, "to_account": destination, "amount_minor": 1},
        )
        replay = await client.post(
            "/transfers",
            headers={"Idempotency-Key": key},
            json={"from_account": source, "to_account": destination, "amount_minor": 1},
        )
        conflict = await client.post(
            "/transfers",
            headers={"Idempotency-Key": key},
            json={"from_account": source, "to_account": destination, "amount_minor": 2},
        )
    assert response.status_code == 422
    assert response.json() == {"code": "insufficient_funds", "message": "Insufficient funds"}
    assert (replay.status_code, replay.json()) == (response.status_code, response.json())
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_transfer_rejects_different_currencies() -> None:
    source = await _make_account("currency-source", currency="USD", balance_minor=500)
    destination = await _make_account("currency-destination", currency="EUR")
    async with _client() as client:
        response = await client.post(
            "/transfers",
            headers={"Idempotency-Key": f"currency-{uuid.uuid4()}"},
            json={"from_account": source, "to_account": destination, "amount_minor": 1},
        )
    assert response.status_code == 422
    assert response.json()["code"] == "currency_mismatch"


@pytest.mark.asyncio
async def test_transfer_missing_account_is_rejected_without_insert() -> None:
    destination = await _make_account("missing-account-destination")
    key = f"transfer-missing-{uuid.uuid4()}"
    payload = {
        "from_account": 9_223_372_036_854_774_999,
        "to_account": destination,
        "amount_minor": 10,
    }
    async with _client() as client:
        first = await client.post("/transfers", headers={"Idempotency-Key": key}, json=payload)
        replay = await client.post("/transfers", headers={"Idempotency-Key": key}, json=payload)
    assert first.status_code == 404
    assert replay.status_code == first.status_code
    assert replay.json() == first.json()
    async with SessionLocal() as session:
        transfer = await session.scalar(select(Transfer).where(Transfer.idempotency_key == key))
    assert transfer is None


@pytest.mark.asyncio
async def test_same_account_transfer_is_rejected_before_insert() -> None:
    account = await _make_account("same-account")
    key = f"transfer-self-{uuid.uuid4()}"
    async with _client() as client:
        response = await client.post(
            "/transfers",
            headers={"Idempotency-Key": key},
            json={"from_account": account, "to_account": account, "amount_minor": 1},
        )
    assert response.status_code == 422
    assert response.json()["code"] == "same_account"
    async with SessionLocal() as session:
        transfer = await session.scalar(select(Transfer).where(Transfer.idempotency_key == key))
    assert transfer is None


@pytest.mark.asyncio
async def test_duplicate_key_same_payload_replays_status_and_body() -> None:
    source = await _make_account("replay-source", balance_minor=500)
    destination = await _make_account("replay-destination")
    async with _client() as client:
        first = await client.post(
            "/transfers",
            headers={"Idempotency-Key": f"transfer-replay-{uuid.uuid4()}"},
            json={"from_account": source, "to_account": destination, "amount_minor": 100},
        )
        replay = await client.post(
            "/transfers",
            headers={"Idempotency-Key": first.request.headers["Idempotency-Key"]},
            json={"from_account": source, "to_account": destination, "amount_minor": 100},
        )
    assert replay.status_code == first.status_code
    assert replay.json() == first.json()


@pytest.mark.asyncio
async def test_duplicate_key_different_payload_returns_409() -> None:
    source = await _make_account("mismatch-source", balance_minor=500)
    destination = await _make_account("mismatch-destination")
    idem_key = f"transfer-mismatch-{uuid.uuid4()}"
    async with _client() as client:
        await client.post(
            "/transfers",
            headers={"Idempotency-Key": idem_key},
            json={"from_account": source, "to_account": destination, "amount_minor": 100},
        )
        response = await client.post(
            "/transfers",
            headers={"Idempotency-Key": idem_key},
            json={"from_account": source, "to_account": destination, "amount_minor": 101},
        )
    assert response.status_code == 409
    assert response.json()["code"] == "idempotency_key_reused"


@pytest.mark.asyncio
async def test_same_key_50_concurrent_requests_create_one_transfer() -> None:
    source = await _make_account("concurrent-source", balance_minor=10_000)
    destination = await _make_account("concurrent-destination")
    body = {"from_account": source, "to_account": destination, "amount_minor": 37}
    idem_key = f"transfer-concurrent-50-{uuid.uuid4()}"

    async with _client() as client:
        responses = await asyncio.gather(
            *[
                client.post(
                    "/transfers",
                    headers={"Idempotency-Key": idem_key},
                    json=body,
                )
                for _ in range(50)
            ]
        )

    assert {response.status_code for response in responses} == {201}
    assert all(response.json() == responses[0].json() for response in responses)
    async with SessionLocal() as session:
        count = await session.scalar(
            select(func.count()).select_from(Transfer).where(Transfer.idempotency_key == idem_key)
        )
    assert count == 1
