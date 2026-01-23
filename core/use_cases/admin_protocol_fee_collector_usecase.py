from __future__ import annotations

from dataclasses import dataclass

from adapters.chain.artifacts import load_contract_from_out
from adapters.external.database.protocol_fee_collector_repository_mongodb import ProtocolFeeCollectorRepositoryMongoDB
from config import get_settings
from core.domain.entities.protocol_fee_collector_entity import ProtocolFeeCollectorEntity
from core.domain.enums.factory_enums import FactoryStatus
from core.domain.enums.tx_enums import GasStrategy
from core.domain.repositories.protocol_fee_collector_repository_interface import ProtocolFeeCollectorRepository
from core.services.tx_service import TxService


@dataclass
class AdminProtocolFeeCollectorUseCase:
    """
    Admin-only use case responsible for deploying ProtocolFeeCollector on-chain
    and persisting deployment records in MongoDB.
    """

    txs: TxService
    repo: ProtocolFeeCollectorRepository

    @classmethod
    def from_settings(cls) -> "AdminProtocolFeeCollectorUseCase":
        s = get_settings()
        repo = ProtocolFeeCollectorRepositoryMongoDB()

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
        raise ValueError("A protocol fee collector already exists and does not allow creating a new one.")

    def create_protocol_fee_collector(
        self,
        *,
        chain: str,
        initial_owner: str,
        treasury: str,
        protocol_fee_bps: int,
        gas_strategy: GasStrategy = GasStrategy.BUFFERED,
    ) -> dict:
        """
        Deploy ProtocolFeeCollector on-chain and persist the deployment record in MongoDB.
        """
        chain = (chain or "").strip().lower()
        if not chain:
            raise ValueError("chain is required")

        if protocol_fee_bps < 0 or protocol_fee_bps > 5000:
            raise ValueError("protocol_fee_bps must be between 0 and 5000 (inclusive).")

        latest = self.repo.get_latest(chain=chain)
        self._ensure_can_create(latest.status if latest else None)

        abi, bytecode = load_contract_from_out("vaults", "ProtocolFeeCollector.json")

        res = self.txs.deploy(
            abi=abi,
            bytecode=bytecode,
            ctor_args=(initial_owner, treasury, int(protocol_fee_bps)),
            wait=True,
            gas_strategy=gas_strategy,
        )

        addr = (res.get("result") or {}).get("contract_address")
        if not addr:
            raise RuntimeError("Deploy succeeded but contract_address is missing.")

        self.repo.set_all_status(chain=chain, status=FactoryStatus.ARCHIVED_CAN_CREATE_NEW)

        ent = ProtocolFeeCollectorEntity(
            chain=chain,
            address=str(addr),
            status=FactoryStatus.ACTIVE,
            tx_hash=res.get("tx_hash"),
            treasury=treasury,
            protocol_fee_bps=int(protocol_fee_bps),
        )
        self.repo.insert(ent)

        active = self.repo.get_active(chain=chain)
        if not active or active.address.lower() != ent.address.lower():
            raise RuntimeError("ProtocolFeeCollector deployed but failed to persist as ACTIVE in MongoDB.")

        res["result"] = {
            "chain": ent.chain,
            "address": ent.address,
            "status": ent.status.value,
            "created_at": ent.created_at_iso,
            "treasury": ent.treasury,
            "protocol_fee_bps": ent.protocol_fee_bps,
        }
        return res
