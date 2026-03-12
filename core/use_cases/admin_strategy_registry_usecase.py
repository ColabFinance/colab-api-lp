from __future__ import annotations

from dataclasses import dataclass

from adapters.chain.artifacts import load_contract_from_out
from adapters.external.database.strategy_registry_repository_mongodb import StrategyRepositoryMongoDB
from config import get_settings
from core.domain.entities.strategy_registry_entity import StrategyRegistryEntity
from core.domain.enums.factory_enums import FactoryStatus
from core.domain.enums.tx_enums import GasStrategy
from core.domain.repositories.strategy_registry_repository_interface import StrategyRepository
from core.services.tx_service import TxService


@dataclass
class AdminStrategyFactoryUseCase:
    txs: TxService
    strategy_repo: StrategyRepository

    @classmethod
    def from_settings(cls) -> "AdminStrategyFactoryUseCase":
        s = get_settings()
        strategy_repo = StrategyRepositoryMongoDB()

        try:
            strategy_repo.ensure_indexes()
        except Exception:
            pass

        return cls(
            txs=TxService(s.RPC_URL_DEFAULT),
            strategy_repo=strategy_repo,
        )

    def _ensure_can_create(self, latest_status: FactoryStatus | None) -> None:
        if latest_status is None:
            return
        if latest_status == FactoryStatus.ARCHIVED_CAN_CREATE_NEW:
            return
        raise ValueError("A factory already exists and does not allow creating a new one.")

    @staticmethod
    def _serialize_record(ent: StrategyRegistryEntity | None) -> dict | None:
        if ent is None:
            return None

        status = ent.status.value if hasattr(ent.status, "value") else ent.status
        return {
            "chain": ent.chain,
            "address": ent.address,
            "status": status,
            "tx_hash": getattr(ent, "tx_hash", None),
            "owner": getattr(ent, "owner", None),
            "created_at": getattr(ent, "created_at", None),
            "created_at_iso": getattr(ent, "created_at_iso", None),
            "updated_at": getattr(ent, "updated_at", None),
            "updated_at_iso": getattr(ent, "updated_at_iso", None),
        }

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

        ent = StrategyRegistryEntity(
            chain=chain,
            address=str(addr),
            status=FactoryStatus.ACTIVE,
            tx_hash=res.get("tx_hash"),
            owner=initial_owner,
        )
        self.strategy_repo.insert(ent)

        active = self.strategy_repo.get_active(chain=chain)
        if not active or active.address.lower() != ent.address.lower():
            raise RuntimeError("Factory deployed but failed to persist as ACTIVE in MongoDB.")

        res["result"] = self._serialize_record(active)
        return res

    def list_strategy_registries(
        self,
        *,
        chain: str,
        limit: int = 50,
    ) -> dict:
        chain = (chain or "").strip().lower()
        if not chain:
            raise ValueError("chain is required")

        limit = max(1, int(limit))

        active = self.strategy_repo.get_active(chain=chain)
        history = self.strategy_repo.list_all(chain=chain, limit=limit)

        return {
            "ok": True,
            "message": "Strategy registry records fetched successfully.",
            "result": {
                "active": self._serialize_record(active),
                "history": [self._serialize_record(item) for item in history],
            },
        }