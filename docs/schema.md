# LedgerPay schema

All monetary values are integer minor units (for example, cents). `accounts.currency` identifies
the currency for those units. A transfer links two accounts and is uniquely identified by its
idempotency key. A reversal is a new transfer with `reversal_of` pointing to the original; a
unique constraint allows at most one reversal per transfer. Each transfer can produce debit and
credit rows in `ledger_entries`; a debit is
negative and a credit is positive. Ledger rows are append-only: PostgreSQL rejects `UPDATE` and
`DELETE` through a row trigger. `balances` stores the current nonnegative balance and a version for
optimistic concurrency. `accounts.opening_balance_minor` records externally supplied starting
capital and defaults to zero; reconciliation compares `balances` with this baseline plus ledger
entries. The demo-only bootstrap updates this baseline and records an audit event. `audit_log.detail`
stores structured JSON metadata.

```mermaid
erDiagram
    ACCOUNTS ||--o{ TRANSFERS : "from_account"
    ACCOUNTS ||--o{ TRANSFERS : "to_account"
    TRANSFERS o|--o| TRANSFERS : reverses
    TRANSFERS ||--o{ LEDGER_ENTRIES : records
    ACCOUNTS ||--o{ LEDGER_ENTRIES : owns
    ACCOUNTS ||--o| BALANCES : has

    ACCOUNTS {
        bigint id PK
        varchar owner_name
        varchar currency "3 uppercase letters"
        bigint opening_balance_minor "CHECK >= 0, external baseline"
        timestamptz created_at
    }
    TRANSFERS {
        uuid id PK
        text idempotency_key UK
        uuid reversal_of FK, UK
        bigint from_account FK
        bigint to_account FK
        bigint amount_minor "CHECK > 0"
        varchar status
        timestamptz created_at
    }
    LEDGER_ENTRIES {
        bigint id PK
        uuid transfer_id FK
        bigint account_id FK
        bigint amount_minor "debit < 0, credit > 0"
        timestamptz created_at
    }
    BALANCES {
        bigint account_id PK, FK
        bigint balance_minor "CHECK >= 0"
        int version
    }
    AUDIT_LOG {
        bigint id PK
        text actor
        text action
        text entity
        text entity_id
        jsonb detail
        timestamptz at
    }
```
