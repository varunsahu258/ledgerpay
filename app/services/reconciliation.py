from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Account, Balance, LedgerEntry


class AccountMismatch(TypedDict):
    account_id: int
    ledger_balance_minor: int
    stored_balance_minor: int | None


class ReconciliationReport(TypedDict):
    account_mismatches: list[AccountMismatch]
    global_ledger_sum_minor: int
    global_sum_is_zero: bool
    ok: bool


async def reconcile(session: AsyncSession) -> ReconciliationReport:
    expected_rows = (
        await session.execute(
            select(
                Account.id,
                Account.opening_balance_minor
                + func.coalesce(func.sum(LedgerEntry.amount_minor), 0),
                Balance.balance_minor,
            )
            .outerjoin(LedgerEntry, LedgerEntry.account_id == Account.id)
            .outerjoin(Balance, Balance.account_id == Account.id)
            .group_by(Account.id, Balance.balance_minor)
            .order_by(Account.id)
        )
    ).all()
    mismatches: list[AccountMismatch] = []
    for account_id, ledger_balance, stored_balance in expected_rows:
        if stored_balance is None or int(ledger_balance) != stored_balance:
            mismatches.append(
                {
                    "account_id": account_id,
                    "ledger_balance_minor": int(ledger_balance),
                    "stored_balance_minor": stored_balance,
                }
            )

    global_sum = await session.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_minor), 0)))
    total = int(global_sum or 0)
    zero_sum = total == 0
    return {
        "account_mismatches": mismatches,
        "global_ledger_sum_minor": total,
        "global_sum_is_zero": zero_sum,
        "ok": not mismatches and zero_sum,
    }
