"""Reset and reseed a dedicated public-demo database; intended for scheduled use."""

import argparse
import asyncio

from sqlalchemy import text

from app.core.config import settings
from app.db import engine
from app.demo import seed


async def reset(base_url: str) -> None:
    if not settings.demo_mode:
        raise RuntimeError("Refusing reset: DEMO_MODE must be true")
    if not settings.demo_reset_enabled:
        raise RuntimeError("Refusing reset: DEMO_RESET_ENABLED must be true")
    if not settings.demo_seed_token:
        raise RuntimeError("Refusing reset: configure DEMO_SEED_TOKEN for protected reseeding")

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE audit_log, ledger_entries, transfers, balances, accounts "
                "RESTART IDENTITY CASCADE"
            )
        )
    await seed(base_url, seed_token=settings.demo_seed_token)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=settings.demo_api_base_url)
    args = parser.parse_args()

    async def run_and_dispose() -> None:
        try:
            await reset(args.base_url)
        finally:
            await engine.dispose()

    asyncio.run(run_and_dispose())


if __name__ == "__main__":
    main()
