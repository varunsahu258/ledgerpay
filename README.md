# LedgerPay

LedgerPay is a Python 3.12 showcase for an auditable money-transfer API: double-entry accounting, idempotent retries, ordered database locks, immutable ledger history, and balance reconciliation, with a browser console and generated API reference.

[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/OWNER/REPO/actions/workflows/ci.yml) · [Browser console](http://localhost:8000/console/) (after starting the demo) · [OpenAPI reference](site/) · [Measured concurrency report](site/results.html)

## What is included

| Capability | What it does |
| --- | --- |
| Browser console | Create accounts, view balances, submit transfers, inspect ledger history, filter by date, and request reversals. |
| Account API | Create and retrieve accounts; list them with keyset pagination and current materialized balances. |
| Transfer API | Move integer minor units between same-currency accounts in one PostgreSQL transaction. |
| Idempotency | Stores the request hash and response for each key, so a retry replays the original status and body. |
| Double-entry history | Each completed transfer adds a debit and a matching credit; PostgreSQL blocks ledger updates and deletes. |
| Reversals | A reversal is a new linked transfer with opposite entries; each completed transfer can be reversed once. |
| Reconciliation | Recomputes every balance from opening capital plus ledger entries, and checks the global ledger sum. |
| Demo data | Creates 20 accounts and submits 500 realistic transfer requests through the HTTP API. |
| Static docs | `openapi.json`, a Redoc reference, and a concurrency results page are assembled under `site/`. |
| Automated checks | Ruff, mypy, PostgreSQL migrations, pytest, Hypothesis, asyncio concurrency checks, and an 85% coverage floor. |

## Live demo

- **Live console:** `<LIVE_CONSOLE_URL>` (replace with the deployed `/console/` URL before publishing).
- **GitHub Pages:** `<PAGES_URL>` (replace with this repository's Pages URL).
- **Demo preview:**

![LedgerPay demo preview placeholder](docs/demo.gif)

The GIF is a labeled preview placeholder; replace it with a short recording of the live console when
the public deployment is available.

## Start in three commands

Requirements: macOS/Linux, Docker Desktop with its engine running, `uv`, and Python 3.12 (uv can install it). From this repository directory:

```sh
uv sync --python 3.12 --all-groups
make demo
make site
```

Then open these local pages:

| URL | What you see |
| --- | --- |
| [http://localhost:8000/console/](http://localhost:8000/console/) | Interactive LedgerPay browser console |
| [http://localhost:8000/docs](http://localhost:8000/docs) | Swagger UI; execute API requests from the browser |
| [http://localhost:8000/redoc](http://localhost:8000/redoc) | FastAPI's live Redoc view |
| [http://localhost:8000/health](http://localhost:8000/health) | API and database health check |
| [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json) | Live OpenAPI JSON |
| [http://localhost:8080/](http://localhost:8080/) | Generated static Redoc page, if you start the optional static server below |
| [http://localhost:8080/results.html](http://localhost:8080/results.html) | Static concurrency report and chart |

`make demo` starts PostgreSQL 16 and waits for its health check before running migrations, builds and starts the API container, then calls the real API to seed 20 accounts and 500 transfers. It prints a demo summary. The seeded starting funds are recorded as external opening capital; the 500 transfers themselves use the normal transfer endpoint. Re-running the seed adds more demo records; it does not reset the database. `make migrate` also waits for the Compose database to become healthy before connecting.

## Public demo deployment

Public-demo protections are off by default. Set `DEMO_MODE=true` to enable a sliding-window write
limit per client IP on account creation, transfers, and reversals, plus an atomic PostgreSQL-backed
cap on total accounts. Configure the request count/window and account cap with
`DEMO_RATE_LIMIT_REQUESTS`, `DEMO_RATE_LIMIT_WINDOW_SECONDS`, and `DEMO_MAX_ACCOUNTS`. The limiter
is intentionally process-local and suitable only as a lightweight showcase safeguard.

For demo seeding/reset, configure a private random `DEMO_SEED_TOKEN`; seeder requests with the
matching `X-Demo-Seed-Token` bypass the public rate counter. `scripts/reset_demo.py` truncates and
recreates **all** LedgerPay data, so it refuses to run unless `DEMO_MODE=true`,
`DEMO_RESET_ENABLED=true`, and a seed token are set. Schedule it only for a dedicated disposable
demo database. `DEMO_API_BASE_URL` supplies its default target API. See [docs/DEPLOY.md](docs/DEPLOY.md)
for Render + Neon setup, environment values, initial seeding, and a cron example.

To serve the generated static documentation locally after `make site`, run this in another terminal:

```sh
python3 -m http.server 8080 --directory site
```

The console is served by FastAPI at `/console/`, so its requests go to the same API origin and do not need a separate frontend server or CORS setup.

## Run manually

If you want an empty database rather than the demo dataset:

```sh
uv sync --python 3.12 --all-groups
cp .env.example .env    # only needed if you want to edit the default local settings
docker compose up -d db
make migrate
make run
```

`make run` serves the app on `http://localhost:8000` with reload enabled. The Compose database credentials are `ledgerpay` / `ledgerpay`, database `ledgerpay`, on port `5432`. In a separate terminal, use `make test` and `make lint` as described below. The container API uses the Compose network hostname `db`; a locally run API reads `DATABASE_URL` from `.env` and should use `localhost`.

Useful service commands:

```sh
docker compose ps                         # container state
docker compose logs -f db                 # PostgreSQL logs
docker compose logs -f api                # API container logs
docker compose down                       # stop services; keep the named database volume
docker compose down -v                    # stop services and delete database data
```

On macOS, if `docker compose up -d db` hangs, first open Docker Desktop and wait until it reports that the engine is running. Check `docker info` (the output must include a Server section) and `docker context show` (normally `desktop-linux` for Docker Desktop). If the client hangs before showing server details, the API project has not reached PostgreSQL yet; this is a Docker engine startup issue. After the engine is ready, retry `docker compose up -d db`, then check `docker compose ps` and `docker compose logs db`.

## Browser console walkthrough

1. Start the API with `make demo` or `make run` after starting the database and applying migrations.
2. Open [http://localhost:8000/console/](http://localhost:8000/console/). The connection indicator confirms whether `/health` can reach PostgreSQL.
3. Use **New account** to create a zero-balance account, or choose a seeded account. The account table lists its current balance in integer minor units.
4. Select source and destination, enter a positive integer amount, and send. The console supplies a UUID idempotency key. Retrying the same HTTP request with the same key returns the saved response; use **New key** for a different operation.
5. Choose an account under **Account activity** to load ledger entries. Start and end dates are inclusive calendar dates; older entries load by cursor. Use **Reverse transfer** to create a linked, opposite transfer. A reversal may fail if the recipient no longer has enough money.

The browser console displays API error messages such as `insufficient_funds`, `currency_mismatch`, `same_account`, or `already_reversed`. It never calls an external payment processor.

## API reference

FastAPI publishes an interactive Swagger UI at `/docs`, ReDoc at `/redoc`, and its OpenAPI 3 schema at `/openapi.json`. The checked-in static reference is regenerated by `make site`. The static page loads the Redoc bundle from a CDN, so an internet connection is needed to render that page; `openapi.json` itself is local and can be imported into Swagger Editor, Postman, or other OpenAPI tooling.

All API failures use a JSON body shaped like `{"code":"...","message":"..."}`. FastAPI request validation returns HTTP 422 with `validation_error`. Routes that require an idempotency key require the `Idempotency-Key` header (1 to 255 characters).

| Method and path | Success | Behavior |
| --- | --- | --- |
| `GET /health` | `200` | Executes `SELECT 1` against PostgreSQL; returns `{"status":"ok"}`. |
| `POST /accounts` | `201` | JSON `{"owner_name":"Ada Lovelace","currency":"USD"}`. Creates a zero-balance account. Currency is three uppercase letters. |
| `GET /accounts` | `200` | Query: `cursor` (exclusive account ID) and `limit` (1–100, default 50). Returns `{items:[...],next_cursor}`; each item includes `balance_minor`. |
| `GET /accounts/{id}` | `200` | Retrieves the account's identity, currency, and creation time. |
| `GET /accounts/{id}/transactions` | `200` | Query: `cursor` (ledger entry ID), `limit` (1–100, default 50), `start_date`, `end_date`. Returns newest entries first and a `next_cursor`. |
| `POST /transfers` | `201` | Requires `Idempotency-Key`. JSON: `{"from_account":1,"to_account":2,"amount_minor":1250}`. Creates an atomic transfer. |
| `POST /transfers/{uuid}/reverse` | `201` | Requires `Idempotency-Key`. Creates a new opposite transfer linked to the original. |

Common business responses include `404 account_not_found`, `404 transfer_not_found`, `409 idempotency_key_reused`, `409 already_reversed`, `422 insufficient_funds`, `422 currency_mismatch`, and `422 same_account`. A repeated request with the same key and payload returns the original stored status and response body, including a previously stored business failure. Reusing the key for a different payload returns `409`.

Example requests (replace account IDs with IDs returned by the create/list API):

```sh
curl -s http://localhost:8000/health
curl -s -X POST http://localhost:8000/accounts \
  -H 'Content-Type: application/json' \
  -d '{"owner_name":"Ada Lovelace","currency":"USD"}'
curl -s -X POST http://localhost:8000/transfers \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: example-transfer-001' \
  -d '{"from_account":1,"to_account":2,"amount_minor":1250}'
curl -s 'http://localhost:8000/accounts?limit=20'
curl -s 'http://localhost:8000/accounts/1/transactions?limit=25&start_date=2026-01-01'
```

A completed transfer response contains `id`, `from_account`, `to_account`, `amount_minor`, `status`, and `created_at`. A reversal response also includes `reversal_of`. Do not assume account IDs start at 1 if you have reused a database.

## How a transfer works

1. The API validates the payload and rejects a same-account transfer. Inside a database transaction, it confirms the referenced accounts exist.
2. It attempts to insert a `transfers` row with `ON CONFLICT DO NOTHING` on the unique idempotency key. If another request already claimed that key, the API compares request hashes and either returns its saved result or reports key reuse with a different payload.
3. It locks both balance rows in ascending `account_id` order. Every transfer asks for locks in that same order, including opposite-direction transfers. This prevents a circular wait: one request cannot hold account A while waiting for B as another holds B while waiting for A.
4. It checks currency equality and available funds. A business failure is saved against the idempotency key so retries replay the same response.
5. For a successful transfer, it writes one negative debit and one positive credit, changes the two materialized balances and versions, writes an audit event, stores the response, and commits the transaction. PostgreSQL makes all of these visible together or rolls them all back.

A unique idempotency constraint is the arbiter when identical requests arrive at once: at most one insert claims a key. Other transactions wait for that insert to commit or roll back. After commit, a competing request reads the stored hash and response, so only one transfer and one pair of ledger entries are created for that key.

## Data model and accounting

See [docs/schema.md](docs/schema.md) for the ER diagram. The core tables are:

| Table | Purpose and important rules |
| --- | --- |
| `accounts` | Account owner, three-letter currency, timestamp, and nonnegative `opening_balance_minor` baseline. |
| `transfers` | One request/operation: UUID, unique idempotency key, source/destination, positive amount, status, request hash, stored response, optional `reversal_of`. The unique reversal link permits one reversal per original. |
| `ledger_entries` | Immutable signed postings linked to a transfer and account. Debits are negative, credits positive. PostgreSQL triggers reject `UPDATE` and `DELETE`. |
| `balances` | Current nonnegative materialized balance and version, one row per account. Updated while its row lock is held. |
| `audit_log` | Actor, action, entity reference, structured JSONB details, and timestamp. |

Every money amount is a PostgreSQL integer minor unit, such as cents or paise. No floating-point amount is accepted. The currency is attached to the account; cross-currency conversion is outside this service. `opening_balance_minor` represents capital that existed before this service's transfer history; demo setup updates this baseline and logs the bootstrap event.

The invariant for an account is `balances.balance_minor = accounts.opening_balance_minor + SUM(ledger_entries.amount_minor)`. For each transfer the debit plus credit is zero, so the global ledger sum stays zero. Reconciliation checks both properties. Run it with:

```sh
uv run python -m app.reconcile
```

It prints a JSON report of balance and global-sum mismatches and exits nonzero when any check fails. It uses the `DATABASE_URL` from environment or `.env`.

The ledger is intentionally append-only: a correction is represented by a new compensating transfer, not by changing old rows. To check the database trigger manually:

```sh
docker compose exec db psql -U ledgerpay -d ledgerpay
-- At the psql prompt (use an existing ledger entry ID):
UPDATE ledger_entries SET amount_minor = amount_minor WHERE id = 1;
-- PostgreSQL should reject the update because ledger history is append-only.
```

## Architecture

```mermaid
flowchart LR
    Browser[Browser console] -->|HTTP JSON| API[FastAPI routes]
    Client[CLI or API client] --> API
    API --> Services[Account, transfer, reversal, history, reconciliation]
    Services --> ORM[SQLAlchemy 2 async repositories]
    ORM --> DB[(PostgreSQL 16)]
    DB --> Ledger[Append-only double-entry ledger]
    Services --> Audit[Audit log]
    CI[GitHub Actions] --> Checks[Ruff, mypy, Alembic, pytest]
    Pages[Pages workflow] --> Static[Redoc and concurrency results]
```

The code is organized by responsibility:

```text
app/
  api/             FastAPI routes and HTTP validation
  core/            environment-backed settings
  models/          SQLAlchemy table mappings
  repositories/    database access helpers
  schemas/         Pydantic request and response models
  services/        transfer, reversal, account, history, reconciliation logic
  static/console/  same-origin browser console
  db.py            async engine and session dependency
  demo.py          HTTP-driven demo seeder
  reconcile.py     JSON reconciliation CLI
alembic/           versioned schema migrations and append-only trigger
site/              generated OpenAPI export, Redoc index, results page and data
scripts/           static site/OpenAPI build
 tests/             unit, integration, property, and concurrency suite
```

## Development and verification

```sh
make db-up       # start PostgreSQL and wait until its health check passes
make migrate     # wait for PostgreSQL, then apply Alembic migrations
make run         # run local Uvicorn with reload
make test        # migrate, run pytest, and enforce at least 85% coverage
make lint        # Ruff checks, Ruff format verification, and strict mypy
make site        # export OpenAPI and assemble the static Pages artifact
make demo        # start the Compose database/API and seed through HTTP
```

The test suite includes account API tests, transfer/reversal integration tests against PostgreSQL, unit tests, Hypothesis-generated sequences with retries and invalid operations, reconciliation corruption detection, and an `asyncio.gather` concurrency workload with 200 workers transferring across 10 accounts. Its invariants include no negative balances, per-account reconciliation, zero global ledger sum, and unchanged aggregate money. The concurrency test writes its measured outcome to [`tests/results/invariants.json`](tests/results/invariants.json), including attempts, successes, rejections, and violation count. `site/results.html` visualizes the copied report. A report marked `not_run_locally` means a passing concurrency workload has not yet been recorded for that checkout; run the PostgreSQL-backed suite to refresh it.

`make test` expects a reachable PostgreSQL database. Compose credentials and port defaults are in [docker-compose.yml](docker-compose.yml); local environment variables can be set in `.env` based on [.env.example](.env.example). `make lint` does not need a database. CI runs the same format/lint/type/migration/test gates against a PostgreSQL 16 service.

## Documentation and GitHub Pages

`make site` regenerates the root `openapi.json`, `site/openapi.json`, and the site copy of the measured concurrency report. The Pages workflow builds and deploys the `site/` directory on pushes to `main` and on manual dispatch. Configure the target GitHub repository's Pages source as **GitHub Actions**. The workflow can publish static docs and results; the interactive console requires the running FastAPI service and is therefore available locally at `/console/`.

## Design decisions

- **Double-entry over balance-only writes:** an auditable pair of postings provides a durable explanation of each balance change and supports full reconciliation.
- **Idempotency key plus payload hash:** a database uniqueness constraint arbitrates concurrent duplicate requests; the hash distinguishes a safe retry from accidental key reuse.
- **Ascending lock order:** all transfers request balance locks in the same global order, avoiding deadlocks between opposite-direction transfers.
- **Integer minor units:** signed integer arithmetic is exact and predictable; currency precision is not inferred from binary floating-point values.
- **Append-only ledger:** database enforcement preserves history; reversals and corrections add linked entries.
- **PostgreSQL-specific database:** asyncpg, JSONB, row locks, conflict handling, and trigger functions are central to the behavior, so SQLite is not a drop-in substitute.

## Configuration

| Setting | Default / example | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://ledgerpay:ledgerpay@localhost:5432/ledgerpay` | Async SQLAlchemy database URL for local Uvicorn and CLI commands. |
| Compose API URL | `postgresql+asyncpg://ledgerpay:ledgerpay@db:5432/ledgerpay` | Compose-internal database connection used by the API container. |
| `POSTGRES_USER` | `ledgerpay` | Compose database initialization user. |
| `POSTGRES_PASSWORD` | `ledgerpay` | Compose database initialization password; change for non-demo use. |
| `POSTGRES_DB` | `ledgerpay` | Compose database name. |

Compose initializes the database password only when creating its data volume. If you change the environment credentials after initialization, they do not rewrite the existing PostgreSQL role password. For this disposable demo, `docker compose down -v` removes the volume so it can be recreated; this permanently deletes local database data.

## Limitations

- This is an educational showcase, not a production banking or payment system. It has no authentication, authorization, tenant boundaries, rate limits, operational alerting, or secrets management.
- No external processor, deposits, withdrawals, settlement, chargebacks, exchange rates, or multi-currency conversion are implemented. Demo opening capital is external baseline data, not itself a double-entry funding transfer.
- Accounts use three uppercase letters as a currency code but do not validate against an ISO currency registry or currency-specific decimal precision. Callers must agree on minor-unit meaning.
- Reconciliation detects drift but does not automatically repair balances; investigate the report and post a valid correction through the accounting workflow.
- Failed transfer business outcomes are stored for idempotent replay. Correcting the cause requires a new idempotency key and a new request.
- PostgreSQL 16 is required. The test, demo, and migration flows need Docker or another PostgreSQL service.
- GitHub Pages is only live after the project is pushed to its intended GitHub repository and Pages is enabled for Actions. A workflow file in a local checkout alone does not publish a site.

## License

MIT. See [LICENSE](LICENSE). Architectural rationale is recorded in [DECISIONS.md](DECISIONS.md).
