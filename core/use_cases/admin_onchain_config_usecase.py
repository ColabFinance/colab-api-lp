from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from adapters.external.database.admin_onchain_config_repository_mongodb import (
    ProtocolFeeCollectorConfigRepositoryMongoDB,
    ProtocolFeeCollectorReporterRepositoryMongoDB,
    StrategyRegistryAllowlistRepositoryMongoDB,
    VaultFactoryConfigRepositoryMongoDB,
    VaultFeeBufferDepositorRepositoryMongoDB,
)
from adapters.external.database.protocol_fee_collector_repository_mongodb import (
    ProtocolFeeCollectorRepositoryMongoDB,
)
from adapters.external.database.strategy_registry_repository_mongodb import (
    StrategyRepositoryMongoDB,
)
from adapters.external.database.vault_factory_repository_mongodb import (
    VaultFactoryRepositoryMongoDB,
)
from adapters.external.database.vault_fee_buffer_repository_mongodb import (
    VaultFeeBufferRepositoryMongoDB,
)


@dataclass
class AdminOnchainConfigUseCase:
    strategy_registry_repo: StrategyRepositoryMongoDB
    vault_factory_repo: VaultFactoryRepositoryMongoDB
    protocol_fee_collector_repo: ProtocolFeeCollectorRepositoryMongoDB
    vault_fee_buffer_repo: VaultFeeBufferRepositoryMongoDB

    strategy_allowlist_repo: StrategyRegistryAllowlistRepositoryMongoDB
    vault_factory_config_repo: VaultFactoryConfigRepositoryMongoDB
    protocol_fee_config_repo: ProtocolFeeCollectorConfigRepositoryMongoDB
    protocol_fee_reporter_repo: ProtocolFeeCollectorReporterRepositoryMongoDB
    vault_fee_buffer_depositor_repo: VaultFeeBufferDepositorRepositoryMongoDB

    @classmethod
    def from_settings(cls) -> "AdminOnchainConfigUseCase":
        return cls(
            strategy_registry_repo=StrategyRepositoryMongoDB(),
            vault_factory_repo=VaultFactoryRepositoryMongoDB(),
            protocol_fee_collector_repo=ProtocolFeeCollectorRepositoryMongoDB(),
            vault_fee_buffer_repo=VaultFeeBufferRepositoryMongoDB(),
            strategy_allowlist_repo=StrategyRegistryAllowlistRepositoryMongoDB(),
            vault_factory_config_repo=VaultFactoryConfigRepositoryMongoDB(),
            protocol_fee_config_repo=ProtocolFeeCollectorConfigRepositoryMongoDB(),
            protocol_fee_reporter_repo=ProtocolFeeCollectorReporterRepositoryMongoDB(),
            vault_fee_buffer_depositor_repo=VaultFeeBufferDepositorRepositoryMongoDB(),
        )

    @staticmethod
    def _serialize_contract_record(ent: Any | None) -> dict | None:
        if ent is None:
            return None

        status = ent.status.value if hasattr(ent.status, "value") else ent.status
        return {
            "chain": getattr(ent, "chain", None),
            "address": getattr(ent, "address", None),
            "status": status,
            "tx_hash": getattr(ent, "tx_hash", None),
            "owner": getattr(ent, "owner", None),
            "created_at": getattr(ent, "created_at", None),
            "created_at_iso": getattr(ent, "created_at_iso", None),
            "updated_at": getattr(ent, "updated_at", None),
            "updated_at_iso": getattr(ent, "updated_at_iso", None),
        }

    @staticmethod
    def _resolve_contract_address(active_record: Any | None, explicit_contract_address: str | None) -> str:
        if explicit_contract_address:
            return explicit_contract_address.strip().lower()

        if active_record and getattr(active_record, "address", None):
            return str(active_record.address).strip().lower()

        raise ValueError("No active contract record was found for the selected chain.")

    def list_strategy_registry_state(self, *, chain: str, limit: int = 500) -> dict:
        active = self.strategy_registry_repo.get_active(chain=chain)
        contract = self._serialize_contract_record(active)

        routers: list[dict] = []
        adapters: list[dict] = []

        if contract and contract.get("address"):
            routers = self.strategy_allowlist_repo.list_by_contract(
                chain=chain,
                contract_address=contract["address"],
                entry_type="router",
                limit=limit,
            )
            adapters = self.strategy_allowlist_repo.list_by_contract(
                chain=chain,
                contract_address=contract["address"],
                entry_type="adapter",
                limit=limit,
            )

        return {
            "ok": True,
            "message": "StrategyRegistry admin state fetched successfully.",
            "data": {
                "contract": contract,
                "routers": routers,
                "adapters": adapters,
            },
        }

    def save_strategy_router_state(
        self,
        *,
        chain: str,
        contract_address: str | None,
        address: str,
        name: str,
        allowed: bool,
        tx_hash: str | None,
        updated_by: str | None,
    ) -> dict:
        active = self.strategy_registry_repo.get_active(chain=chain)
        resolved_contract = self._resolve_contract_address(active, contract_address)

        self.strategy_allowlist_repo.upsert(
            chain=chain,
            contract_address=resolved_contract,
            entry_type="router",
            address=address,
            label=name,
            adapter_type=None,
            desired_allowed=allowed,
            tx_hash=tx_hash,
            updated_by=updated_by,
        )

        return self.list_strategy_registry_state(chain=chain)

    def save_strategy_adapter_state(
        self,
        *,
        chain: str,
        contract_address: str | None,
        address: str,
        label: str,
        adapter_type: str | None,
        allowed: bool,
        tx_hash: str | None,
        updated_by: str | None,
    ) -> dict:
        active = self.strategy_registry_repo.get_active(chain=chain)
        resolved_contract = self._resolve_contract_address(active, contract_address)

        self.strategy_allowlist_repo.upsert(
            chain=chain,
            contract_address=resolved_contract,
            entry_type="adapter",
            address=address,
            label=label,
            adapter_type=adapter_type,
            desired_allowed=allowed,
            tx_hash=tx_hash,
            updated_by=updated_by,
        )

        return self.list_strategy_registry_state(chain=chain)

    def list_vault_factory_state(self, *, chain: str) -> dict:
        active = self.vault_factory_repo.get_active(chain=chain)
        contract = self._serialize_contract_record(active)
        saved_config = None

        if contract and contract.get("address"):
            saved_config = self.vault_factory_config_repo.get_by_contract(
                chain=chain,
                contract_address=contract["address"],
            )

        return {
            "ok": True,
            "message": "VaultFactory admin state fetched successfully.",
            "data": {
                "contract": contract,
                "saved_config": saved_config,
            },
        }

    def save_vault_factory_state(
        self,
        *,
        chain: str,
        contract_address: str | None,
        executor: str,
        fee_collector: str,
        default_cooldown_sec: int,
        default_max_slippage_bps: int,
        default_allow_swap: bool,
        tx_hash: str | None,
        updated_by: str | None,
    ) -> dict:
        active = self.vault_factory_repo.get_active(chain=chain)
        resolved_contract = self._resolve_contract_address(active, contract_address)

        self.vault_factory_config_repo.upsert(
            chain=chain,
            contract_address=resolved_contract,
            executor=executor,
            fee_collector=fee_collector,
            default_cooldown_sec=default_cooldown_sec,
            default_max_slippage_bps=default_max_slippage_bps,
            default_allow_swap=default_allow_swap,
            tx_hash=tx_hash,
            updated_by=updated_by,
        )

        return self.list_vault_factory_state(chain=chain)

    def list_protocol_fee_collector_state(self, *, chain: str, limit: int = 500) -> dict:
        active = self.protocol_fee_collector_repo.get_active(chain=chain)
        contract = self._serialize_contract_record(active)
        saved_config = None
        reporters: list[dict] = []

        if contract and contract.get("address"):
            saved_config = self.protocol_fee_config_repo.get_by_contract(
                chain=chain,
                contract_address=contract["address"],
            )
            reporters = self.protocol_fee_reporter_repo.list_by_contract(
                chain=chain,
                contract_address=contract["address"],
                limit=limit,
            )

        return {
            "ok": True,
            "message": "ProtocolFeeCollector admin state fetched successfully.",
            "data": {
                "contract": contract,
                "saved_config": saved_config,
                "reporters": reporters,
            },
        }

    def save_protocol_fee_collector_state(
        self,
        *,
        chain: str,
        contract_address: str | None,
        treasury: str,
        protocol_fee_bps: int,
        tx_hash: str | None,
        updated_by: str | None,
    ) -> dict:
        active = self.protocol_fee_collector_repo.get_active(chain=chain)
        resolved_contract = self._resolve_contract_address(active, contract_address)

        self.protocol_fee_config_repo.upsert(
            chain=chain,
            contract_address=resolved_contract,
            treasury=treasury,
            protocol_fee_bps=protocol_fee_bps,
            tx_hash=tx_hash,
            updated_by=updated_by,
        )

        return self.list_protocol_fee_collector_state(chain=chain)

    def save_protocol_fee_reporter_state(
        self,
        *,
        chain: str,
        contract_address: str | None,
        reporter: str,
        allowed: bool,
        tx_hash: str | None,
        updated_by: str | None,
    ) -> dict:
        active = self.protocol_fee_collector_repo.get_active(chain=chain)
        resolved_contract = self._resolve_contract_address(active, contract_address)

        self.protocol_fee_reporter_repo.upsert(
            chain=chain,
            contract_address=resolved_contract,
            reporter=reporter,
            desired_allowed=allowed,
            tx_hash=tx_hash,
            updated_by=updated_by,
        )

        return self.list_protocol_fee_collector_state(chain=chain)

    def list_vault_fee_buffer_state(self, *, chain: str, limit: int = 500) -> dict:
        active = self.vault_fee_buffer_repo.get_active(chain=chain)
        contract = self._serialize_contract_record(active)
        depositors: list[dict] = []

        if contract and contract.get("address"):
            depositors = self.vault_fee_buffer_depositor_repo.list_by_contract(
                chain=chain,
                contract_address=contract["address"],
                limit=limit,
            )

        return {
            "ok": True,
            "message": "VaultFeeBuffer admin state fetched successfully.",
            "data": {
                "contract": contract,
                "depositors": depositors,
            },
        }

    def save_vault_fee_buffer_depositor_state(
        self,
        *,
        chain: str,
        contract_address: str | None,
        depositor: str,
        label: str | None,
        allowed: bool,
        tx_hash: str | None,
        updated_by: str | None,
    ) -> dict:
        active = self.vault_fee_buffer_repo.get_active(chain=chain)
        resolved_contract = self._resolve_contract_address(active, contract_address)

        self.vault_fee_buffer_depositor_repo.upsert(
            chain=chain,
            contract_address=resolved_contract,
            depositor=depositor,
            label=label,
            desired_allowed=allowed,
            tx_hash=tx_hash,
            updated_by=updated_by,
        )

        return self.list_vault_fee_buffer_state(chain=chain)