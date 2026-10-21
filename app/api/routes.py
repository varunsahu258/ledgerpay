from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import get_session
from app.schemas.account import AccountCreate, AccountListItem, AccountPage, AccountRead
from app.schemas.transfer import ErrorBody, ReversalRead, TransferCreate, TransferRead
from app.services.accounts import AccountCapReached, AccountService
from app.services.reversals import ReversalService
from app.services.transactions import TransactionHistoryService, TransactionPage
from app.services.transfers import TransferService

router = APIRouter()


@router.post(
    "/accounts",
    response_model=AccountRead,
    status_code=201,
    summary="Create an account",
    description="Creates a zero-balance account. Currency is a three-letter uppercase code.",
    tags=["Accounts"],
)
async def create_account(
    payload: AccountCreate,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> AccountRead | JSONResponse:
    service = AccountService(session)
    try:
        if settings.demo_mode:
            account = await service.create_with_cap(
                payload, max_accounts=settings.demo_max_accounts
            )
        else:
            account = await service.create(payload)
    except AccountCapReached:
        return JSONResponse(
            status_code=429,
            content={
                "code": "demo_account_limit_reached",
                "message": "This public demo has reached its account limit",
            },
        )
    return AccountRead.model_validate(account)


@router.get(
    "/accounts",
    response_model=AccountPage,
    summary="List accounts",
    description=(
        "Returns accounts in ascending ID order with keyset pagination and current balances."
    ),
    tags=["Accounts"],
)
async def list_accounts(
    cursor: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    accounts, has_more = await AccountService(session).list(cursor=cursor, limit=limit)
    items = [
        AccountListItem.model_validate(
            {**AccountRead.model_validate(account).model_dump(), "balance_minor": balance}
        )
        for account, balance in accounts
    ]
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "next_cursor": items[-1].id if has_more and items else None,
    }


@router.get(
    "/accounts/{account_id}",
    response_model=AccountRead,
    summary="Get an account",
    tags=["Accounts"],
)
async def get_account(
    account_id: int,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> AccountRead:
    account = await AccountService(session).get(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return AccountRead.model_validate(account)


@router.get(
    "/accounts/{account_id}/transactions",
    response_model=TransactionPage,
    summary="List account ledger entries",
    description=(
        "Returns newest entries first using a ledger-entry ID cursor. Date bounds are inclusive."
    ),
    tags=["Ledger"],
)
async def list_account_transactions(
    account_id: int,
    cursor: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    start_date: date | None = None,
    end_date: date | None = None,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> JSONResponse:
    if start_date is not None and end_date is not None and start_date > end_date:
        return JSONResponse(
            status_code=422,
            content={
                "code": "invalid_date_range",
                "message": "start_date must not exceed end_date",
            },
        )
    page = await TransactionHistoryService(session).list_for_account(
        account_id,
        cursor=cursor,
        limit=limit,
        start_date=start_date,
        end_date=end_date,
    )
    if page is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return JSONResponse(content=page)


@router.post(
    "/transfers",
    responses={
        201: {
            "model": TransferRead,
            "description": "Transfer created or successful retry replayed.",
        },
        404: {"model": ErrorBody},
        409: {"model": ErrorBody, "description": "Idempotency key reused with another payload."},
        422: {"model": ErrorBody, "description": "Invalid transfer or insufficient funds."},
    },
    summary="Create an idempotent transfer",
    description=(
        "Moves integer minor units between same-currency accounts in one database transaction. "
        "Retries require the same Idempotency-Key and payload."
    ),
    tags=["Transfers"],
)
async def create_transfer(
    payload: TransferCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> JSONResponse:
    outcome = await TransferService(session).create(payload, idempotency_key)
    return JSONResponse(status_code=outcome.status_code, content=outcome.body)


@router.post(
    "/transfers/{transfer_id}/reverse",
    responses={
        201: {"model": ReversalRead, "description": "Reversal transfer created or replayed."},
        404: {"model": ErrorBody},
        409: {"model": ErrorBody, "description": "Transfer already reversed or key reused."},
        422: {"model": ErrorBody, "description": "Reversal cannot be funded."},
    },
    summary="Reverse a transfer",
    description=(
        "Creates a new opposite transfer linked to the original; ledger history is never edited."
    ),
    tags=["Transfers"],
)
async def reverse_transfer(
    transfer_id: UUID,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> JSONResponse:
    outcome = await ReversalService(session).reverse(transfer_id, idempotency_key)
    return JSONResponse(status_code=outcome.status_code, content=outcome.body)
