import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AuditLog, LedgerEntry, Transfer
from app.services.balance_locking import ordered_balance_lock_query


@dataclass(frozen=True)
class ReversalOutcome:
    status_code: int
    body: dict[str, object]


def _hash(original_id: uuid.UUID) -> str:
    payload = json.dumps(
        {"operation": "reverse", "transfer_id": str(original_id)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _error(status: int, code: str, message: str) -> ReversalOutcome:
    return ReversalOutcome(status, {"code": code, "message": message})


class ReversalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reverse(self, original_id: uuid.UUID, idempotency_key: str) -> ReversalOutcome:
        digest = _hash(original_id)
        async with self.session.begin():
            # A retry can replay even after the original is no longer independently reversible.
            existing = await self._by_key(idempotency_key)
            if existing is not None:
                return self._replay(existing, digest)

            original = await self.session.scalar(
                select(Transfer).where(Transfer.id == original_id).with_for_update()
            )
            if original is None:
                return _error(404, "transfer_not_found", "Transfer not found")

            # Serialize all reversal attempts on the original transfer, then recheck the key in
            # case a concurrent request with this key completed while this transaction waited.
            existing = await self._by_key(idempotency_key)
            if existing is not None:
                return self._replay(existing, digest)
            if original.status != "completed" or original.reversal_of is not None:
                return _error(
                    409,
                    "transfer_not_reversible",
                    "Only completed original transfers can be reversed",
                )
            prior_reversal = await self.session.scalar(
                select(Transfer).where(Transfer.reversal_of == original_id)
            )
            if prior_reversal is not None:
                return _error(409, "already_reversed", "Transfer has already been reversed")

            reversal_id = uuid.uuid4()
            inserted_id = await self.session.scalar(
                insert(Transfer)
                .values(
                    id=reversal_id,
                    idempotency_key=idempotency_key,
                    from_account=original.to_account,
                    to_account=original.from_account,
                    amount_minor=original.amount_minor,
                    status="processing",
                    request_hash=digest,
                    reversal_of=original_id,
                )
                .on_conflict_do_nothing()
                .returning(Transfer.id)
            )
            if inserted_id is None:
                existing = await self._by_key(idempotency_key)
                if existing is not None:
                    return self._replay(existing, digest)
                return _error(409, "already_reversed", "Transfer has already been reversed")

            account_ids = [original.from_account, original.to_account]
            locked = (await self.session.execute(ordered_balance_lock_query(account_ids))).all()
            balances = {balance.account_id: balance for balance, _currency in locked}
            if len(balances) != 2:
                outcome = _error(404, "account_not_found", "One or both accounts do not exist")
                await self._save_failure(reversal_id, outcome)
                return outcome

            reversal_source = balances[original.to_account]
            reversal_destination = balances[original.from_account]
            if reversal_source.balance_minor < original.amount_minor:
                outcome = _error(
                    422, "insufficient_funds", "Insufficient funds to reverse transfer"
                )
                await self._save_failure(reversal_id, outcome)
                return outcome

            reversal_source.balance_minor -= original.amount_minor
            reversal_source.version += 1
            reversal_destination.balance_minor += original.amount_minor
            reversal_destination.version += 1
            self.session.add_all(
                [
                    LedgerEntry(
                        transfer_id=reversal_id,
                        account_id=original.to_account,
                        amount_minor=-original.amount_minor,
                    ),
                    LedgerEntry(
                        transfer_id=reversal_id,
                        account_id=original.from_account,
                        amount_minor=original.amount_minor,
                    ),
                    AuditLog(
                        actor="api",
                        action="transfer.reversed",
                        entity="transfer",
                        entity_id=str(reversal_id),
                        detail={
                            "reversal_of": str(original_id),
                            "from_account": original.to_account,
                            "to_account": original.from_account,
                            "amount_minor": original.amount_minor,
                        },
                    ),
                ]
            )
            await self.session.flush()
            body: dict[str, object] = {
                "id": str(reversal_id),
                "reversal_of": str(original_id),
                "from_account": original.to_account,
                "to_account": original.from_account,
                "amount_minor": original.amount_minor,
                "status": "completed",
            }
            outcome = ReversalOutcome(201, body)
            await self.session.execute(
                update(Transfer)
                .where(Transfer.id == reversal_id)
                .values(
                    status="completed",
                    response_status=outcome.status_code,
                    response_body=body,
                )
            )
            return outcome

    async def _by_key(self, key: str) -> Transfer | None:
        result = await self.session.execute(select(Transfer).where(Transfer.idempotency_key == key))
        return result.scalar_one_or_none()

    @staticmethod
    def _replay(existing: Transfer, digest: str) -> ReversalOutcome:
        if existing.request_hash != digest:
            return _error(
                409,
                "idempotency_key_reused",
                "Idempotency-Key was used with a different request",
            )
        if existing.response_status is None or existing.response_body is None:
            return _error(409, "reversal_in_progress", "Reversal request is still in progress")
        return ReversalOutcome(existing.response_status, existing.response_body)

    async def _save_failure(self, transfer_id: uuid.UUID, outcome: ReversalOutcome) -> None:
        await self.session.execute(
            update(Transfer)
            .where(Transfer.id == transfer_id)
            .values(
                status="failed",
                response_status=outcome.status_code,
                response_body=outcome.body,
            )
        )
