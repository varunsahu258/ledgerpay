from datetime import datetime

from pydantic import BaseModel, Field


class TransferCreate(BaseModel):
    from_account: int = Field(gt=0)
    to_account: int = Field(gt=0)
    amount_minor: int = Field(gt=0)


class TransferRead(BaseModel):
    id: str
    from_account: int
    to_account: int
    amount_minor: int
    status: str
    created_at: datetime


class ReversalRead(BaseModel):
    id: str
    reversal_of: str
    from_account: int
    to_account: int
    amount_minor: int
    status: str


class ErrorBody(BaseModel):
    code: str
    message: str
