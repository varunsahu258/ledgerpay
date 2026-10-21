import asyncio
import json
import random
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select, update
from sqlalchemy.dialects import postgresql

from app.db import SessionLocal, engine
from app.main import app
from app.models.entities import Account, Balance
from app.schemas.account import AccountCreate
from app.services.accounts import AccountService
from app.services.balance_locking import ordered_balance_lock_query
from app.services.reconciliation import reconcile


async def _setup_accounts(count: int, starting_balance: int) -> tuple[list[int], int]:
    account_ids: list[int] = []
    async with SessionLocal() as session:
        for index in range(count):
            account = await AccountService(session).create(
                AccountCreate(owner_name=f"property-{uuid.uuid4()}-{index}", currency="USD")
            )
            account_ids.append(account.id)
            await session.execute(
                update(Account)
                .where(Account.id == account.id)
                .values(opening_balance_minor=starting_balance)
            )
            await session.execute(
                update(Balance)
                .where(Balance.account_id == account.id)
                .values(balance_minor=starting_balance)
            )
            await session.commit()
        total = await session.scalar(select(func.coalesce(func.sum(Balance.balance_minor), 0)))
    return account_ids, int(total or 0)


async def _assert_invariants(account_ids: Sequence[int], expected_system_total: int) -> None:
    async with SessionLocal() as session:
        report = await reconcile(session)
        assert report["global_sum_is_zero"], report
        target_mismatches = [
            mismatch
            for mismatch in report["account_mismatches"]
            if mismatch["account_id"] in account_ids
        ]
        assert target_mismatches == [], report
        negative_count = await session.scalar(
            select(func.count()).select_from(Balance).where(Balance.balance_minor < 0)
        )
        assert negative_count == 0
        system_total = await session.scalar(
            select(func.coalesce(func.sum(Balance.balance_minor), 0))
        )
        assert int(system_total or 0) == expected_system_total
        target_balances = (
            await session.scalars(select(Balance).where(Balance.account_id.in_(account_ids)))
        ).all()
        assert len(target_balances) == len(account_ids)


@settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    account_count=st.integers(min_value=2, max_value=10),
    starting_balance=st.integers(min_value=20_000, max_value=30_000),
    operations=st.lists(
        st.tuples(
            st.sampled_from(("transfer", "retry", "conflict", "reverse", "self", "overspend")),
            st.integers(min_value=0, max_value=9),
            st.integers(min_value=0, max_value=9),
            st.integers(min_value=1, max_value=2_500),
        ),
        min_size=0,
        max_size=12,
    ),
)
def test_generated_transfer_sequences_preserve_ledger_invariants(
    account_count: int,
    starting_balance: int,
    operations: list[tuple[str, int, int, int]],
) -> None:
    asyncio.run(_run_property_case(account_count, starting_balance, operations))


async def _run_property_case(
    account_count: int,
    starting_balance: int,
    operations: list[tuple[str, int, int, int]],
) -> None:
    try:
        await _exercise_sequence(account_count, starting_balance, operations)
    finally:
        await engine.dispose()


async def _exercise_sequence(
    account_count: int,
    starting_balance: int,
    operations: list[tuple[str, int, int, int]],
) -> None:
    account_ids, system_total = await _setup_accounts(account_count, starting_balance)
    prefix = f"property-{uuid.uuid4()}"
    requests: list[tuple[str, dict[str, int], int, dict[str, Any]]] = []
    reversible_ids: list[str] = []

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:

        async def apply(kind: str, source_index: int, destination_index: int, amount: int) -> None:
            source = account_ids[source_index % account_count]
            destination = account_ids[destination_index % account_count]
            if kind in {"transfer", "retry", "conflict", "reverse"} and source == destination:
                destination = account_ids[(source_index + 1) % account_count]
            if kind in {"retry", "conflict"} and requests:
                key, old_payload, old_status, old_body = requests[-1]
                payload = old_payload.copy()
                if kind == "conflict":
                    payload["amount_minor"] += 1
                response = await client.post(
                    "/transfers", headers={"Idempotency-Key": key}, json=payload
                )
                if kind == "retry":
                    assert (response.status_code, response.json()) == (old_status, old_body)
                else:
                    assert response.status_code == 409
            elif kind == "reverse" and reversible_ids:
                original_id = reversible_ids[
                    (source_index + destination_index + amount) % len(reversible_ids)
                ]
                reversal_key = f"{prefix}-reverse-{uuid.uuid4()}"
                response = await client.post(
                    f"/transfers/{original_id}/reverse",
                    headers={"Idempotency-Key": reversal_key},
                )
                replay = await client.post(
                    f"/transfers/{original_id}/reverse",
                    headers={"Idempotency-Key": reversal_key},
                )
                assert (replay.status_code, replay.json()) == (
                    response.status_code,
                    response.json(),
                )
            else:
                if kind == "self":
                    destination = source
                elif kind == "overspend":
                    if destination == source:
                        destination = account_ids[(source_index + 1) % account_count]
                    amount = 2_000_000_000
                payload = {
                    "from_account": source,
                    "to_account": destination,
                    "amount_minor": amount,
                }
                key = f"{prefix}-{uuid.uuid4()}"
                response = await client.post(
                    "/transfers", headers={"Idempotency-Key": key}, json=payload
                )
                body = response.json()
                if kind != "self":
                    requests.append((key, payload, response.status_code, body))
                if kind == "self":
                    assert response.status_code == 422
                elif kind == "overspend":
                    assert response.status_code == 422
                else:
                    assert response.status_code in {201, 409, 422}
                    if kind in {"transfer", "reverse"} and response.status_code == 201:
                        reversible_ids.append(body["id"])
            await _assert_invariants(account_ids, system_total)

        for kind, source, destination, amount in operations:
            await apply(kind, source, destination, amount)

        # Guarantee every generated example exercises a successful transfer, replay, key
        # conflict, reversal, reversal replay, already-reversed rejection, and invalid requests.
        await apply("transfer", 0, 1, 25)
        successful_id = reversible_ids[-1]
        await apply("retry", 0, 1, 25)
        await apply("conflict", 0, 1, 25)
        reversal_key = f"{prefix}-required-reversal"
        reverse_response = await client.post(
            f"/transfers/{successful_id}/reverse", headers={"Idempotency-Key": reversal_key}
        )
        assert reverse_response.status_code == 201
        reverse_replay = await client.post(
            f"/transfers/{successful_id}/reverse", headers={"Idempotency-Key": reversal_key}
        )
        assert (reverse_replay.status_code, reverse_replay.json()) == (
            reverse_response.status_code,
            reverse_response.json(),
        )
        second_reversal = await client.post(
            f"/transfers/{successful_id}/reverse",
            headers={"Idempotency-Key": f"{prefix}-second-reversal"},
        )
        assert second_reversal.status_code == 409
        await _assert_invariants(account_ids, system_total)
        await apply("self", 0, 0, 10)
        await apply("overspend", 0, 1, 10)


def test_deterministic_concurrency_workload_preserves_invariants_and_writes_report() -> None:
    asyncio.run(_run_concurrency_case())


async def _run_concurrency_case() -> None:
    try:
        await _run_concurrency_workload()
    finally:
        await engine.dispose()


async def _run_concurrency_workload() -> None:
    lock_sql = str(ordered_balance_lock_query([2, 1]).compile(dialect=postgresql.dialect()))
    assert "ORDER BY balances.account_id ASC" in lock_sql
    assert lock_sql.index("ORDER BY") < lock_sql.index("FOR UPDATE")
    rng = random.Random(271828)
    account_ids, system_total = await _setup_accounts(10, 50_000)
    jobs: list[tuple[int, int, int]] = []
    for _ in range(50):
        source = rng.randrange(10)
        destination = rng.choice([index for index in range(10) if index != source])
        amount = rng.randint(1, 100)
        jobs.extend([(source, destination, amount), (destination, source, amount)])
    for index in range(100):
        source = rng.randrange(10)
        destination = (
            source
            if index % 5 == 0
            else rng.choice([candidate for candidate in range(10) if candidate != source])
        )
        jobs.append((source, destination, rng.randint(1, 100)))
    rng.shuffle(jobs)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:

        async def worker(index: int, job: tuple[int, int, int]) -> tuple[int, dict[str, Any]]:
            source, destination, amount = job
            response = await client.post(
                "/transfers",
                headers={"Idempotency-Key": f"stress-{uuid.uuid4()}-{index}"},
                json={
                    "from_account": account_ids[source],
                    "to_account": account_ids[destination],
                    "amount_minor": amount,
                },
            )
            return response.status_code, response.json()

        results = await asyncio.wait_for(
            asyncio.gather(*(worker(index, job) for index, job in enumerate(jobs))),
            timeout=60,
        )

    async with SessionLocal() as session:
        report = await reconcile(session)
        negative_count = await session.scalar(
            select(func.count()).select_from(Balance).where(Balance.balance_minor < 0)
        )
        new_system_total = await session.scalar(
            select(func.coalesce(func.sum(Balance.balance_minor), 0))
        )
    violations: list[str] = []
    if not report["global_sum_is_zero"]:
        violations.append("global ledger sum is not zero")
    target_mismatches = [
        mismatch
        for mismatch in report["account_mismatches"]
        if mismatch["account_id"] in account_ids
    ]
    if target_mismatches:
        violations.append("stored balances differ from ledger sums")
    if negative_count:
        violations.append("a balance is negative")
    if int(new_system_total or 0) != system_total:
        violations.append("total system money changed")
    succeeded = sum(status == 201 for status, _body in results)
    rejected = sum(status != 201 for status, _body in results)
    unexpected_statuses = [status for status, _body in results if status not in {201, 422}]
    if unexpected_statuses:
        violations.append(f"unexpected response statuses: {unexpected_statuses}")

    output = {
        "run_status": "passed" if not violations else "failed",
        "transfers_attempted": len(jobs),
        "succeeded": succeeded,
        "rejected": rejected,
        "invariant_violations": len(violations),
        "violations": violations,
    }
    result_path = Path(__file__).parent / "results" / "invariants.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")

    assert len(results) == 200
    assert succeeded + rejected == 200
    assert not violations, output
