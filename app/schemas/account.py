from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AccountCreate(BaseModel):
    owner_name: str = Field(min_length=1, max_length=200)
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def currency_is_iso_style(cls, value: str) -> str:
        if not value.isalpha() or not value.isupper():
            raise ValueError("currency must be a three-letter uppercase code")
        return value


class AccountRead(BaseModel):
    id: int
    owner_name: str
    currency: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AccountListItem(AccountRead):
    balance_minor: int


class AccountPage(BaseModel):
    items: list[AccountListItem]
    next_cursor: int | None
