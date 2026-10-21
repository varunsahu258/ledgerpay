from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


def normalize_database_url(value: str) -> str:
    """Adapt common PostgreSQL URLs and libpq SSL query options for asyncpg."""
    url = make_url(value)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+asyncpg")
    if url.drivername != "postgresql+asyncpg":
        return url.render_as_string(hide_password=False)

    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    # asyncpg controls channel binding itself; it is not a connection keyword.
    query.pop("channel_binding", None)
    if sslmode is not None and "ssl" not in query:
        # asyncpg accepts PostgreSQL sslmode values using its `ssl` parameter.
        query["ssl"] = sslmode
    return url.set(query=query).render_as_string(hide_password=False)


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://ledgerpay:ledgerpay@localhost:5432/ledgerpay"
    app_env: str = "development"
    demo_mode: bool = False
    demo_rate_limit_requests: int = Field(default=60, ge=1)
    demo_rate_limit_window_seconds: int = Field(default=60, ge=1)
    demo_max_accounts: int = Field(default=100, ge=1)
    demo_seed_token: str | None = None
    demo_reset_enabled: bool = False
    demo_api_base_url: str = "http://localhost:8000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def use_asyncpg_driver(cls, value: str) -> str:
        return normalize_database_url(value)


settings = Settings()
