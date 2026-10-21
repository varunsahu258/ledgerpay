from collections.abc import Sequence

from sqlalchemy import Select, select

from app.models.entities import Account, Balance


def ordered_balance_lock_query(
    account_ids: Sequence[int],
) -> Select[tuple[Balance, str]]:
    """Lock the requested balances in one globally consistent account ID order."""
    return (
        select(Balance, Account.currency)
        .join(Account, Account.id == Balance.account_id)
        .where(Balance.account_id.in_(account_ids))
        .order_by(Balance.account_id.asc())
        .with_for_update(of=Balance)
    )
