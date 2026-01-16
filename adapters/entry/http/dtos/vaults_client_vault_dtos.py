from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class TxGasBlock(BaseModel):
    limit: Optional[int] = None
    used: Optional[int] = None
    price_wei: Optional[int] = None
    effective_price_wei: Optional[int] = None
    cost_eth: Optional[float] = None
    cost_usd: Optional[float] = None


class TxBudgetBlock(BaseModel):
    max_gas_usd: Optional[float] = None
    eth_usd_hint: Optional[float] = None
    usd_estimated_upper_bound: Optional[float] = None
    budget_exceeded: Optional[bool] = None


class TxRunResponse(BaseModel):
    tx_hash: str
    broadcasted: bool
    receipt: Optional[Dict[str, Any]] = None
    status: Optional[int] = None

    gas: Optional[TxGasBlock] = None
    budget: Optional[TxBudgetBlock] = None

    result: Optional[Dict[str, Any]] = None
    ts: Optional[str] = None

    # extra fields for vault creation
    vault_address: Optional[str] = None
    alias: Optional[str] = None
    mongo_id: Optional[str] = None


class SwapPoolRefIn(BaseModel):
    dex: str
    pool: str


class VaultConfigIn(BaseModel):
    adapter: str
    pool: str
    nfpm: str
    gauge: Optional[str] = None

    rpc_url: str
    version: str
    swap_pools: Dict[str, SwapPoolRefIn] = Field(default_factory=dict)


class CreateClientVaultRequest(BaseModel):
    # onchain
    strategy_id: int = Field(..., ge=1)
    owner: str = Field(..., description="Owner address to create vault for (required)")
    gas_strategy: str = Field(default="buffered", description="default|buffered|aggressive")

    # registry metadata
    chain: str = Field(..., description="ex: base")
    dex: str = Field(..., description="ex: pancake|aerodrome|uniswap")
    par_token: str = Field(..., description="Ex: WETH or CAKE or any symbol identifier used in alias")
    name: str = Field(..., description="Human friendly name (user-provided)")
    description: Optional[str] = Field(default=None, description="Human friendly description")

    config: VaultConfigIn = Field(..., description="Off-chain config that must be persisted under config")
