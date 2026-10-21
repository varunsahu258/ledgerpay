# Architecture decision records

## ADR 1: PostgreSQL is the source of truth

Use PostgreSQL 16 with SQLAlchemy's async engine and asyncpg. The application relies on row locks, JSONB, migration-managed constraints, and an append-only trigger; a lightweight SQLite substitute would not validate those behaviors.

## ADR 2: Keep a double-entry transfer ledger

Each successful transfer is one atomic operation with a negative debit and matching positive credit. The ledger trigger blocks updates and deletes. Reversals create a new compensating transfer, preserving the original history. Reconciliation checks opening balance plus entry sum for each account and verifies the global transfer-ledger sum is zero.

## ADR 3: Store money as integer minor units

Store amounts in signed 64-bit integers. This avoids floating-point rounding in transfer validation, balance updates, and reconciliation.

## ADR 4: Make retries safe and locks ordered

Require an idempotency key and persist a canonical request hash with the result. A unique constraint arbitrates simultaneous requests; matching retries replay the stored response and payload conflicts return 409. Transfer and reversal flows lock balance rows in ascending account ID order so opposite-direction requests cannot form a lock cycle.

## ADR 5: Make opening funds explicit

An account's nonnegative `opening_balance_minor` records initial external capital outside its peer-to-peer transfer entries. It defaults to zero; normal account creation cannot mint funds. Reconciliation uses the opening amount as the account's baseline. The demo seeder sets that baseline directly and writes an audit event before making transfers through the API. A production deployment should replace this demo bootstrap with a controlled funding/settlement workflow.

## ADR 6: Publish static API and test documentation

Export FastAPI's OpenAPI schema and render it with Redoc as static HTML. Publish the measured concurrency report as JSON, with a plain JavaScript results page, using GitHub Pages.
