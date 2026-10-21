from __future__ import annotations

import json
from typing import Any

import pytest

import app.reconcile as reconcile_cli


class _SessionContext:
    async def __aenter__(self) -> _SessionContext:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _EngineStub:
    async def dispose(self) -> None:
        return None


@pytest.mark.parametrize(
    ("report", "expected_exit"),
    [
        (
            {
                "account_mismatches": [],
                "global_ledger_sum_minor": 0,
                "global_sum_is_zero": True,
                "ok": True,
            },
            0,
        ),
        (
            {
                "account_mismatches": [{"account_id": 3}],
                "global_ledger_sum_minor": 7,
                "global_sum_is_zero": False,
                "ok": False,
            },
            1,
        ),
    ],
)
def test_reconcile_cli_prints_json_and_uses_nonzero_exit_for_mismatches(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    report: dict[str, Any],
    expected_exit: int,
) -> None:
    async def fake_reconcile(_session: object) -> dict[str, Any]:
        return report

    monkeypatch.setattr(reconcile_cli, "SessionLocal", _SessionContext)
    monkeypatch.setattr(reconcile_cli, "engine", _EngineStub())
    monkeypatch.setattr(reconcile_cli, "reconcile", fake_reconcile)

    with pytest.raises(SystemExit) as raised:
        reconcile_cli.main()

    assert raised.value.code == expected_exit
    assert json.loads(capsys.readouterr().out) == report
