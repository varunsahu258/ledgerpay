import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Account, AuditLog, LedgerEntry, Transfer
from app.schemas.transfer import TransferCreate
from app.services.balance_locking import ordered_balance_lock_query


@dataclass(frozen=True)
class TransferOutcome:
    status_code: int
    body: dict[str, object]


def request_hash(payload: TransferCreate) -> str:
    serialized = json.dumps(
        payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


def error_outcome(status_code: int, code: str, message: str) -> TransferOutcome:
    return TransferOutcome(status_code, {"code": code, "message": message})


class TransferService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payload: TransferCreate, idempotency_key: str) -> TransferOutcome:
        if payload.from_account == payload.to_account:
            return error_outcome(422, "same_account", "Source and destination must differ")

        digest = request_hash(payload)
        transfer_id = uuid.uuid4()
        async with self.session.begin():
            existing_accounts = await self.session.scalars(
                select(Account.id).where(Account.id.in_([payload.from_account, payload.to_account]))
            )
            if len(existing_accounts.all()) != 2:
                return error_outcome(404, "account_not_found", "One or both accounts do not exist")

            inserted_id = await self.session.scalar(
                insert(Transfer)
                .values(
                    id=transfer_id,
                    idempotency_key=idempotency_key,
                    from_account=payload.from_account,
                    to_account=payload.to_account,
                    amount_minor=payload.amount_minor,
                    status="processing",
                    request_hash=digest,
                )
                .on_conflict_do_nothing(index_elements=[Transfer.idempotency_key])
                .returning(Transfer.id)
            )

            if inserted_id is None:
                existing = await self.session.scalar(
                    select(Transfer).where(Transfer.idempotency_key == idempotency_key)
                )
                assert existing is not None, "conflicting idempotency row should be visible"
                if existing.request_hash != digest:
                    return error_outcome(
                        409,
                        "idempotency_key_reused",
                        "Idempotency-Key was used with a different request",
                    )
                assert existing.response_status is not None and existing.response_body is not None
                return TransferOutcome(existing.response_status, existing.response_body)

            balances = (
                await self.session.execute(
                    ordered_balance_lock_query([payload.from_account, payload.to_account])
                )
            ).all()
            by_account = {balance.account_id: (balance, currency) for balance, currency in balances}

            if len(by_account) != 2:
                outcome = error_outcome(
                    404, "account_not_found", "One or both accounts do not exist"
                )
                await self._save_failure(transfer_id, "failed", outcome)
                return outcome

            source, source_currency = by_account[payload.from_account]
            destination, destination_currency = by_account[payload.to_account]
            if source_currency != destination_currency:
                outcome = error_outcome(
                    422, "currency_mismatch", "Transfers require accounts with the same currency"
                )
                await self._save_failure(transfer_id, "failed", outcome)
                return outcome
            if source.balance_minor < payload.amount_minor:
                outcome = error_outcome(422, "insufficient_funds", "Insufficient funds")
                await self._save_failure(transfer_id, "failed", outcome)
                return outcome

            now_transfer = await self.session.scalar(
                select(Transfer).where(Transfer.id == transfer_id)
            )
            assert now_transfer is not None
            source.balance_minor -= payload.amount_minor
            source.version += 1
            destination.balance_minor += payload.amount_minor
            destination.version += 1
            self.session.add_all(
                [
                    LedgerEntry(
                        transfer_id=transfer_id,
                        account_id=payload.from_account,
                        amount_minor=-payload.amount_minor,
                    ),
                    LedgerEntry(
                        transfer_id=transfer_id,
                        account_id=payload.to_account,
                        amount_minor=payload.amount_minor,
                    ),
                    AuditLog(
                        actor="api",
                        action="transfer.completed",
                        entity="transfer",
                        entity_id=str(transfer_id),
                        detail={
                            "from_account": payload.from_account,
                            "to_account": payload.to_account,
                            "amount_minor": payload.amount_minor,
                            "currency": source_currency,
                        },
                    ),
                ]
            )
            await self.session.flush()
            await self.session.execute(
                update(Transfer).where(Transfer.id == transfer_id).values(status="completed")
            )
            body: dict[str, object] = {
                "id": str(transfer_id),
                "from_account": payload.from_account,
                "to_account": payload.to_account,
                "amount_minor": payload.amount_minor,
                "status": "completed",
                "created_at": now_transfer.created_at.isoformat(),
            }
            outcome = TransferOutcome(201, body)
            await self.session.execute(
                update(Transfer)
                .where(Transfer.id == transfer_id)
                .values(
                    response_status=outcome.status_code,
                    response_body=body,
                )
            )
            return outcome

    async def _save_failure(
        self, transfer_id: uuid.UUID, status: str, outcome: TransferOutcome
    ) -> None:
        await self.session.execute(
            update(Transfer)
            .where(Transfer.id == transfer_id)
            .values(
                status=status,
                response_status=outcome.status_code,
                response_body=outcome.body,
            )
        )
