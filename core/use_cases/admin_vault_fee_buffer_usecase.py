from __future__ import annotations

from dataclasses import dataclass

from adapters.chain.artifacts import load_contract_from_out
from adapters.external.database.vault_fee_buffer_repository_mongodb import VaultFeeBufferRepositoryMongoDB
from config import get_settings
from core.domain.entities.vault_fee_buffer_entity import VaultFeeBufferEntity
from core.domain.enums.factory_enums import FactoryStatus
from core.domain.enums.tx_enums import GasStrategy
from core.domain.repositories.vault_fee_buffer_repository_interface import VaultFeeBufferRepository
from core.services.tx_service import TxService


@dataclass
class AdminVaultFeeBufferUseCase:
    """
    Admin-only use case responsible for deploying VaultFeeBuffer on-chain
    and persisting deployment records in MongoDB.
    """

    txs: TxService
    repo: VaultFeeBufferRepository

    @classmethod
    def from_settings(cls) -> "AdminVaultFeeBufferUseCase":
        s = get_settings()
        repo = VaultFeeBufferRepositoryMongoDB()

        try:
            repo.ensure_indexes()
        except Exception:
            pass

        return cls(
            txs=TxService(s.RPC_URL_DEFAULT),
            repo=repo,
        )

    def _ensure_can_create(self, latest_status: FactoryStatus | None) -> None:
        if latest_status is None:
            return
        if latest_status == FactoryStatus.ARCHIVED_CAN_CREATE_NEW:
            return
        raise ValueError("A VaultFeeBuffer already exists and does not allow creating a new one.")

    def create_vault_fee_buffer(
        self,
        *,
        chain: str,
        initial_owner: str,
        gas_strategy: GasStrategy = GasStrategy.BUFFERED,
    ) -> dict:
        chain = (chain or "").strip().lower()
        if not chain:
            raise ValueError("chain is required")

        latest = self.repo.get_latest(chain=chain)
        self._ensure_can_create(latest.status if latest else None)

        abi, bytecode = load_contract_from_out("vaults", "VaultFeeBuffer.json")

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

        self.repo.set_all_status(chain=chain, status=FactoryStatus.ARCHIVED_CAN_CREATE_NEW)

        ent = VaultFeeBufferEntity(
            chain=chain,
            address=str(addr),
            status=FactoryStatus.ACTIVE,
            tx_hash=res.get("tx_hash"),
            owner=initial_owner,
        )
        self.repo.insert(ent)

        active = self.repo.get_active(chain=chain)
        if not active or active.address.lower() != ent.address.lower():
            raise RuntimeError("VaultFeeBuffer deployed but failed to persist as ACTIVE in MongoDB.")

        res["result"] = {
            "chain": ent.chain,
            "address": ent.address,
            "status": ent.status,
            "created_at": ent.created_at_iso,
            "owner": ent.owner,
        }
        return res
