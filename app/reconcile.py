import asyncio
import json

from app.db import SessionLocal, engine
from app.services.reconciliation import reconcile


async def run() -> int:
    async with SessionLocal() as session:
        report = await reconcile(session)
    print(json.dumps(report, sort_keys=True))
    await engine.dispose()
    return 0 if report["ok"] else 1


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
