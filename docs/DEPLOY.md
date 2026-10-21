# Deploy LedgerPay to Render + Neon

This deploys the Dockerized FastAPI service on Render and PostgreSQL on Neon. The API expects
`DATABASE_URL` as a PostgreSQL URL; plain `postgres://` and `postgresql://` URLs are normalized to
SQLAlchemy's `postgresql+asyncpg://` driver. `sslmode=require` (and other asyncpg-supported
PostgreSQL SSL modes) is translated to asyncpg's `ssl` option. The libpq `channel_binding` URL
parameter is removed because asyncpg manages SCRAM channel binding itself.

## 1. Create the Neon database

1. Create a Neon project and a PostgreSQL database/role in the Neon Console.
2. Open **Connect** for the project and copy the PostgreSQL connection string. It normally looks
   like `postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require&channel_binding=require`.
3. Keep that string private. You will paste it into Render as the `DATABASE_URL` secret. Do not
   commit it to this repository or place it in `.env.example`.

Neon documents that connection URIs use the standard PostgreSQL connection-string format; use the
direct connection URL for this service. See [Neon's connection URI reference](https://api-docs.neon.tech/reference/getconnectionuri).

## 2. Create the Render web service

1. Push this repository to GitHub.
2. In Render, choose **New → Blueprint**, connect the repository, and deploy the checked-in
   `render.yaml` blueprint. It defines a Docker web service using the repository's Dockerfile.
3. When Render prompts for `DATABASE_URL`, paste the Neon connection string. Set `DEMO_SEED_TOKEN`
   to a long, random secret used only by the demo seeder/reset job. Generate one locally, for
   example with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`.
4. Create/deploy the service. Its Docker command runs `uv run --no-sync alembic upgrade head`
   before starting Uvicorn on Render's `PORT`. Render checks `/health` before routing traffic.
5. Copy the service's `onrender.com` URL. The console is at `/console/`; the interactive API docs
   are at `/docs`.

The blueprint enables `DEMO_MODE=true`, caps accounts, and rate-limits write requests. The
in-memory per-IP limiter is process-local and intended as a simple showcase safeguard, not a
replacement for a distributed rate limiter or production abuse controls.

## 3. Seed the public demo

Run from this repository after deployment. These variables must match the Render settings; the
seed token authorizes the controlled seed writes past the public request limit.

```sh
export DATABASE_URL='postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require&channel_binding=require'
export DEMO_MODE=true
export DEMO_SEED_TOKEN='the-same-random-secret-configured-in-render'
uv sync --python 3.12 --all-groups
uv run python -m app.demo --base-url 'https://YOUR-SERVICE.onrender.com' --seed-token "$DEMO_SEED_TOKEN"
```

The seeder creates 20 accounts and submits 500 transfers through the public API. It also records
the demo accounts' opening capital in the connected Neon database.

## 4. Schedule a periodic reset (optional)

`scripts/reset_demo.py` truncates every LedgerPay table and reseeds it. Use it only against a
dedicated demo database. It refuses to run unless `DEMO_MODE=true`, `DEMO_RESET_ENABLED=true`, and a
`DEMO_SEED_TOKEN` are provided. Configure those variables in the cron job's environment, not by
committing secrets. Example command:

```sh
DEMO_MODE=true DEMO_RESET_ENABLED=true \
DEMO_API_BASE_URL='https://YOUR-SERVICE.onrender.com' \
uv run python scripts/reset_demo.py --base-url 'https://YOUR-SERVICE.onrender.com'
```

The cron environment also needs `DATABASE_URL` and the same `DEMO_SEED_TOKEN` configured in the
Render service. The destructive reset is deliberately opt-in; schedule it only for a database
whose contents can be discarded.

## 5. Verify the deployment

```sh
curl -fsS 'https://YOUR-SERVICE.onrender.com/health'
curl -fsS 'https://YOUR-SERVICE.onrender.com/accounts?limit=25'
```

For platform setup details, see [Render's Docker deployment guide](https://render.com/docs/docker),
[Blueprint reference](https://render.com/docs/blueprint-spec), and
[health-check guide](https://render.com/docs/health-checks).
