from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, Optional, List

from web3 import Web3
from web3.contract.contract import Contract
from web3.exceptions import ContractLogicError, BadFunctionCallOutput

from adapters.chain.client_vault import ClientVaultAdapter
from adapters.external.database.adapter_registry_repository_mongodb import AdapterRegistryRepositoryMongoDB
from adapters.external.database.dex_pool_repository_mongodb import DexPoolRepositoryMongoDB
from adapters.external.database.dex_registry_repository_mongodb import DexRegistryRepositoryMongoDB
from adapters.external.database.mongo_client import get_mongo_db
from adapters.external.database.vault_client_registry_repository_mongodb import VaultRegistryRepositoryMongoDB

from adapters.external.signals.signals_http_client import SignalsHttpClient
from core.domain.entities.vault_client_registry_entity import VaultRegistryEntity
from core.domain.repositories.adapter_registry_repository_interface import AdapterRegistryRepository
from core.domain.repositories.dex_pool_repository_interface import DexPoolRepository
from core.domain.repositories.dex_registry_repository_interface import DexRegistryRepository
from core.domain.repositories.vault_client_registry_repository_interface import VaultRegistryRepositoryInterface

from core.domain.schemas.vault_inputs import VaultCreateConfigIn
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

ZERO_ADDR_HEX = "0x0000000000000000000000000000000000000000"
STABLE_SYMBOLS = {
    "usdc",
    "usdt",
    "dai",
    "usde",
    "susde",
    "fdusd",
    "pyusd",
    "usdbc",
    "frax",
    "gusd",
    "lusd",
    "tusd",
}


def _is_zero_address(addr: Optional[str]) -> bool:
    if not addr:
        return True
    return str(addr).strip().lower() in {"", ZERO_ADDR_HEX}


def _format_fee_tier_label(fee_bps: Optional[str]) -> Optional[str]:
    if fee_bps is None:
        return None

    try:
        fee_tier = int(str(fee_bps).strip())
    except Exception:
        return None

    if fee_tier <= 0:
        return None

    text = f"{fee_tier / 10000:.2f}".rstrip("0").rstrip(".")
    return f"{text}%"


def _split_pool_name(pool_name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not pool_name:
        return None, None

    clean = str(pool_name).strip().replace("-", "/")
    if "/" not in clean:
        return None, None

    left, right = clean.split("/", 1)
    left = left.strip().upper() or None
    right = right.strip().upper() or None
    return left, right


def _build_display_name(
    *,
    raw_name: Optional[str],
    pool_name: Optional[str],
    fee_bps: Optional[str],
    alias: Optional[str],
    address: Optional[str],
) -> str:
    raw = (raw_name or "").strip()
    if raw and "%" in raw:
        return raw

    fee_label = _format_fee_tier_label(fee_bps)

    if pool_name:
        pair = str(pool_name).replace("/", "-").upper().strip()
        return f"{pair} {fee_label}".strip() if fee_label else pair

    if raw:
        return raw

    return (alias or address or "vault").strip()


def _pair_type_from_symbols(
    token0_symbol: Optional[str],
    token1_symbol: Optional[str],
) -> str:
    if (
        token0_symbol
        and token1_symbol
        and token0_symbol.lower() in STABLE_SYMBOLS
        and token1_symbol.lower() in STABLE_SYMBOLS
    ):
        return "stable"
    return "volatile"

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
    signals_http_client: SignalsHttpClient

    @classmethod
    def from_settings(cls) -> "VaultClientVaultUseCase":
        db = get_mongo_db()
        vault_repo = VaultRegistryRepositoryMongoDB(db=db)
        adapter_repo = AdapterRegistryRepositoryMongoDB(db=db)
        dex_pool_repo = DexPoolRepositoryMongoDB(db=db)
        dex_registry_repo = DexRegistryRepositoryMongoDB(db=db)
        signals_http_client = SignalsHttpClient.from_settings()
        return cls(
            vault_registry_repo=vault_repo,
            adapter_registry_repo=adapter_repo,
            dex_pool_repo=dex_pool_repo,
            dex_registry_repo=dex_registry_repo,
            signals_http_client=signals_http_client
        )
 
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

        dp = None
        
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

        # fallback for older vault_registry docs (missing config.reward_swap_pool)
        if not reward_swap_pool:
            reward_swap_pool = _try_get(ar, "reward_swap_pool", None) or _try_get(dp, "reward_swap_pool", None)

        if reward_swap_pool and Web3.is_address(str(reward_swap_pool)):
            reward_swap_pool = Web3.to_checksum_address(str(reward_swap_pool))
        else:
            reward_swap_pool = None

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

    async def register_client_vault(
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

        try:
            if not (cfg.reward_swap_pool and Web3.is_address(str(cfg.reward_swap_pool))):
                main_pool = Web3.to_checksum_address(cfg.pool)

                chain_n = _norm_slug(chain)
                dex_n = _norm_slug(dex)

                dp = self.dex_pool_repo.get_by_pool(chain=chain_n, dex=dex_n, pool=main_pool)
                rsp = _try_get(dp, "reward_swap_pool", None)

                if rsp and Web3.is_address(str(rsp)):
                    cfg.reward_swap_pool = Web3.to_checksum_address(str(rsp))
        except Exception:
            # best-effort; do not block vault registration
            pass

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

        await self.signals_http_client.link_vault_to_strategy(
            chain=chain,
            alias=alias,
            dex=dex,
            owner=owner,
            strategy_id=strategy_id
        )
        
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

    def list_explore_registry(
        self,
        *,
        owner: Optional[str] = None,
        chain: Optional[str] = None,
        dex: Optional[str] = None,
        query: Optional[str] = None,
        active_only: Optional[bool] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        collection = getattr(self.vault_registry_repo, "collection", None)
        if collection is None:
            raise ValueError("Vault registry collection is not available")

        q: Dict[str, Any] = {}

        chain_n = _norm_slug(chain) if chain else None
        dex_n = _norm_slug(dex) if dex else None
        owner_n = (owner or "").strip().lower() if owner else None

        if chain_n:
            q["chain"] = chain_n
        if dex_n:
            q["dex"] = dex_n
        if active_only is not None:
            q["is_active"] = bool(active_only)

        needle = (query or "").strip().lower()
        if needle:
            rx = {"$regex": re.escape(needle)}
            q["$or"] = [
                {"alias": rx},
                {"name": rx},
                {"address": rx},
                {"par_token": rx},
                {"description": rx},
            ]

        limit_i = max(1, min(int(limit or 500), 1000))
        offset_i = max(0, int(offset or 0))

        docs = list(
            collection.find(q)
            .sort("created_at", -1)
            .skip(offset_i)
            .limit(limit_i)
        )

        items: List[Dict[str, Any]] = []

        for raw in docs:
            v = VaultRegistryEntity.from_mongo(raw)
            cfg = getattr(v, "config", None)

            chain_val = _norm_slug(getattr(v, "chain", None) or chain_n or "")
            dex_val = _norm_slug(getattr(v, "dex", None) or dex_n or "")

            adapter_addr = _try_get(cfg, "adapter")
            pool_addr = _try_get(cfg, "pool")
            gauge_addr = _try_get(cfg, "gauge")

            adapter_doc = None
            if adapter_addr and Web3.is_address(str(adapter_addr)):
                try:
                    adapter_doc = self.adapter_registry_repo.get_by_address(address=str(adapter_addr))
                except Exception:
                    adapter_doc = None

            pool_doc = None
            if pool_addr and chain_val and dex_val:
                try:
                    pool_doc = self.dex_pool_repo.get_by_pool(
                        chain=chain_val,
                        dex=dex_val,
                        pool=str(pool_addr),
                    )
                except Exception:
                    pool_doc = None

            token0_address = _try_get(adapter_doc, "token0", None) or _try_get(pool_doc, "token0", None)
            token1_address = _try_get(adapter_doc, "token1", None) or _try_get(pool_doc, "token1", None)

            pool_name = _try_get(adapter_doc, "pool_name", None)
            fee_bps = _try_get(adapter_doc, "fee_bps", None)

            if _is_zero_address(gauge_addr):
                gauge_addr = _try_get(adapter_doc, "gauge", None) or _try_get(pool_doc, "gauge", None)

            token0_symbol, token1_symbol = _split_pool_name(pool_name)

            items.append(
                {
                    "id": getattr(v, "alias", None) or getattr(v, "address", None),
                    "alias": getattr(v, "alias", None),
                    "name": _build_display_name(
                        raw_name=getattr(v, "name", None),
                        pool_name=pool_name,
                        fee_bps=fee_bps,
                        alias=getattr(v, "alias", None),
                        address=getattr(v, "address", None),
                    ),
                    "address": getattr(v, "address", None),
                    "owner": getattr(v, "owner", None),
                    "strategy_id": int(getattr(v, "strategy_id", 0) or 0),
                    "chain": chain_val,
                    "dex": dex_val,
                    "pool": pool_addr,
                    "adapter": adapter_addr,
                    "gauge": gauge_addr,
                    "token0_address": token0_address,
                    "token1_address": token1_address,
                    "token0_symbol": token0_symbol,
                    "token1_symbol": token1_symbol,
                    "pool_name": pool_name,
                    "fee_bps": str(fee_bps) if fee_bps is not None else None,
                    "has_gauge": not _is_zero_address(gauge_addr),
                    "is_active": bool(getattr(v, "is_active", False)),
                    "is_mine": bool(
                        owner_n and str(getattr(v, "owner", "")).lower() == owner_n
                    ),
                    "pair_type": _pair_type_from_symbols(token0_symbol, token1_symbol),
                    "status": "active" if bool(getattr(v, "is_active", False)) else "paused",
                    # TODO: preencher a partir de cache leve (vault_state / performance snapshot),
                    # sem chamar status/performance pesado em lote.
                    "tvl_usd": None,
                    "tvl_change_24h_pct": None,
                    "apr_pct": None,
                    "apy_pct": None,
                    "range_status": None,
                    "my_position_usd": None,
                }
            )

        return items
    
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