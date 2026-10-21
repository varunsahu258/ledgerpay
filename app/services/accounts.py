from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Account, Balance
from app.schemas.account import AccountCreate


class AccountCapReached(Exception):
    """Raised when demo-mode account creation reaches its configured hard cap."""


class AccountService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payload: AccountCreate) -> Account:
        account = Account(owner_name=payload.owner_name.strip(), currency=payload.currency)
        self.session.add(account)
        await self.session.flush()
        self.session.add(Balance(account_id=account.id, balance_minor=0, version=1))
        await self.session.commit()
        await self.session.refresh(account)
        return account

    async def create_with_cap(self, payload: AccountCreate, *, max_accounts: int) -> Account:
        """Atomically enforce a global account cap for a public demo instance."""
        async with self.session.begin():
            # Serialize cap checks across app workers and hosts sharing this PostgreSQL DB.
            await self.session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": 1279348817}
            )
            count = await self.session.scalar(select(func.count()).select_from(Account))
            if count is not None and count >= max_accounts:
                raise AccountCapReached
            account = Account(owner_name=payload.owner_name.strip(), currency=payload.currency)
            self.session.add(account)
            await self.session.flush()
            self.session.add(Balance(account_id=account.id, balance_minor=0, version=1))
        await self.session.refresh(account)
        return account

    async def get(self, account_id: int) -> Account | None:
        result = await self.session.execute(select(Account).where(Account.id == account_id))
        return result.scalar_one_or_none()

    async def list(
        self, *, cursor: int | None, limit: int
    ) -> tuple[list[tuple[Account, int]], bool]:
        statement = (
            select(Account, Balance.balance_minor)
            .join(Balance, Balance.account_id == Account.id)
            .order_by(Account.id)
            .limit(limit + 1)
        )
        if cursor is not None:
            statement = statement.where(Account.id > cursor)
        result = await self.session.execute(statement)
        rows = list(result.all())
        return [(account, balance) for account, balance in rows[:limit]], len(rows) > limit
