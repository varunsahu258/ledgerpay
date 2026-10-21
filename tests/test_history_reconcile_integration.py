import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.db import SessionLocal
from app.main import app
from app.models.entities import Account, Balance, LedgerEntry, Transfer
from app.schemas.account import AccountCreate
from app.services.accounts import AccountService
from app.services.reconciliation import reconcile


async def _account(owner: str, balance_minor: int = 0) -> int:
    async with SessionLocal() as session:
        account = await AccountService(session).create(
            AccountCreate(owner_name=owner, currency="USD")
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


@pytest.mark.asyncio
async def test_history_cursor_paginates_ledger_ids_and_filters_dates() -> None:
    source = await _account("history-source", balance_minor=1_000)
    destination = await _account("history-destination")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for index in range(3):
            response = await client.post(
                "/transfers",
                headers={"Idempotency-Key": f"history-{uuid.uuid4()}"},
                json={
                    "from_account": source,
                    "to_account": destination,
                    "amount_minor": 10,
                },
            )
            assert response.status_code == 201, f"transfer {index} failed: {response.text}"

        first = await client.get(
            f"/accounts/{source}/transactions?limit=2&start_date=2000-01-01&end_date=2099-12-31"
        )
        future_only = await client.get(f"/accounts/{source}/transactions?start_date=2099-01-01")
        assert first.status_code == 200
        assert future_only.status_code == 200
        assert future_only.json()["items"] == []
        first_page = first.json()
        assert first_page["has_more"] is True
        assert len(first_page["items"]) == 2
        ids = [item["id"] for item in first_page["items"]]
        assert ids == sorted(ids, reverse=True)

        second = await client.get(
            f"/accounts/{source}/transactions?limit=2&cursor={first_page['next_cursor']}"
        )
    assert second.status_code == 200
    second_page = second.json()
    assert second_page["has_more"] is False
    assert len(second_page["items"]) == 1
    assert second_page["items"][0]["id"] < ids[-1]


@pytest.mark.asyncio
async def test_transfer_reversal_is_new_idempotent_transfer_and_only_once() -> None:
    source = await _account("reversal-source", balance_minor=1_000)
    destination = await _account("reversal-destination")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        original_response = await client.post(
            "/transfers",
            headers={"Idempotency-Key": f"original-{uuid.uuid4()}"},
            json={"from_account": source, "to_account": destination, "amount_minor": 250},
        )
        assert original_response.status_code == 201
        original_id = original_response.json()["id"]
        key = f"reverse-{uuid.uuid4()}"
        first = await client.post(
            f"/transfers/{original_id}/reverse", headers={"Idempotency-Key": key}
        )
        replay = await client.post(
            f"/transfers/{original_id}/reverse", headers={"Idempotency-Key": key}
        )
        another_attempt = await client.post(
            f"/transfers/{original_id}/reverse",
            headers={"Idempotency-Key": f"reverse-again-{uuid.uuid4()}"},
        )

    assert first.status_code == 201
    assert first.json()["reversal_of"] == original_id
    assert first.json()["id"] != original_id
    assert replay.status_code == first.status_code
    assert replay.json() == first.json()
    assert another_attempt.status_code == 409
    async with SessionLocal() as session:
        original = await session.get(Transfer, uuid.UUID(original_id))
        reversal = await session.get(Transfer, uuid.UUID(first.json()["id"]))
        entries = (
            await session.scalars(
                select(LedgerEntry).where(
                    LedgerEntry.transfer_id.in_(
                        [uuid.UUID(original_id), uuid.UUID(first.json()["id"])]
                    )
                )
            )
        ).all()
    assert original is not None and original.reversal_of is None
    assert reversal is not None and reversal.reversal_of == uuid.UUID(original_id)
    assert len(entries) == 4


@pytest.mark.asyncio
async def test_reverse_missing_transfer_and_reused_key_for_another_transfer() -> None:
    source = await _account("reversal-key-source", balance_minor=1_000)
    first_destination = await _account("reversal-key-destination-1")
    second_destination = await _account("reversal-key-destination-2")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.post(
            f"/transfers/{uuid.uuid4()}/reverse",
            headers={"Idempotency-Key": f"missing-reversal-{uuid.uuid4()}"},
        )
        first_transfer = await client.post(
            "/transfers",
            headers={"Idempotency-Key": f"reversal-key-original-1-{uuid.uuid4()}"},
            json={"from_account": source, "to_account": first_destination, "amount_minor": 100},
        )
        second_transfer = await client.post(
            "/transfers",
            headers={"Idempotency-Key": f"reversal-key-original-2-{uuid.uuid4()}"},
            json={"from_account": source, "to_account": second_destination, "amount_minor": 100},
        )
        key = f"shared-reversal-key-{uuid.uuid4()}"
        reversed_first = await client.post(
            f"/transfers/{first_transfer.json()['id']}/reverse",
            headers={"Idempotency-Key": key},
        )
        reused_for_other = await client.post(
            f"/transfers/{second_transfer.json()['id']}/reverse",
            headers={"Idempotency-Key": key},
        )
    assert missing.status_code == 404
    assert first_transfer.status_code == second_transfer.status_code == 201
    assert reversed_first.status_code == 201
    assert reused_for_other.status_code == 409
    assert reused_for_other.json()["code"] == "idempotency_key_reused"


@pytest.mark.asyncio
async def test_reversal_rejects_failed_transfer_and_insufficient_reversal_funds() -> None:
    poor_source = await _account("failed-reversal-source")
    other = await _account("failed-reversal-destination")
    funded_source = await _account("drained-reversal-source", balance_minor=500)
    drained_destination = await _account("drained-reversal-destination")
    third = await _account("drained-reversal-third")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        failed_key = f"failed-original-{uuid.uuid4()}"
        failed = await client.post(
            "/transfers",
            headers={"Idempotency-Key": failed_key},
            json={"from_account": poor_source, "to_account": other, "amount_minor": 5},
        )
        assert failed.status_code == 422
        async with SessionLocal() as session:
            failed_transfer = await session.scalar(
                select(Transfer).where(Transfer.idempotency_key == failed_key)
            )
            assert failed_transfer is not None
            failed_transfer_id = str(failed_transfer.id)
        failed_reversal = await client.post(
            f"/transfers/{failed_transfer_id}/reverse",
            headers={"Idempotency-Key": f"failed-reverse-{uuid.uuid4()}"},
        )

        original = await client.post(
            "/transfers",
            headers={"Idempotency-Key": f"drain-original-{uuid.uuid4()}"},
            json={
                "from_account": funded_source,
                "to_account": drained_destination,
                "amount_minor": 500,
            },
        )
        drain = await client.post(
            "/transfers",
            headers={"Idempotency-Key": f"drain-destination-{uuid.uuid4()}"},
            json={
                "from_account": drained_destination,
                "to_account": third,
                "amount_minor": 500,
            },
        )
        assert original.status_code == 201
        assert drain.status_code == 201
        insufficient_reversal = await client.post(
            f"/transfers/{original.json()['id']}/reverse",
            headers={"Idempotency-Key": f"insufficient-reverse-{uuid.uuid4()}"},
        )

    assert failed_reversal.status_code == 409
    assert failed_reversal.json()["code"] == "transfer_not_reversible"
    assert insufficient_reversal.status_code == 422
    assert insufficient_reversal.json()["code"] == "insufficient_funds"


@pytest.mark.asyncio
async def test_reconciliation_catches_corrupted_stored_balance() -> None:
    account_id = await _account("reconcile-corrupt")
    async with SessionLocal() as session:
        await session.execute(
            update(Balance).where(Balance.account_id == account_id).values(balance_minor=7)
        )
        await session.commit()
        report = await reconcile(session)
        await session.execute(
            update(Balance).where(Balance.account_id == account_id).values(balance_minor=0)
        )
        await session.commit()

    assert report["ok"] is False
    mismatch = next(row for row in report["account_mismatches"] if row["account_id"] == account_id)
    assert mismatch == {
        "account_id": account_id,
        "ledger_balance_minor": 0,
        "stored_balance_minor": 7,
    }
    assert report["global_sum_is_zero"] is True


@pytest.mark.asyncio
async def test_history_rejects_invalid_date_range() -> None:
    account_id = await _account("history-date-range")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/accounts/{account_id}/transactions?start_date=2026-02-02&end_date=2026-02-01"
        )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_date_range"


@pytest.mark.asyncio
async def test_history_missing_account_returns_not_found() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/accounts/9223372036854775000/transactions")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
