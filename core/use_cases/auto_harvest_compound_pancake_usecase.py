from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from web3 import Web3

from adapters.chain.client_vault import ClientVaultAdapter
from adapters.external.database.mongo_client import get_mongo_db
from adapters.external.database.vault_client_registry_repository_mongodb import VaultRegistryRepositoryMongoDB
from config import get_settings
from core.domain.entities.vault_client_registry_entity import VaultRegistryEntity
from core.domain.repositories.vault_client_registry_repository_interface import VaultRegistryRepositoryInterface
from core.domain.schemas.auto_harvest_daily_types import AutoHarvestDailyParams
from core.services.tx_service import TxService
from core.services.utils import to_json_safe


@dataclass
class AutoHarvestCompoundPancakeUseCase:
    """
    Use case for daily ops that are executed by off-chain jobs:

    - harvest_job: collect pool fees + claim rewards (+ optional reward swap)
    - compound_job: add liquidity using vault buffer balances

    Both operations call the SAME contract method:
        ClientVault.autoHarvestAndCompoundPancake(params)

    The only difference is the params passed (harvest toggles vs compound toggles).
    """

    vault_registry_repo: VaultRegistryRepositoryInterface

    @classmethod
    def from_settings(cls) -> "AutoHarvestCompoundPancakeUseCase":
        db = get_mongo_db()
        repo = VaultRegistryRepositoryMongoDB(db[VaultRegistryRepositoryMongoDB.COLLECTION])
        repo.ensure_indexes()
        return cls(vault_registry_repo=repo)

    def _get_vault_by_alias(self, alias: str) -> VaultRegistryEntity:
        alias = (alias or "").strip()
        if not alias:
            raise ValueError("alias is required")

        ent = self.vault_registry_repo.find_by_alias(alias)
        if not ent:
            raise ValueError(f"Unknown vault alias: {alias}")
        return ent

    def _assert_pancake(self, ent: VaultRegistryEntity) -> None:
        dex = (ent.dex or "").strip().lower()
        if dex != "pancake_v3":
            raise ValueError(f"Vault dex mismatch. expected=pancake got={dex}")

    def _rpc_url_for_vault(self, ent: VaultRegistryEntity) -> str:
        s = get_settings()
        rpc_url = (getattr(ent.config, "rpc_url", None) or "").strip()
        return rpc_url or s.RPC_URL_DEFAULT

    def _build_w3_and_txs(self, rpc_url: str) -> tuple[Web3, TxService]:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        txs = TxService(rpc_url)
        return w3, txs

    def harvest_job(
        self,
        *,
        alias: str,
        harvest_pool_fees: bool = True,
        harvest_rewards: bool = True,
        swap_rewards: bool = False,
        reward_amount_in: int = 0,
        reward_amount_out_min: int = 0,
        reward_sqrt_price_limit_x96: int = 0,
        gas_strategy: str = "buffered",
    ) -> dict:
        """
        Execute the daily harvest job:

        - Collect pool fees into buffer
        - Claim rewards into buffer
        - Optionally swap rewards (restricted single-hop based on vault config)

        Contract call:
            autoHarvestAndCompoundPancake(params) with compound disabled.
        """
        ent = self._get_vault_by_alias(alias)
        self._assert_pancake(ent)

        vault_addr = (ent.config.address or "").strip()
        if not (Web3.is_address(vault_addr) and len(vault_addr) == 42):
            raise ValueError("Vault address not found/invalid in registry config.address")

        rpc_url = self._rpc_url_for_vault(ent)
        w3, txs = self._build_w3_and_txs(rpc_url)

        params = AutoHarvestDailyParams(
            harvestPoolFees=bool(harvest_pool_fees),
            harvestRewards=bool(harvest_rewards),
            swapRewards=bool(swap_rewards),
            rewardAmountIn=int(reward_amount_in or 0),
            rewardAmountOutMin=int(reward_amount_out_min or 0),
            rewardSqrtPriceLimitX96=int(reward_sqrt_price_limit_x96 or 0),
            compound=False,
            compound0Desired=0,
            compound1Desired=0,
            compound0Min=0,
            compound1Min=0,
        )

        cv = ClientVaultAdapter(w3=w3, address=vault_addr)
        fn = cv.fn_auto_harvest_and_compound_pancake(params)
        tx_any = txs.send(fn, wait=True, gas_strategy=gas_strategy)

        return to_json_safe(
            {
                "tx": tx_any,
                "mode": "harvest_job",
                "alias": ent.alias,
                "vault_address": Web3.to_checksum_address(vault_addr),
                "rpc_url_used": rpc_url,
                "params_used": params.model_dump(),
            }
        )

    def compound_job(
        self,
        *,
        alias: str,
        compound0_desired: int = 0,
        compound1_desired: int = 0,
        compound0_min: int = 0,
        compound1_min: int = 0,
        gas_strategy: str = "buffered",
    ) -> dict:
        """
        Execute the daily compound job:

        - Do NOT harvest fees/rewards
        - Add liquidity using buffer token balances

        Contract call:
            autoHarvestAndCompoundPancake(params) with harvest disabled and compound enabled.
        """
        ent = self._get_vault_by_alias(alias)
        self._assert_pancake(ent)

        vault_addr = (ent.config.address or "").strip()
        if not (Web3.is_address(vault_addr) and len(vault_addr) == 42):
            raise ValueError("Vault address not found/invalid in registry config.address")

        rpc_url = self._rpc_url_for_vault(ent)
        w3, txs = self._build_w3_and_txs(rpc_url)

        params = AutoHarvestDailyParams(
            harvestPoolFees=False,
            harvestRewards=False,
            swapRewards=False,
            rewardAmountIn=0,
            rewardAmountOutMin=0,
            rewardSqrtPriceLimitX96=0,
            compound=True,
            compound0Desired=int(compound0_desired or 0),
            compound1Desired=int(compound1_desired or 0),
            compound0Min=int(compound0_min or 0),
            compound1Min=int(compound1_min or 0),
        )

        cv = ClientVaultAdapter(w3=w3, address=vault_addr)
        fn = cv.fn_auto_harvest_and_compound_pancake(params)
        tx_any = txs.send(fn, wait=True, gas_strategy=gas_strategy)

        return to_json_safe(
            {
                "tx": tx_any,
                "mode": "compound_job",
                "alias": ent.alias,
                "vault_address": Web3.to_checksum_address(vault_addr),
                "rpc_url_used": rpc_url,
                "params_used": params.model_dump(),
            }
        )
