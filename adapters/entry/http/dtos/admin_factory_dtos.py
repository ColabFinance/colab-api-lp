from pydantic import BaseModel, Field


class CreateFactoryRequest(BaseModel):
    gas_strategy: str = Field(default="buffered", description="default|buffered|aggressive")


class FactoryRecordOut(BaseModel):
    address: str
    status: str
    created_at: str
    tx_hash: str | None = None
