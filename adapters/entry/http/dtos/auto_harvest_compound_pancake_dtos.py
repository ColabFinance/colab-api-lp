from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class HarvestJobPancakeRequest(BaseModel):
    """
    Request payload for the harvest_job endpoint.

    This endpoint calls ClientVault.autoHarvestAndCompoundPancake with:
      - harvestPoolFees/harvestRewards (+ optional reward swap)
      - compound disabled
    """

    harvest_pool_fees: bool = Field(True, description="Collect pool fees into buffer.")
    harvest_rewards: bool = Field(True, description="Claim rewards into buffer.")

    swap_rewards: bool = Field(False, description="Swap rewards using configured restricted single-hop rewardSwap.")
    reward_amount_in: int = Field(0, ge=0, description="0 = use full reward buffer balance.")
    reward_amount_out_min: int = Field(0, ge=0, description="Min amount out for reward swap (raw).")
    reward_sqrt_price_limit_x96: int = Field(0, ge=0, description="0 = use config default.")

    gas_strategy: str = Field(default="buffered", description="default|buffered|aggressive")
    meta: Optional[Dict[str, Any]] = None


class CompoundJobPancakeRequest(BaseModel):
    """
    Request payload for the compound_job endpoint.

    This endpoint calls ClientVault.autoHarvestAndCompoundPancake with:
      - harvest disabled
      - compound enabled using token buffer balances
    """

    compound0_desired: int = Field(0, ge=0, description="0 = use full token0 buffer balance.")
    compound1_desired: int = Field(0, ge=0, description="0 = use full token1 buffer balance.")
    compound0_min: int = Field(0, ge=0, description="Token0 min (raw).")
    compound1_min: int = Field(0, ge=0, description="Token1 min (raw).")

    gas_strategy: str = Field(default="buffered", description="default|buffered|aggressive")
    meta: Optional[Dict[str, Any]] = None
