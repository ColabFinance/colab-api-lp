from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AutoHarvestDailyParams(BaseModel):
    """
    Pydantic representation of ClientVault.AutoHarvestDailyParams (Solidity struct).

    This struct is used by ClientVault.autoHarvestAndCompoundPancake(params).

    Notes:
    - rewardAmountIn == 0 means "use full reward buffer balance" (contract rule)
    - rewardSqrtPriceLimitX96 == 0 means "use configured default" (contract rule)
    - compound0Desired/compound1Desired == 0 means "use full token buffer balance" (contract rule)
    """

    # Harvest (harvest_job)
    harvestPoolFees: bool = Field(..., description="If True, collect pool fees into buffer.")
    harvestRewards: bool = Field(..., description="If True, claim farming rewards into buffer.")

    # Optional reward swap (still part of harvest_job)
    swapRewards: bool = Field(False, description="If True, swap rewards using configured restricted single-hop path.")
    rewardAmountIn: int = Field(0, ge=0, description="Reward amount in (raw). 0 = full reward buffer balance.")
    rewardAmountOutMin: int = Field(0, ge=0, description="Min amount out (raw) for reward swap.")
    rewardSqrtPriceLimitX96: int = Field(
        0,
        ge=0,
        description="Sqrt price limit (uint160). 0 = use configured default.",
    )

    # Compound (compound_job)
    compound: bool = Field(False, description="If True, add liquidity using buffer balances.")
    compound0Desired: int = Field(0, ge=0, description="Token0 desired (raw). 0 = full token0 buffer.")
    compound1Desired: int = Field(0, ge=0, description="Token1 desired (raw). 0 = full token1 buffer.")
    compound0Min: int = Field(0, ge=0, description="Token0 min (raw).")
    compound1Min: int = Field(0, ge=0, description="Token1 min (raw).")

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    def to_abi_dict(self) -> dict:
        """
        Convert to a plain dict compatible with web3.py ABI encoding.
        Keys match the Solidity struct field names exactly.
        """
        return self.model_dump(exclude_none=True)
