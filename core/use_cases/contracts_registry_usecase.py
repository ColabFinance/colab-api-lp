from __future__ import annotations

from dataclasses import dataclass

from adapters.external.database.adapter_registry_repository_mongodb import AdapterRegistryRepositoryMongoDB
from adapters.external.database.strategy_factory_repository_mongodb import StrategyRepositoryMongoDB
from adapters.external.database.vault_factory_repository_mongodb import VaultFactoryRepositoryMongoDB
from core.domain.repositories.adapter_registry_repository_interface import AdapterRegistryRepository
from core.domain.repositories.strategy_factory_repository_interface import StrategyRepository
from core.domain.repositories.vault_factory_repository_interface import VaultFactoryRepository

from adapters.entry.http.dtos.contracts_registry_dtos import (
    ContractsRegistryOut,
    FactoryPublicOut,
    AdapterRegistryPublicOut,
)


@dataclass
class ContractsRegistryUseCase:
    adapters_repo: AdapterRegistryRepository
    strategy_repo: StrategyRepository
    vault_repo: VaultFactoryRepository

    @classmethod
    def from_settings(cls) -> "ContractsRegistryUseCase":
        # repos already use get_mongo_db() internally
        adapters_repo = AdapterRegistryRepositoryMongoDB()
        strategy_repo = StrategyRepositoryMongoDB()
        vault_repo = VaultFactoryRepositoryMongoDB()

        try:
            adapters_repo.ensure_indexes()
        except Exception:
            pass
        try:
            strategy_repo.ensure_indexes()
        except Exception:
            pass
        try:
            vault_repo.ensure_indexes()
        except Exception:
            pass

        return cls(
            adapters_repo=adapters_repo,
            strategy_repo=strategy_repo,
            vault_repo=vault_repo,
        )

    def get_registry(self, *, chain: str) -> ContractsRegistryOut:
        chain = (chain or "").strip().lower()
        if not chain:
            raise ValueError("chain is required")

        strategy = self.strategy_repo.get_active(chain=chain)
        if not strategy:
            raise ValueError(f"No ACTIVE strategy factory found for chain={chain}")

        vault = self.vault_repo.get_active(chain=chain)
        if not vault:
            raise ValueError(f"No ACTIVE vault factory found for chain={chain}")

        adapters = self.adapters_repo.list_active(chain=chain, limit=500)

        return ContractsRegistryOut(
            chain=chain,
            strategy_factory=FactoryPublicOut(chain=chain, address=strategy.address),
            vault_factory=FactoryPublicOut(chain=chain, address=vault.address),
            adapters=[
                AdapterRegistryPublicOut(
                    chain=a.chain,
                    address=a.address,
                    dex=a.dex,
                    pool=a.pool,
                    nfpm=a.nfpm,
                    gauge=a.gauge,
                    token0=a.token0,
                    token1=a.token1,
                    pool_name=a.pool_name,
                    fee_bps=a.fee_bps,
                )
                for a in adapters
            ],
        )
