import pytest_asyncio

from app.db import engine


@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def dispose_database_engine_between_tests() -> None:
    yield
    await engine.dispose()
