from __future__ import annotations

from dataclasses import dataclass

from adapters.chain.artifacts import load_contract_from_out
from adapters.external.database.vault_factory_repository_mongodb import VaultFactoryRepositoryMongoDB
from config import get_settings
from core.domain.entities.vault_factory_entity import VaultFactoryEntity
from core.domain.enums.factory_enums import FactoryStatus
from core.domain.enums.tx_enums import GasStrategy
from core.domain.repositories.vault_factory_repository_interface import VaultFactoryRepository
from core.services.tx_service import TxService


@dataclass
class AdminVaultFactoryUseCase:
    txs: TxService
    vault_repo: VaultFactoryRepository

    @classmethod
    def from_settings(cls) -> "AdminVaultFactoryUseCase":
        s = get_settings()
        vault_repo = VaultFactoryRepositoryMongoDB()

        try:
            vault_repo.ensure_indexes()
        except Exception:
            pass

        return cls(
            txs=TxService(s.RPC_URL_DEFAULT),
            vault_repo=vault_repo,
        )

    def _ensure_can_create(self, latest_status: FactoryStatus | None) -> None:
        if latest_status is None:
            return
        if latest_status == FactoryStatus.ARCHIVED_CAN_CREATE_NEW:
            return
        raise ValueError("A factory already exists and does not allow creating a new one.")

    @staticmethod
    def _serialize_record(ent: VaultFactoryEntity | None) -> dict | None:
        if ent is None:
            return None

        status = ent.status.value if hasattr(ent.status, "value") else ent.status
        return {
            "chain": ent.chain,
            "address": ent.address,
            "status": status,
            "tx_hash": getattr(ent, "tx_hash", None),
            "owner": getattr(ent, "owner", None),
            "strategy_registry": getattr(ent, "strategy_registry", None),
            "executor": getattr(ent, "executor", None),
            "fee_collector": getattr(ent, "fee_collector", None),
            "default_cooldown_sec": getattr(ent, "default_cooldown_sec", None),
            "default_max_slippage_bps": getattr(ent, "default_max_slippage_bps", None),
            "default_allow_swap": getattr(ent, "default_allow_swap", None),
            "created_at": getattr(ent, "created_at", None),
            "created_at_iso": getattr(ent, "created_at_iso", None),
            "updated_at": getattr(ent, "updated_at", None),
            "updated_at_iso": getattr(ent, "updated_at_iso", None),
        }

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
            owner=initial_owner,
            strategy_registry=strategy_registry,
            executor=executor,
            fee_collector=fee_collector,
            default_cooldown_sec=int(default_cooldown_sec),
            default_max_slippage_bps=int(default_max_slippage_bps),
            default_allow_swap=bool(default_allow_swap),
        )
        self.vault_repo.insert(ent)

        active = self.vault_repo.get_active(chain=chain)
        if not active or active.address.lower() != ent.address.lower():
            raise RuntimeError("Factory deployed but failed to persist as ACTIVE in MongoDB.")

        res["result"] = self._serialize_record(active)
        return res

    def list_vault_factories(
        self,
        *,
        chain: str,
        limit: int = 50,
    ) -> dict:
        chain = (chain or "").strip().lower()
        if not chain:
            raise ValueError("chain is required")

        limit = max(1, int(limit))

        active = self.vault_repo.get_active(chain=chain)
        history = self.vault_repo.list_all(chain=chain, limit=limit)

        return {
            "ok": True,
            "message": "Vault factory records fetched successfully.",
            "result": {
                "active": self._serialize_record(active),
                "history": [self._serialize_record(item) for item in history],
            },
        }