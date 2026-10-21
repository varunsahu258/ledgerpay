from sqlalchemy.dialects import postgresql

from app.schemas.transfer import TransferCreate
from app.services.balance_locking import ordered_balance_lock_query
from app.services.transfers import request_hash


def test_transfer_request_hash_is_stable_and_payload_sensitive() -> None:
    first = TransferCreate(from_account=10, to_account=20, amount_minor=500)
    same = TransferCreate(from_account=10, to_account=20, amount_minor=500)
    different = TransferCreate(from_account=10, to_account=20, amount_minor=501)

    assert request_hash(first) == request_hash(same)
    assert request_hash(first) != request_hash(different)


def test_balance_lock_query_orders_rows_before_for_update() -> None:
    sql = str(ordered_balance_lock_query([20, 10]).compile(dialect=postgresql.dialect()))

    order_by = sql.index("ORDER BY balances.account_id ASC")
    for_update = sql.index("FOR UPDATE OF balances")
    assert order_by < for_update
