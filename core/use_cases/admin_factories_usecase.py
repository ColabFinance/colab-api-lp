from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from adapters.external.database.strategy_factory_repository_mongodb import StrategyRepositoryMongoDB
from adapters.external.database.vault_factory_repository_mongodb import VaultFactoryRepositoryMongoDB
from config import get_settings
from core.domain.entities.factory_entities import (
    FactoryStatus,
    StrategyFactoryEntity,
    VaultFactoryEntity,
)
from core.domain.repositories.strategy_factory_repository_interface import StrategyRepository
from core.domain.repositories.vault_factory_repository_interface import VaultFactoryRepository
from core.services.tx_service import TxService
from adapters.chain.artifacts import load_abi_json, load_artifact, artifact_bytecode


@dataclass
class AdminFactoriesUseCase:
    """
    Admin flow:
      - Deploy StrategyFactory/VaultFactory on-chain
      - If mined successfully, persist address in Mongo
      - Mark the new one ACTIVE, and archive previous ones (ARCHIVED_CAN_CREATE_NEW)
    """

    txs: TxService
    strategy_repo: StrategyRepository
    vault_repo: VaultFactoryRepository

    @classmethod
    def from_settings(cls) -> "AdminFactoriesUseCase":
        s = get_settings()
        return cls(
            txs=TxService(s.RPC_URL_DEFAULT),
            strategy_repo=StrategyRepositoryMongoDB(),
            vault_repo=VaultFactoryRepositoryMongoDB(),
        )

    def _ensure_can_create(self, latest_status: FactoryStatus | None) -> None:
        if latest_status is None:
            return
        if latest_status == FactoryStatus.ARCHIVED_CAN_CREATE_NEW:
            return
        raise ValueError("A factory already exists and does not allow creating a new one.")

    def create_strategy_factory(self, *, gas_strategy: str = "buffered") -> dict:
        latest = self.strategy_repo.get_latest()
        self._ensure_can_create(latest.status if latest else None)

        # ABI from libs/abi
        # TODO: adjust filename/folder to match your actual contract ABI json name.
        abi = load_abi_json("factory", "StrategyFactory.json")

        # bytecode from out artifact
        # TODO: adjust artifact path to match your compilation output
        art = load_artifact("StrategyFactory.sol", "StrategyFactory.json")
        bytecode = artifact_bytecode(art)

        res = self.txs.deploy(
            abi=abi,
            bytecode=bytecode,
            ctor_args=(),
            wait=True,
            gas_strategy=gas_strategy,
        )

        addr = (res.get("result") or {}).get("contract_address")
        if not addr:
            raise RuntimeError("Deploy succeeded but contract_address is missing.")

        # Persist ONLY after success
        self.strategy_repo.set_all_status(status=FactoryStatus.ARCHIVED_CAN_CREATE_NEW)
        ent = StrategyFactoryEntity(
            address=str(addr),
            status=FactoryStatus.ACTIVE,
            created_at=datetime.now(UTC),
            tx_hash=res.get("tx_hash"),
        )
        self.strategy_repo.insert(ent)

        res["result"] = {
            "address": ent.address,
            "status": ent.status.value,
            "created_at": ent.created_at.isoformat(),
        }
        return res

    def create_vault_factory(self, *, gas_strategy: str = "buffered") -> dict:
        latest = self.vault_repo.get_latest()
        self._ensure_can_create(latest.status if latest else None)

        # ABI from libs/abi
        # TODO: adjust filename/folder to match your actual contract ABI json name.
        abi = load_abi_json("factory", "VaultFactory.json")

        # bytecode from out artifact
        # TODO: adjust artifact path to match your compilation output
        art = load_artifact("VaultFactory.sol", "VaultFactory.json")
        bytecode = artifact_bytecode(art)

        res = self.txs.deploy(
            abi=abi,
            bytecode=bytecode,
            ctor_args=(),
            wait=True,
            gas_strategy=gas_strategy,
        )

        addr = (res.get("result") or {}).get("contract_address")
        if not addr:
            raise RuntimeError("Deploy succeeded but contract_address is missing.")

        self.vault_repo.set_all_status(status=FactoryStatus.ARCHIVED_CAN_CREATE_NEW)
        ent = VaultFactoryEntity(
            address=str(addr),
            status=FactoryStatus.ACTIVE,
            created_at=datetime.now(UTC),
            tx_hash=res.get("tx_hash"),
        )
        self.vault_repo.insert(ent)

        res["result"] = {
            "address": ent.address,
            "status": ent.status.value,
            "created_at": ent.created_at.isoformat(),
        }
        return res
