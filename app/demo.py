"""Seed a self-contained demo through the public HTTP API."""

import asyncio
import json
import random
import uuid
from collections import Counter

import httpx
from sqlalchemy import update

from app.core.config import settings
from app.db import SessionLocal, engine
from app.models.entities import Account, AuditLog, Balance

ACCOUNT_COUNT = 20
TRANSFER_COUNT = 500
OPENING_BALANCE_MINOR = 5_000_000  # USD/EUR 50,000.00 per demo account
OWNERS = (
    "Avery Chen",
    "Morgan Patel",
    "Riley Johnson",
    "Jordan Kim",
    "Taylor Singh",
    "Casey Rivera",
    "Quinn Brooks",
    "Jamie Okafor",
    "Alex Martin",
    "Samira Hassan",
)


async def wait_for_api(client: httpx.AsyncClient) -> None:
    for _ in range(60):
        try:
            if (await client.get("/health")).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1)
    raise RuntimeError("API did not become healthy within 60 seconds")


async def create_accounts(
    client: httpx.AsyncClient, seed_token: str | None = None
) -> list[tuple[int, str]]:
    accounts: list[tuple[int, str]] = []
    for index in range(ACCOUNT_COUNT):
        currency = "USD" if index < ACCOUNT_COUNT // 2 else "EUR"
        owner = f"{OWNERS[index % len(OWNERS)]} {index + 1:02d}"
        headers = {"X-Demo-Seed-Token": seed_token} if seed_token else None
        response = await client.post(
            "/accounts", json={"owner_name": owner, "currency": currency}, headers=headers
        )
        response.raise_for_status()
        accounts.append((int(response.json()["id"]), currency))
    return accounts


async def fund_accounts(account_ids: list[int]) -> None:
    """Record demo-only external funding as an opening baseline, outside transfer history."""
    async with SessionLocal.begin() as session:
        for account_id in account_ids:
            await session.execute(
                update(Account)
                .where(Account.id == account_id)
                .values(opening_balance_minor=OPENING_BALANCE_MINOR)
            )
            await session.execute(
                update(Balance)
                .where(Balance.account_id == account_id)
                .values(balance_minor=OPENING_BALANCE_MINOR, version=Balance.version + 1)
            )
            session.add(
                AuditLog(
                    actor="demo-seeder",
                    action="account.opening_funded",
                    entity="account",
                    entity_id=str(account_id),
                    detail={"amount_minor": OPENING_BALANCE_MINOR, "currency": "account currency"},
                )
            )


async def run_transfers(
    client: httpx.AsyncClient,
    accounts: list[tuple[int, str]],
    seed_token: str | None = None,
) -> Counter[int]:
    rng = random.Random(20261018)
    by_currency = {
        currency: [
            account_id for account_id, account_currency in accounts if account_currency == currency
        ]
        for currency in ("USD", "EUR")
    }
    requests: list[tuple[str, dict[str, int]]] = []
    prefix = uuid.uuid4()
    for index in range(TRANSFER_COUNT):
        currency = "USD" if index % 2 == 0 else "EUR"
        candidates = by_currency[currency]
        source, destination = rng.sample(candidates, 2)
        # $7.50–$425.00 or €7.50–€425.00; all values remain integer minor units.
        amount = rng.randint(750, 42_500)
        requests.append(
            (
                f"demo-{prefix}-{index}",
                {"from_account": source, "to_account": destination, "amount_minor": amount},
            )
        )

    semaphore = asyncio.Semaphore(25)

    async def send(key: str, payload: dict[str, int]) -> int:
        async with semaphore:
            headers = {"Idempotency-Key": key}
            if seed_token:
                headers["X-Demo-Seed-Token"] = seed_token
            response = await client.post("/transfers", headers=headers, json=payload)
            if response.status_code != 201:
                raise RuntimeError(
                    f"Demo transfer failed ({response.status_code}): {response.text}"
                )
            return response.status_code

    statuses = await asyncio.gather(*(send(key, payload) for key, payload in requests))
    return Counter(statuses)


async def seed(base_url: str, seed_token: str | None = None) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        await wait_for_api(client)
        accounts = await create_accounts(client, seed_token)
        await fund_accounts([account_id for account_id, _ in accounts])
        statuses = await run_transfers(client, accounts, seed_token)
    print(
        json.dumps(
            {
                "accounts_created": len(accounts),
                "transfers_attempted": TRANSFER_COUNT,
                "transfers_succeeded": statuses[201],
                "currencies": {"USD": 10, "EUR": 10},
                "opening_balance_minor_per_account": OPENING_BALANCE_MINOR,
            },
            indent=2,
            sort_keys=True,
        )
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=settings.demo_api_base_url)
    parser.add_argument("--seed-token", default=settings.demo_seed_token)
    args = parser.parse_args()

    async def run_and_dispose() -> None:
        try:
            if args.seed_token is None:
                await seed(args.base_url)
            else:
                await seed(args.base_url, seed_token=args.seed_token)
        finally:
            await engine.dispose()

    asyncio.run(run_and_dispose())


if __name__ == "__main__":
    main()
