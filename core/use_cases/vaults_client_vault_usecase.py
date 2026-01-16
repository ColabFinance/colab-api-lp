from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any, Dict, Optional

from web3 import Web3
from web3.contract.contract import Contract

from adapters.chain.strategy_registry import StrategyRegistryAdapter
from adapters.chain.vault_factory import VaultFactoryAdapter
from adapters.external.database.mongo_client import get_mongo_db
from adapters.external.database.vault_client_registry_repository_mongodb import VaultRegistryRepositoryMongoDB
from config import get_settings
from adapters.chain.client_vault import ClientVaultAdapter
from core.domain.entities.vault_client_registry_entity import SwapPoolRef, VaultConfig, VaultOnchainInfo, VaultRegistryEntity
from core.domain.repositories.vault_client_registry_repository_interface import VaultRegistryRepositoryInterface
from core.services.tx_service import TxService
from core.services.utils import to_json_safe
from core.services.vault_status_service import VaultStatusService

def _is_address_like(s: str) -> bool:
    return isinstance(s, str) and s.startswith("0x") and len(s) == 42


def _norm_owner_prefix(owner: str) -> str:
    s = (owner or "").strip()
    if s.startswith("0x") and len(s) >= 7:
        return s[2:7].lower()
    return (s[:5] or "owner").lower()


def _norm_slug(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "")


@dataclass
class VaultClientVaultUseCase:
    """
    ClientVault creation + Mongo registry insertion.

    Responsibilities:
    - Validate strategy exists/active on StrategyRegistry
    - Execute VaultFactory.createClientVault signed by backend PK
    - Resolve created vault address
    - Read status to capture on-chain snapshot
    - Generate alias (owner5-par-dex-chain-N)
    - Insert into vault_registry collection using entity + repo
    """

    w3: Web3
    registry: StrategyRegistryAdapter
    factory: VaultFactoryAdapter
    txs: TxService
    status_svc: VaultStatusService
    vault_registry_repo: VaultRegistryRepositoryInterface

    @classmethod
    def from_settings(cls) -> "VaultClientVaultUseCase":
        s = get_settings()
        w3 = Web3(Web3.HTTPProvider(s.RPC_URL_DEFAULT))
        registry = StrategyRegistryAdapter(w3=w3, address=s.STRATEGY_REGISTRY_ADDRESS)
        factory = VaultFactoryAdapter(w3=w3, address=s.VAULT_FACTORY_ADDRESS)
        status_svc = VaultStatusService(w3=w3)
        txs = TxService(s.RPC_URL_DEFAULT)

        db = get_mongo_db()
        repo = VaultRegistryRepositoryMongoDB(db[VaultRegistryRepositoryMongoDB.COLLECTION])
        repo.ensure_indexes()

        return cls(w3=w3, registry=registry, factory=factory, txs=txs, status_svc=status_svc, vault_registry_repo=repo)

    # ---------- internal normalization ----------

    def _normalize_tx_result(self, tx_any: Any) -> Dict[str, Any]:
        """
        Ensure tx result is a dict with receipt available.

        Accepts:
        - dict from TxService.send(...)
        - str tx_hash (legacy / accidental return shape)
        """
        if isinstance(tx_any, dict):
            return tx_any

        if isinstance(tx_any, str) and tx_any.startswith("0x"):
            tx_hash = tx_any
            rcpt = dict(self.w3.eth.wait_for_transaction_receipt(tx_hash))
            status = int(rcpt.get("status", 0))
            return to_json_safe(
                {
                    "tx_hash": tx_hash,
                    "broadcasted": True,
                    "status": status,
                    "receipt": rcpt,
                    "gas": {},
                    "budget": {},
                    "result": {},
                    "ts": datetime.now(UTC).isoformat(),
                }
            )

        raise ValueError(f"Invalid tx result returned by TxService: {type(tx_any)}")
    
    # ---------- public ----------

    def create_client_vault_and_register(
        self,
        *,
        strategy_id: int,
        owner: str,
        chain: str,
        dex: str,
        par_token: str,
        name: str,
        description: Optional[str],
        config_in: Dict[str, Any],
        gas_strategy: str = "buffered",
    ) -> Dict[str, Any]:
        if not _is_address_like(owner):
            raise ValueError("Invalid owner address")
        
        # 1) validate
        if not self.registry.is_strategy_active(owner=owner, strategy_id=strategy_id):
            raise ValueError("Strategy not active or does not exist on-chain for this owner.")

        chain = _norm_slug(chain)
        dex = _norm_slug(dex)
        par_token_norm = _norm_slug(par_token).upper() if par_token else ""

        if not chain:
            raise ValueError("chain is required")
        if not dex:
            raise ValueError("dex is required")
        if not par_token_norm:
            raise ValueError("par_token is required")
        if not (name or "").strip():
            raise ValueError("name is required")

        # sanity: chain id
        chain_id = self.w3.eth.chain_id

        # sanity: contrato tem bytecode?
        reg_code = self.w3.eth.get_code(Web3.to_checksum_address(self.registry.address))
        fac_code = self.w3.eth.get_code(Web3.to_checksum_address(self.factory.address))

        if not reg_code or reg_code == b"":
            raise ValueError(f"StrategyRegistry has no code on this RPC. chain_id={chain_id} address={self.registry.address}")

        if not fac_code or fac_code == b"":
            raise ValueError(f"VaultFactory has no code on this RPC. chain_id={chain_id} address={self.factory.address}")

        # 2) on-chain create
        fn = self.factory.fn_create_client_vault(strategy_id=strategy_id, owner_override=owner)
        tx_any = self.txs.send(fn, wait=True, gas_strategy=gas_strategy)
        
        tx_res = self._normalize_tx_result(tx_any)
        
        # 3) resolve vault address
        vault_addr = self._resolve_created_vault_address(tx_res)
        if not vault_addr:
            raise ValueError("Could not resolve created vault address from receipt")

        # 4) alias generation
        owner_prefix = _norm_owner_prefix(owner)
        n_existing = self.vault_registry_repo.count_alias_prefix(
            chain=chain,
            dex=dex,
            owner_prefix=owner_prefix,
            par_token=par_token_norm.lower(),
        )
        # begin with 1
        idx = int(n_existing) + 1
        alias = f"{owner_prefix}-{par_token_norm.lower()}-{dex}-{chain}-{idx}"

        # 5) build entity with old structure + new fields
        cfg = VaultConfig(
            address=vault_addr,
            adapter=str(config_in.get("adapter", "")).strip(),
            pool=str(config_in.get("pool", "")).strip(),
            nfpm=str(config_in.get("nfpm", "")).strip(),
            gauge=(str(config_in.get("gauge")).strip() if config_in.get("gauge") else None),
            rpc_url=str(config_in.get("rpc_url", "")).strip(),
            version=str(config_in.get("version", "")).strip(),
            swap_pools={
                k: SwapPoolRef.model_validate(v) for k, v in (config_in.get("swap_pools") or {}).items()
            },
        )

        entity = VaultRegistryEntity(
            dex=dex,
            alias=alias,
            config=cfg,
            is_active=False,

            chain=chain,
            owner=Web3.to_checksum_address(owner),
            par_token=par_token_norm,

            name=name.strip(),
            description=(description.strip() if description else None),

            strategy_id=int(strategy_id)
        )

        saved = self.vault_registry_repo.insert(entity)

        # 7) response for controller
        return {
            "tx": tx_res,
            "vault_address": vault_addr,
            "alias": alias,
            "mongo_id": saved.id,
            "entity": saved,
        }

    # ---------- internal ----------

    def _as_receipt_dict(self, raw: Any) -> dict:
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return {}
            try:
                v = json.loads(s)
                return v if isinstance(v, dict) else {}
            except Exception:
                return {}
        return {}

    def _resolve_created_vault_address(self, tx_res: Dict[str, Any]) -> Optional[str]:
        """
        Best-effort:
        - Try decode event from receipt logs if ABI supports it
        - Fallback: attempt to find any address-like in logs topics/data (weak)
        """
        receipt = self._as_receipt_dict(tx_res.get("receipt"))
        logs = receipt.get("logs") or []
        if not logs:
            return None

        # 1) best: try factory contract events
        try:
            # VaultFactoryAdapter likely has self.contract
            c: Contract = self.factory.contract  # type: ignore[attr-defined]
            # Try common event names
            for ev_name in ("ClientVaultDeployed"):
                ev = getattr(c.events, ev_name, None)
                if ev is None:
                    continue
                try:
                    decoded = ev().process_receipt(receipt)
                    if decoded:
                        print("decoded", decoded)
                        args = decoded[0].get("args") or {}
                        # common arg keys
                        for k in ("vault", "clientVault", "vaultAddress", "addr"):
                            v = args.get(k)
                            if _is_address_like(v):
                                return Web3.to_checksum_address(v)
                except Exception:
                    continue
        except Exception:
            pass

        # 2) weak fallback: scan log 'address' fields (contract emitting logs)
        # (not ideal, but sometimes factory emits with vault address as log.address)
        for lg in logs:
            print("lg",lg)
            addr = lg.get("address")
            if _is_address_like(addr):
                # This will often be the factory address, not the vault. So only accept if different.
                if Web3.to_checksum_address(addr) != Web3.to_checksum_address(self.factory.address):  # type: ignore
                    return Web3.to_checksum_address(addr)

        return None

    
    def _resolve_vault_address(self, alias_or_address: str) -> str:
        if _is_address_like(alias_or_address):
            return Web3.to_checksum_address(alias_or_address)
        raise ValueError("Unknown vault alias (send the vault address in the path)")

    # -------- reads --------

    def get_status(self, *, alias_or_address: str) -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        return self.status_svc.compute(vault_addr)

