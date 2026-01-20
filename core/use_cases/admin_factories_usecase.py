from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from adapters.chain.artifacts import load_contract_from_out
from adapters.external.database.strategy_factory_repository_mongodb import StrategyRepositoryMongoDB
from adapters.external.database.vault_factory_repository_mongodb import VaultFactoryRepositoryMongoDB
from config import get_settings
from core.domain.entities.factory_entities import StrategyFactoryEntity, VaultFactoryEntity
from core.domain.enums.factory_enums import FactoryStatus
from core.domain.enums.tx_enums import GasStrategy
from core.domain.repositories.strategy_factory_repository_interface import StrategyRepository
from core.domain.repositories.vault_factory_repository_interface import VaultFactoryRepository
from core.services.tx_service import TxService


@dataclass
class AdminFactoriesUseCase:
    txs: TxService
    strategy_repo: StrategyRepository
    vault_repo: VaultFactoryRepository

    @classmethod
    def from_settings(cls) -> "AdminFactoriesUseCase":
        s = get_settings()
        strategy_repo = StrategyRepositoryMongoDB()
        vault_repo = VaultFactoryRepositoryMongoDB()

        # Ensure indexes once
        try:
            strategy_repo.ensure_indexes()
        except Exception:
            pass
        try:
            vault_repo.ensure_indexes()
        except Exception:
            pass

        return cls(
            txs=TxService(s.RPC_URL_DEFAULT),
            strategy_repo=strategy_repo,
            vault_repo=vault_repo,
        )

    def _ensure_can_create(self, latest_status: FactoryStatus | None) -> None:
        if latest_status is None:
            return
        if latest_status == FactoryStatus.ARCHIVED_CAN_CREATE_NEW:
            return
        raise ValueError("A factory already exists and does not allow creating a new one.")

    def create_strategy_registry(
        self,
        *,
        chain: str,
        initial_owner: str,
        gas_strategy: GasStrategy = GasStrategy.BUFFERED,
    ) -> dict:
        chain = (chain or "").strip().lower()
        if not chain:
            raise ValueError("chain is required")
        
        latest = self.strategy_repo.get_latest(chain=chain)
        self._ensure_can_create(latest.status if latest else None)

        abi, bytecode = load_contract_from_out("vaults", "StrategyRegistry.json")

        res = self.txs.deploy(
            abi=abi,
            bytecode=bytecode,
            ctor_args=(initial_owner,),
            wait=True,
            gas_strategy=gas_strategy,
        )

        addr = (res.get("result") or {}).get("contract_address")
        if not addr:
            raise RuntimeError("Deploy succeeded but contract_address is missing.")

        self.strategy_repo.set_all_status(chain=chain, status=FactoryStatus.ARCHIVED_CAN_CREATE_NEW)
        ent = StrategyFactoryEntity(
            chain=chain,
            address=str(addr),
            status=FactoryStatus.ACTIVE,
            tx_hash=res.get("tx_hash"),
        )
        self.strategy_repo.insert(ent)
        
        active = self.strategy_repo.get_active(chain=chain)
        if not active or active.address.lower() != ent.address.lower():
            raise RuntimeError("Factory deployed but failed to persist as ACTIVE in MongoDB.")
        
        res["result"] = {
            "chain": ent.chain,
            "address": ent.address,
            "status": ent.status.value,
            "created_at": ent.created_at_iso,
        }
        return res

    def create_vault_factory(
        self,
        *,
        chain: str,
        initial_owner: str,
        strategy_registry: str,
        executor: str,
        fee_collector: str = "0x0000000000000000000000000000000000000000",
        default_cooldown_sec: int = 300,
        default_max_slippage_bps: int = 50,
        default_allow_swap: bool = True,
        gas_strategy: GasStrategy = GasStrategy.BUFFERED,
    ) -> dict:
        chain = (chain or "").strip().lower()
        if not chain:
            raise ValueError("chain is required")
        
        latest = self.vault_repo.get_latest(chain=chain)
        self._ensure_can_create(latest.status if latest else None)

        abi, bytecode = load_contract_from_out("vaults", "VaultFactory.json")

        res = self.txs.deploy(
            abi=abi,
            bytecode=bytecode,
            ctor_args=(
                initial_owner,
                strategy_registry,
                executor,
                fee_collector,
                int(default_cooldown_sec),
                int(default_max_slippage_bps),
                bool(default_allow_swap),
            ),
            wait=True,
            gas_strategy=gas_strategy,
        )

        addr = (res.get("result") or {}).get("contract_address")
        if not addr:
            raise RuntimeError("Deploy succeeded but contract_address is missing.")

        self.vault_repo.set_all_status(chain=chain, status=FactoryStatus.ARCHIVED_CAN_CREATE_NEW)
        ent = VaultFactoryEntity(
            chain=chain,
            address=str(addr),
            status=FactoryStatus.ACTIVE,
            tx_hash=res.get("tx_hash"),
        )
        self.vault_repo.insert(ent)

        active = self.vault_repo.get_active(chain=chain)
        if not active or active.address.lower() != ent.address.lower():
            raise RuntimeError("Factory deployed but failed to persist as ACTIVE in MongoDB.")
        
        res["result"] = {
            "chain": ent.chain,
            "address": ent.address,
            "status": ent.status.value,
            "created_at": ent.created_at_iso,
        }
        return res
