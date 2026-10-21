from datetime import UTC, date, datetime, time, timedelta

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Account, LedgerEntry, Transfer


class TransactionRead(BaseModel):
    id: int
    transfer_id: str
    from_account: int
    to_account: int
    amount_minor: int
    created_at: datetime
    transfer_status: str
    reversal_of: str | None


class TransactionPage(BaseModel):
    items: list[TransactionRead]
    next_cursor: int | None
    has_more: bool


class TransactionHistoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_account(
        self,
        account_id: int,
        *,
        cursor: int | None = None,
        limit: int = 50,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, object] | None:
        account = await self.session.get(Account, account_id)
        if account is None:
            return None
        statement = (
            select(LedgerEntry, Transfer)
            .join(Transfer, Transfer.id == LedgerEntry.transfer_id)
            .where(LedgerEntry.account_id == account_id)
        )
        if cursor is not None:
            statement = statement.where(LedgerEntry.id < cursor)
        if start_date is not None:
            statement = statement.where(
                LedgerEntry.created_at >= datetime.combine(start_date, time.min, tzinfo=UTC)
            )
        if end_date is not None:
            exclusive_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
            statement = statement.where(LedgerEntry.created_at < exclusive_end)
        rows = (
            await self.session.execute(statement.order_by(LedgerEntry.id.desc()).limit(limit + 1))
        ).all()
        has_more = len(rows) > limit
        page = rows[:limit]
        items: list[dict[str, object]] = [
            {
                "id": entry.id,
                "transfer_id": str(transfer.id),
                "from_account": transfer.from_account,
                "to_account": transfer.to_account,
                "amount_minor": entry.amount_minor,
                "created_at": entry.created_at.isoformat(),
                "transfer_status": transfer.status,
                "reversal_of": str(transfer.reversal_of) if transfer.reversal_of else None,
            }
            for entry, transfer in page
        ]
        return {
            "items": items,
            "next_cursor": items[-1]["id"] if has_more and items else None,
            "has_more": has_more,
        }
