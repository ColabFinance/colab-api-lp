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

    @staticmethod
    def _serialize_record(ent: ProtocolFeeCollectorEntity | None) -> dict | None:
        if ent is None:
            return None

        status = ent.status.value if hasattr(ent.status, "value") else ent.status
        return {
            "chain": ent.chain,
            "address": ent.address,
            "status": status,
            "tx_hash": getattr(ent, "tx_hash", None),
            "owner": getattr(ent, "owner", None),
            "treasury": getattr(ent, "treasury", None),
            "protocol_fee_bps": getattr(ent, "protocol_fee_bps", None),
            "created_at": getattr(ent, "created_at", None),
            "created_at_iso": getattr(ent, "created_at_iso", None),
            "updated_at": getattr(ent, "updated_at", None),
            "updated_at_iso": getattr(ent, "updated_at_iso", None),
        }

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
            owner=initial_owner,
            treasury=treasury,
            protocol_fee_bps=int(protocol_fee_bps),
        )
        self.repo.insert(ent)

        active = self.repo.get_active(chain=chain)
        if not active or active.address.lower() != ent.address.lower():
            raise RuntimeError("ProtocolFeeCollector deployed but failed to persist as ACTIVE in MongoDB.")

        res["result"] = self._serialize_record(active)
        return res

    def list_protocol_fee_collectors(
        self,
        *,
        chain: str,
        limit: int = 50,
    ) -> dict:
        chain = (chain or "").strip().lower()
        if not chain:
            raise ValueError("chain is required")

        limit = max(1, int(limit))

        active = self.repo.get_active(chain=chain)
        history = self.repo.list_all(chain=chain, limit=limit)

        return {
            "ok": True,
            "message": "Protocol fee collector records fetched successfully.",
            "result": {
                "active": self._serialize_record(active),
                "history": [self._serialize_record(item) for item in history],
            },
        }