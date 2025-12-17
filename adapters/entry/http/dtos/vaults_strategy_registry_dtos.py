from pydantic import BaseModel, Field


class StrategyOnchainOut(BaseModel):
    strategy_id: int
    adapter: str
    dex_router: str
    token0: str
    token1: str
    name: str
    description: str
    active: bool

class RegisterStrategyTxRequest(BaseModel):
    adapter: str
    dex_router: str
    token0: str
    token1: str
    name: str
    description: str


class UpdateStrategyTxRequest(BaseModel):
    strategy_id: int = Field(..., ge=1)
    adapter: str
    dex_router: str
    token0: str
    token1: str
    name: str
    description: str


class SetStrategyActiveTxRequest(BaseModel):
    admin_wallet: str
    strategy_id: int = Field(..., ge=1)
    active: bool
