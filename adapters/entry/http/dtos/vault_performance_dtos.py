from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CashflowItem(BaseModel):
    event_type: str  # deposit|withdraw
    ts_ms: int
    ts_iso: str

    token: Optional[str] = None
    amount_human: Optional[str] = None
    amount_raw: Optional[str] = None
    decimals: Optional[int] = None

    amount_usd: Optional[float] = None
    amount_usd_source: Optional[str] = None  # stable|spot_est|unknown

    tx_hash: str


class CashflowTotals(BaseModel):
    deposited_usd: Optional[float] = None
    withdrawn_usd: Optional[float] = None
    net_contributed_usd: Optional[float] = None

    missing_usd_count: int = 0


class CurrentValueBlock(BaseModel):
    total_usd: Optional[float] = None
    in_position_usd: Optional[float] = None
    vault_idle_usd: Optional[float] = None

    fees_uncollected_usd: Optional[float] = None
    rewards_pending_usd: Optional[float] = None

    source: str = "unknown"  # live_status|last_episode|unknown


class ProfitAnnualized(BaseModel):
    method: str = "modified_dietz"
    days: Optional[float] = None

    daily_rate: Optional[float] = None
    apr: Optional[float] = None
    apy_daily_compound: Optional[float] = None


class ProfitBlock(BaseModel):
    profit_usd: Optional[float] = None
    profit_pct: Optional[float] = None

    profit_net_gas_usd: Optional[float] = None
    profit_net_gas_pct: Optional[float] = None

    annualized: ProfitAnnualized = Field(default_factory=ProfitAnnualized)


class EpisodeItem(BaseModel):
    id: Optional[str] = None
    status: str

    open_time: int
    open_time_iso: Optional[str] = None
    close_time: Optional[int] = None
    close_time_iso: Optional[str] = None

    open_price: Optional[float] = None
    close_price: Optional[float] = None

    Pa: Optional[float] = None
    Pb: Optional[float] = None

    pool_type: Optional[str] = None
    mode_on_open: Optional[str] = None
    majority_on_open: Optional[str] = None

    last_event_bar: Optional[int] = None
    metrics: Optional[Dict[str, Any]] = None


class EpisodesBlock(BaseModel):
    items: List[EpisodeItem] = []
    total: Optional[int] = None


class GasCostsBlock(BaseModel):
    total_gas_usd: float = 0.0
    tx_count: int = 0


class VaultPerformanceData(BaseModel):
    vault: Dict[str, Any] = {}
    period: Dict[str, Any] = {}

    cashflows: List[CashflowItem] = []
    cashflows_totals: CashflowTotals = Field(default_factory=CashflowTotals)

    current_value: CurrentValueBlock = Field(default_factory=CurrentValueBlock)

    gas_costs: GasCostsBlock = Field(default_factory=GasCostsBlock)
    profit: ProfitBlock = Field(default_factory=ProfitBlock)

    episodes: EpisodesBlock = Field(default_factory=EpisodesBlock)


class VaultPerformanceResponse(BaseModel):
    ok: bool = True
    message: str = "ok"
    data: VaultPerformanceData
