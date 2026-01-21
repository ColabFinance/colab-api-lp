from __future__ import annotations

from typing import Any, Dict, Optional, List

from pydantic import BaseModel, Field

from core.domain.schemas.vault_inputs import VaultCreateConfigIn


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

    vault_address: Optional[str] = None
    alias: Optional[str] = None
    mongo_id: Optional[str] = None

    @classmethod
    def from_tx_any(
        cls,
        *,
        tx_any: Any,
        vault_address: Optional[str] = None,
        alias: Optional[str] = None,
        mongo_id: Optional[str] = None,
    ) -> "TxRunResponse":
        if isinstance(tx_any, dict):
            tx = tx_any
        elif isinstance(tx_any, str) and tx_any.startswith("0x"):
            tx = {
                "tx_hash": tx_any,
                "broadcasted": True,
                "status": None,
                "receipt": None,
                "gas": {},
                "budget": {},
                "result": {},
                "ts": None,
            }
        else:
            tx = {
                "tx_hash": "",
                "broadcasted": False,
                "status": None,
                "receipt": None,
                "gas": {},
                "budget": {},
                "result": {},
                "ts": None,
            }

        return cls(
            tx_hash=str(tx.get("tx_hash") or ""),
            broadcasted=bool(tx.get("broadcasted", True)),
            receipt=(tx.get("receipt") if isinstance(tx.get("receipt"), dict) else tx.get("receipt")),
            status=(tx.get("status") if isinstance(tx.get("status"), int) else None),
            gas=(TxGasBlock.model_validate(tx.get("gas") or {}) if isinstance(tx.get("gas"), dict) else None),
            budget=(TxBudgetBlock.model_validate(tx.get("budget") or {}) if isinstance(tx.get("budget"), dict) else None),
            result=(tx.get("result") if isinstance(tx.get("result"), dict) else None),
            ts=(str(tx.get("ts")) if tx.get("ts") is not None else None),
            vault_address=vault_address,
            alias=alias,
            mongo_id=mongo_id,
        )


class CreateClientVaultRequest(BaseModel):
    strategy_id: int = Field(..., ge=1)
    owner: str = Field(..., description="Owner address to create vault for (required)")
    gas_strategy: str = Field(default="buffered", description="default|buffered|aggressive")

    chain: str = Field(..., description="ex: base")
    dex: str = Field(..., description="ex: pancake|aerodrome|uniswap")
    par_token: str = Field(..., description="Ex: WETH or CAKE or any symbol identifier used in alias")
    name: str = Field(..., description="Human friendly name (user-provided)")
    description: Optional[str] = Field(default=None, description="Human friendly description")

    config: VaultCreateConfigIn = Field(..., description="Vault config persisted under `config`")


class RegisterClientVaultRequest(BaseModel):
    vault_address: str
    strategy_id: int

    chain: str
    dex: str
    owner: str
    par_token: str

    name: str
    description: Optional[str] = None

    config: VaultCreateConfigIn


class VaultRegistryOut(BaseModel):
    id: Optional[str] = None

    dex: Optional[str] = None
    address: str
    alias: str
    is_active: Optional[bool] = None

    chain: Optional[str] = None
    owner: Optional[str] = None
    par_token: Optional[str] = None

    name: Optional[str] = None
    description: Optional[str] = None
    strategy_id: Optional[int] = None

    config: Optional[Dict[str, Any]] = None

    created_at: Optional[int] = None
    created_at_iso: Optional[str] = None
    updated_at: Optional[int] = None
    updated_at_iso: Optional[str] = None
