import asyncio
import json
import sys
from collections import Counter
from typing import Any

import pytest

import app.demo as demo
from app.db import SessionLocal
from app.demo import ACCOUNT_COUNT, TRANSFER_COUNT, create_accounts, run_transfers
from app.models.entities import Account, Balance
from app.schemas.account import AccountCreate
from app.services.accounts import AccountService


class _Response:
    status_code = 201

    def __init__(self, account_id: int = 1) -> None:
        self._account_id = account_id

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, int]:
        return {"id": self._account_id}


class _Client:
    def __init__(self) -> None:
        self.created: list[dict[str, str]] = []
        self.transfers: list[tuple[str, dict[str, Any]]] = []
        self.transfer_status = 201

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def post(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any],
    ) -> _Response:
        if path == "/accounts":
            self.created.append(json)
            return _Response(len(self.created))
        assert path == "/transfers"
        assert headers is not None
        self.transfers.append((headers["Idempotency-Key"], json))
        response = _Response()
        response.status_code = self.transfer_status
        response.text = "demo error"
        return response

    async def get(self, _path: str) -> _Response:
        response = _Response()
        response.status_code = 200
        return response


def test_demo_creates_twenty_accounts_across_two_currencies() -> None:
    async def run() -> None:
        client = _Client()
        accounts = await create_accounts(client)  # type: ignore[arg-type]
        assert len(accounts) == ACCOUNT_COUNT
        assert Counter(currency for _account_id, currency in accounts) == {"USD": 10, "EUR": 10}
        assert len(client.created) == ACCOUNT_COUNT

    asyncio.run(run())


def test_demo_generates_five_hundred_valid_api_transfers() -> None:
    async def run() -> None:
        client = _Client()
        accounts = [(index + 1, "USD" if index < 10 else "EUR") for index in range(ACCOUNT_COUNT)]
        statuses = await run_transfers(client, accounts)  # type: ignore[arg-type]
        assert statuses == {201: TRANSFER_COUNT}
        assert len(client.transfers) == TRANSFER_COUNT
        assert len({key for key, _payload in client.transfers}) == TRANSFER_COUNT
        currencies = {account_id: currency for account_id, currency in accounts}
        for _key, payload in client.transfers:
            assert payload["from_account"] != payload["to_account"]
            assert currencies[payload["from_account"]] == currencies[payload["to_account"]]
            assert 750 <= payload["amount_minor"] <= 42_500

    asyncio.run(run())


def test_wait_for_api_accepts_healthy_response() -> None:
    asyncio.run(demo.wait_for_api(_Client()))  # type: ignore[arg-type]


def test_wait_for_api_raises_after_health_check_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()

    async def unavailable(_path: str) -> _Response:
        response = _Response()
        response.status_code = 503
        return response

    async def no_wait(_seconds: int) -> None:
        return None

    monkeypatch.setattr(client, "get", unavailable)
    monkeypatch.setattr(demo.asyncio, "sleep", no_wait)
    with pytest.raises(RuntimeError, match="did not become healthy"):
        asyncio.run(demo.wait_for_api(client))  # type: ignore[arg-type]


def test_demo_transfer_failure_reports_api_response() -> None:
    async def run() -> None:
        client = _Client()
        client.transfer_status = 422
        accounts = [(index + 1, "USD" if index < 10 else "EUR") for index in range(20)]
        with pytest.raises(RuntimeError, match=r"Demo transfer failed \(422\): demo error"):
            await run_transfers(client, accounts)  # type: ignore[arg-type]

    asyncio.run(run())


def test_demo_main_seeds_and_disposes_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_seed(base_url: str) -> None:
        calls.append(base_url)

    async def fake_dispose() -> None:
        calls.append("disposed")

    class _Engine:
        async def dispose(self) -> None:
            await fake_dispose()

    monkeypatch.setattr(sys, "argv", ["app.demo", "--base-url", "http://demo.test"])
    monkeypatch.setattr(demo, "seed", fake_seed)
    monkeypatch.setattr(demo, "engine", _Engine())
    demo.main()
    assert calls == ["http://demo.test", "disposed"]


def test_funding_sets_the_account_opening_baseline() -> None:
    async def run() -> None:
        async with SessionLocal() as session:
            account = await AccountService(session).create(
                AccountCreate(owner_name="demo-funding-test", currency="USD")
            )
            account_id = account.id
        await demo.fund_accounts([account_id])
        async with SessionLocal() as session:
            funded_account = await session.get(Account, account_id)
            balance = await session.get(Balance, account_id)
        assert funded_account is not None
        assert funded_account.opening_balance_minor == demo.OPENING_BALANCE_MINOR
        assert balance is not None
        assert balance.balance_minor == demo.OPENING_BALANCE_MINOR

    asyncio.run(run())


def test_seed_orchestrates_api_calls_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _Client()
    monkeypatch.setattr(demo.httpx, "AsyncClient", lambda **_kwargs: client)

    async def no_funding(_account_ids: list[int]) -> None:
        return None

    monkeypatch.setattr(demo, "fund_accounts", no_funding)
    asyncio.run(demo.seed("http://demo.test"))
    summary = json.loads(capsys.readouterr().out)
    assert summary["accounts_created"] == ACCOUNT_COUNT
    assert summary["transfers_attempted"] == TRANSFER_COUNT
    assert summary["transfers_succeeded"] == TRANSFER_COUNT
