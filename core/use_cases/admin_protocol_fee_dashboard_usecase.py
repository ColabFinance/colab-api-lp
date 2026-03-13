from __future__ import annotations

from dataclasses import dataclass

from adapters.external.database.protocol_fee_collector_repository_mongodb import (
    ProtocolFeeCollectorRepositoryMongoDB,
)
from adapters.external.database.protocol_fee_dashboard_repository_mongodb import (
    ProtocolFeeTrackedTokenRepositoryMongoDB,
    ProtocolFeeWithdrawalRepositoryMongoDB,
)


@dataclass
class AdminProtocolFeeDashboardUseCase:
    collector_repo: ProtocolFeeCollectorRepositoryMongoDB
    tracked_token_repo: ProtocolFeeTrackedTokenRepositoryMongoDB
    withdrawal_repo: ProtocolFeeWithdrawalRepositoryMongoDB

    @classmethod
    def from_settings(cls) -> "AdminProtocolFeeDashboardUseCase":
        return cls(
            collector_repo=ProtocolFeeCollectorRepositoryMongoDB(),
            tracked_token_repo=ProtocolFeeTrackedTokenRepositoryMongoDB(),
            withdrawal_repo=ProtocolFeeWithdrawalRepositoryMongoDB(),
        )

    @staticmethod
    def _serialize_contract_record(ent) -> dict | None:
        if ent is None:
            return None

        status = ent.status.value if hasattr(ent.status, "value") else ent.status
        return {
            "chain": getattr(ent, "chain", None),
            "address": getattr(ent, "address", None),
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

    def _resolve_contract_address(self, *, chain: str, contract_address: str | None) -> str:
        if contract_address:
            return contract_address.strip().lower()

        active = self.collector_repo.get_active(chain=chain)
        if not active or not getattr(active, "address", None):
            raise ValueError("No active ProtocolFeeCollector was found for the selected chain.")

        return str(active.address).strip().lower()

    def list_dashboard(
        self,
        *,
        chain: str,
        tracked_limit: int = 300,
        withdrawal_limit: int = 100,
    ) -> dict:
        active = self.collector_repo.get_active(chain=chain)
        contract = self._serialize_contract_record(active)

        tracked_tokens: list[dict] = []
        withdrawals: list[dict] = []

        if contract and contract.get("address"):
            tracked_tokens = self.tracked_token_repo.list_by_contract(
                chain=chain,
                contract_address=contract["address"],
                limit=tracked_limit,
            )
            withdrawals = self.withdrawal_repo.list_by_contract(
                chain=chain,
                contract_address=contract["address"],
                limit=withdrawal_limit,
            )

        return {
            "ok": True,
            "message": "Protocol fee dashboard fetched successfully.",
            "data": {
                "contract": contract,
                "tracked_tokens": tracked_tokens,
                "withdrawals": withdrawals,
            },
        }

    def track_token(
        self,
        *,
        chain: str,
        contract_address: str | None,
        token_address: str,
        label: str | None,
        created_by: str | None,
    ) -> dict:
        resolved_contract = self._resolve_contract_address(chain=chain, contract_address=contract_address)

        self.tracked_token_repo.upsert(
            chain=chain,
            contract_address=resolved_contract,
            token_address=token_address,
            label=label,
            created_by=created_by,
        )

        return self.list_dashboard(chain=chain)

    def record_withdrawal(
        self,
        *,
        chain: str,
        contract_address: str | None,
        tx_hash: str,
        token_address: str,
        token_symbol: str | None,
        amount_raw: str,
        amount_label: str | None,
        destination: str,
        status: str,
        created_by: str | None,
    ) -> dict:
        resolved_contract = self._resolve_contract_address(chain=chain, contract_address=contract_address)

        self.withdrawal_repo.upsert(
            chain=chain,
            contract_address=resolved_contract,
            tx_hash=tx_hash,
            token_address=token_address,
            token_symbol=token_symbol,
            amount_raw=amount_raw,
            amount_label=amount_label,
            destination=destination,
            status=status,
            created_by=created_by,
        )

        self.tracked_token_repo.upsert(
            chain=chain,
            contract_address=resolved_contract,
            token_address=token_address,
            label=token_symbol,
            created_by=created_by,
        )

        return self.list_dashboard(chain=chain)