from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any, Dict, Optional

from web3 import Web3
from web3.contract.contract import Contract
from web3.exceptions import ContractLogicError, BadFunctionCallOutput

from adapters.chain.client_vault import ClientVaultAdapter
from adapters.chain.strategy_registry import StrategyRegistryAdapter
from adapters.chain.vault_factory import VaultFactoryAdapter
from adapters.external.database.adapter_registry_repository_mongodb import AdapterRegistryRepositoryMongoDB
from adapters.external.database.dex_pool_repository_mongodb import DexPoolRepositoryMongoDB
from adapters.external.database.dex_registry_repository_mongodb import DexRegistryRepositoryMongoDB
from adapters.external.database.mongo_client import get_mongo_db
from adapters.external.database.vault_client_registry_repository_mongodb import VaultRegistryRepositoryMongoDB
from config import get_settings
from core.domain.entities.vault_client_registry_entity import VaultRegistryEntity
from core.domain.repositories.adapter_registry_repository_interface import AdapterRegistryRepository
from core.domain.repositories.dex_pool_repository_interface import DexPoolRepository
from core.domain.repositories.dex_registry_repository_interface import DexRegistryRepository
from core.domain.repositories.vault_client_registry_repository_interface import VaultRegistryRepositoryInterface

from core.domain.schemas.vault_inputs import VaultCreateConfigIn
from core.services.tx_service import TxService
from core.services.utils import to_json_safe
from core.services.vault_status_service import ZERO_ADDR, VaultStatusService
from core.services.web3_cache import get_web3

def _is_address_like(s: str) -> bool:
    return isinstance(s, str) and s.startswith("0x") and len(s) == 42


def _norm_owner_prefix(owner: str) -> str:
    s = (owner or "").strip()
    if s.startswith("0x") and len(s) >= 7:
        return s[0:7]
    return (s[:7] or "owner")


def _norm_slug(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "").replace("/","-")


def _try_get(obj: Any, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


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

    vault_registry_repo: VaultRegistryRepositoryInterface
    adapter_registry_repo: AdapterRegistryRepository
    dex_pool_repo: DexPoolRepository
    dex_registry_repo: DexRegistryRepository

    @classmethod
    def from_settings(cls) -> "VaultClientVaultUseCase":
        db = get_mongo_db()
        vault_repo = VaultRegistryRepositoryMongoDB(db[VaultRegistryRepositoryMongoDB.COLLECTION])
        adapter_repo = AdapterRegistryRepositoryMongoDB()
        dex_pool_repo = DexPoolRepositoryMongoDB()
        dex_registry_repo = DexRegistryRepositoryMongoDB()
        return cls(
            vault_registry_repo=vault_repo,
            adapter_registry_repo=adapter_repo,
            dex_pool_repo=dex_pool_repo,
            dex_registry_repo=dex_registry_repo,
        )
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
        config_in: VaultCreateConfigIn,
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
        cfg = config_in.to_domain(address=vault_addr)

        entity = VaultRegistryEntity(
            dex=dex,
            address=vault_addr,
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
            addr = lg.get("address")
            if _is_address_like(addr):
                # This will often be the factory address, not the vault. So only accept if different.
                if Web3.to_checksum_address(addr) != Web3.to_checksum_address(self.factory.address):  # type: ignore
                    return Web3.to_checksum_address(addr)

        return None

    
    def _resolve_vault_address(self, alias_or_address: str) -> str:
        if _is_address_like(alias_or_address):
            return Web3.to_checksum_address(alias_or_address)
        else:
            vault = self.vault_registry_repo.find_by_alias(alias_or_address)
            if vault:
                alias_or_address = vault.config.address
                return Web3.to_checksum_address(alias_or_address)
        raise ValueError("Unknown vault alias/address (send the vault address in the path)")
    
    # -------- reads --------

    def get_status(
        self,
        *,
        alias_or_address: str,
        debug_timing: bool = False,
        fresh_onchain: bool = False,
    ) -> Dict[str, Any]:
        key = (alias_or_address or "").strip()
        if not key:
            raise ValueError("alias_or_address is required")

        # ---- vault_registry ----
        if _is_address_like(key):
            try:
                addr = Web3.to_checksum_address(key)
            except Exception:
                raise ValueError("Invalid vault address")
            v = self.vault_registry_repo.find_by_address(addr)
        else:
            v = self.vault_registry_repo.find_by_alias(key)

        if not v:
            raise ValueError("Vault not found in vault_registry")

        chain = (v.chain or "").strip().lower()
        dex = (v.dex or "").strip().lower()

        cfg = v.config
        vault_address = Web3.to_checksum_address(v.address)
        rpc_url = (cfg.rpc_url or "").strip()
        if not rpc_url:
            raise ValueError("vault_registry.config.rpc_url is missing")

        # ---- fetch wiring mostly from Mongo ----
        adapter_addr = Web3.to_checksum_address(cfg.adapter)
        pool_addr = Web3.to_checksum_address(cfg.pool)
        nfpm_addr = Web3.to_checksum_address(cfg.nfpm)
        gauge_addr = Web3.to_checksum_address(cfg.gauge) if cfg.gauge else ZERO_ADDR

        token0_addr: Optional[str] = None
        token1_addr: Optional[str] = None

        # Prefer adapter_registry by adapter address (has tokens and full wiring)
        ar = self.adapter_registry_repo.get_by_address(address=adapter_addr)
        if ar:
            try:
                pool_addr = Web3.to_checksum_address(ar.pool)
                nfpm_addr = Web3.to_checksum_address(ar.nfpm)
                gauge_addr = Web3.to_checksum_address(ar.gauge) if ar.gauge else ZERO_ADDR
                token0_addr = Web3.to_checksum_address(ar.token0)
                token1_addr = Web3.to_checksum_address(ar.token1)
            except Exception:
                pass
        else:
            # Fallback: dex_pools by (chain,dex,pool)
            dp = self.dex_pool_repo.get_by_pool(chain=chain, dex=dex, pool=pool_addr)
            if dp:
                try:
                    nfpm_addr = Web3.to_checksum_address(dp.nfpm)
                    gauge_addr = Web3.to_checksum_address(dp.gauge) if dp.gauge else ZERO_ADDR
                    token0_addr = Web3.to_checksum_address(dp.token0)
                    token1_addr = Web3.to_checksum_address(dp.token1)
                except Exception:
                    pass

        # dex_router from dex_registries (global wiring per dex)
        dex_router = None
        dr = self.dex_registry_repo.get_by_key(chain=chain, dex=dex)
        if dr:
            try:
                dex_router = Web3.to_checksum_address(dr.dex_router)
            except Exception:
                dex_router = dr.dex_router

        # strategy_id from vault_registry (already stored)
        strategy_id = int(v.strategy_id)

        static: Dict[str, Any] = {
            "chain": chain,
            "dex": dex,
            "vault": vault_address,
            "owner": v.owner,  # stored in vault_registry
            "adapter": adapter_addr,
            "pool": pool_addr,
            "nfpm": nfpm_addr,
            "gauge": gauge_addr,
            "token0": token0_addr,  # may be None if missing in db
            "token1": token1_addr,  # may be None if missing in db
            "dex_router": dex_router,  # may be None if missing in db
            "strategy_id": strategy_id,
        }

        reward_swap_pool = cfg.reward_swap_pool

        w3 = get_web3(rpc_url)
        svc = VaultStatusService(w3=w3)

        return svc.compute(
            vault_address=vault_address,
            dex=dex,
            reward_swap_pool=reward_swap_pool,
            static=static,
            debug_timing=debug_timing,
            fresh_onchain=fresh_onchain,
        )

    def register_client_vault(
        self,
        *,
        vault_address: str,
        strategy_id: int,
        owner: str,
        chain: str,
        dex: str,
        par_token: str,
        name: str,
        description: Optional[str],
        config_in: VaultCreateConfigIn,
    ) -> Dict[str, Any]:

        if not _is_address_like(vault_address):
            raise ValueError("Invalid vault_address")

        # idempotência
        existing = self.vault_registry_repo.find_by_address(
            Web3.to_checksum_address(vault_address)
        )
        if existing:
            return {
                "alias": existing.alias,
                "mongo_id": existing.id,
            }
        
        rpc_url = (getattr(config_in, "rpc_url", None) or "").strip()
        if not rpc_url:
            raise ValueError("config.rpc_url is required to validate on-chain")

        
        w3 = Web3(Web3.HTTPProvider(rpc_url))

        code = w3.eth.get_code(Web3.to_checksum_address(vault_address))
        if not code or code == b"":
            raise ValueError("Vault has no bytecode on provided rpc_url (wrong RPC/network?)")
            
        # validação mínima on-chain (com o provider correto)
        try:
            vault = ClientVaultAdapter(w3, vault_address)

            onchain_owner = Web3.to_checksum_address(vault.owner())
            expected_owner = Web3.to_checksum_address(owner)

            if onchain_owner != expected_owner:
                raise ValueError(f"Vault owner mismatch (onchain={onchain_owner} expected={expected_owner})")

            onchain_strategy_id = int(vault.strategy_id())
            if int(onchain_strategy_id) != int(strategy_id):
                raise ValueError(f"Vault strategyId mismatch (onchain={onchain_strategy_id} expected={int(strategy_id)})")

        except (ContractLogicError, BadFunctionCallOutput) as exc:
            raise ValueError(
                "Failed to read vault on-chain using provided rpc_url. "
                "Check if rpc_url/network matches the tx chain and that the address is a ClientVault."
            ) from exc

        owner_prefix = _norm_owner_prefix(owner)
        par_token_norm = _norm_slug(par_token).lower()

        idx = self.vault_registry_repo.count_alias_prefix(
            chain=chain,
            dex=dex,
            owner_prefix=owner_prefix,
            par_token=par_token_norm,
        ) + 1

        alias = f"{owner_prefix}-{par_token_norm}-{dex}-{chain}-{idx}"

        cfg = config_in.to_domain(address=vault_address)

        entity = VaultRegistryEntity(
            dex=dex,
            alias=alias,
            address=Web3.to_checksum_address(vault_address),
            config=cfg,
            is_active=False,
            chain=chain,
            owner=Web3.to_checksum_address(owner),
            par_token=par_token.upper(),
            name=name.strip(),
            description=(description.strip() if description else None),
            strategy_id=int(strategy_id),
        )

        saved = self.vault_registry_repo.insert(entity)

        return {
            "alias": alias,
            "mongo_id": saved.id,
        }
        
    def list_registry_by_owner(
        self,
        *,
        owner: str,
        chain: Optional[str] = None,
        dex: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        if not Web3.is_address((owner or "").strip()):
            raise ValueError("Invalid owner address")

        chain_n = _norm_slug(chain) if chain else None
        dex_n = _norm_slug(dex) if dex else None

        limit_i = int(limit or 200)
        offset_i = int(offset or 0)

        if limit_i < 1:
            limit_i = 1
        if limit_i > 500:
            limit_i = 500
        if offset_i < 0:
            offset_i = 0

        return self.vault_registry_repo.list_by_owner(
            owner=owner,
            chain=chain_n,
            dex=dex_n,
            limit=limit_i,
            offset=offset_i,
        )

    def update_daily_harvest_config_in_registry(
        self,
        *,
        alias_or_address: str,
        enabled: bool,
        cooldown_sec: int,
    ) -> VaultRegistryEntity:
        vault_addr = self._resolve_vault_address(alias_or_address)

        set_fields = {
            "config.daily_harvest": {"enabled": bool(enabled), "cooldown_sec": int(cooldown_sec)},
            "config.jobs.harvest_job.enabled": bool(enabled),
        }
        return self.vault_registry_repo.update_fields(address=vault_addr, set_fields=set_fields)

    def update_compound_config_in_registry(
        self,
        *,
        alias_or_address: str,
        enabled: bool,
        cooldown_sec: int,
    ) -> VaultRegistryEntity:
        vault_addr = self._resolve_vault_address(alias_or_address)

        set_fields = {
            "config.compound": {"enabled": bool(enabled), "cooldown_sec": int(cooldown_sec)},
            "config.jobs.compound_job.enabled": bool(enabled),
        }
        return self.vault_registry_repo.update_fields(address=vault_addr, set_fields=set_fields)

    def update_reward_swap_config_in_registry(
        self,
        *,
        alias_or_address: str,
        enabled: bool,
        token_in: str,
        token_out: str,
        fee: int,
        sqrt_price_limit_x96: str,
    ) -> VaultRegistryEntity:
        vault_addr = self._resolve_vault_address(alias_or_address)

        rs = {
            "enabled": bool(enabled),
            "tokenIn": (token_in or "").strip(),
            "tokenOut": (token_out or "").strip(),
            "fee": int(fee or 0),
            "sqrtPriceLimitX96": (sqrt_price_limit_x96 or "0").strip(),
        }

        set_fields = {
            "config.reward_swap": rs,
            "config.jobs.harvest_job.swap_rewards": bool(enabled),
        }
        return self.vault_registry_repo.update_fields(address=vault_addr, set_fields=set_fields)