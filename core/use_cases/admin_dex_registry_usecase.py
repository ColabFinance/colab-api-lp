from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Optional

from adapters.external.database.dex_registry_repository_mongodb import DexRegistryRepositoryMongoDB
from adapters.external.database.dex_pool_repository_mongodb import DexPoolRepositoryMongoDB
from core.domain.entities.dex_registry_entity import DexRegistryEntity, DexPoolEntity
from core.domain.enums.dex_registry_enums import DexRegistryStatus, DexPoolType
from core.domain.repositories.dex_registry_repository_interface import DexRegistryRepository
from core.domain.repositories.dex_pool_repository_interface import DexPoolRepository
from core.services.normalize import _norm, _norm_lower, _require_nonzero


getcontext().prec = 50


def _fee_rate_from_bps(bps: int) -> str:
    return str((Decimal(int(bps)) / Decimal(10_000)).normalize())


@dataclass
class AdminDexRegistryUseCase:
    dex_repo: DexRegistryRepository
    pool_repo: DexPoolRepository

    @classmethod
    def from_settings(cls) -> "AdminDexRegistryUseCase":
        dex_repo = DexRegistryRepositoryMongoDB()
        pool_repo = DexPoolRepositoryMongoDB()
        try:
            dex_repo.ensure_indexes()
        except Exception:
            pass
        try:
            pool_repo.ensure_indexes()
        except Exception:
            pass
        return cls(dex_repo=dex_repo, pool_repo=pool_repo)

    def create_dex(
        self,
        *,
        chain: str,
        dex: str,
        dex_router: str,
        status: DexRegistryStatus = DexRegistryStatus.ACTIVE,
    ) -> dict:
        chain = _norm_lower(chain)
        dex = _norm_lower(dex)
        if not chain:
            raise ValueError("chain is required")
        if not dex:
            raise ValueError("dex is required")

        dex_router = _require_nonzero("dex_router", dex_router)

        exists = self.dex_repo.get_by_key(chain=chain, dex=dex)
        if exists:
            raise ValueError("DEX already exists for this (chain, dex).")

        ent = DexRegistryEntity(
            chain=chain,
            dex=dex,
            dex_router=_norm_lower(dex_router),
            status=status,
        )
        self.dex_repo.insert(ent)

        return {
            "ok": True,
            "message": "DEX registry created.",
            "data": {
                "chain": ent.chain,
                "dex": ent.dex,
                "dex_router": ent.dex_router,
                "status": ent.status,
                "created_at": getattr(ent, "created_at", None),
                "created_at_iso": getattr(ent, "created_at_iso", None),
                "updated_at": getattr(ent, "updated_at", None),
                "updated_at_iso": getattr(ent, "updated_at_iso", None),
            },
        }

    def update_dex(
        self,
        *,
        chain: str,
        dex: str,
        dex_router: str,
        status: DexRegistryStatus = DexRegistryStatus.ACTIVE,
    ) -> dict:
        chain = _norm_lower(chain)
        dex = _norm_lower(dex)
        if not chain:
            raise ValueError("chain is required")
        if not dex:
            raise ValueError("dex is required")

        dex_router = _require_nonzero("dex_router", dex_router)

        updated = self.dex_repo.update_by_key(
            chain=chain,
            dex=dex,
            dex_router=dex_router,
            status=status,
        )
        if not updated:
            raise ValueError("DEX registry not found.")

        return {
            "ok": True,
            "message": "DEX registry updated.",
            "data": {
                "chain": updated.chain,
                "dex": updated.dex,
                "dex_router": updated.dex_router,
                "status": updated.status,
                "created_at": getattr(updated, "created_at", None),
                "created_at_iso": getattr(updated, "created_at_iso", None),
                "updated_at": getattr(updated, "updated_at", None),
                "updated_at_iso": getattr(updated, "updated_at_iso", None),
            },
        }

    def list_dexes(self, *, chain: str, limit: int = 200) -> dict:
        chain = _norm_lower(chain)
        if not chain:
            raise ValueError("chain is required")

        rows = self.dex_repo.list_all(chain=chain, limit=int(limit))
        data = [
            {
                "chain": r.chain,
                "dex": r.dex,
                "dex_router": r.dex_router,
                "status": r.status,
                "created_at": getattr(r, "created_at", None),
                "created_at_iso": getattr(r, "created_at_iso", None),
                "updated_at": getattr(r, "updated_at", None),
                "updated_at_iso": getattr(r, "updated_at_iso", None),
            }
            for r in rows
        ]
        return {"ok": True, "message": "OK", "data": data}

    def create_pool(
        self,
        *,
        chain: str,
        dex: str,
        pool: str,
        nfpm: str,
        gauge: str,
        token0: str,
        token1: str,
        fee_bps: int,
        pair: str = "",
        symbol: str = "",
        adapter: Optional[str] = None,
        reward_token: str = "",
        reward_swap_pool: str = "0x0000000000000000000000000000000000000000",
        pool_type: DexPoolType = DexPoolType.CONCENTRATED,
        tick_spacing: Optional[int] = None,
        status: DexRegistryStatus = DexRegistryStatus.ACTIVE,
    ) -> dict:
        chain = _norm_lower(chain)
        dex = _norm_lower(dex)
        if not chain:
            raise ValueError("chain is required")
        if not dex:
            raise ValueError("dex is required")

        parent = self.dex_repo.get_by_key(chain=chain, dex=dex)
        if not parent:
            raise ValueError("DEX registry not found. Create the DEX first.")

        pool_in = _require_nonzero("pool", pool)
        nfpm_in = _require_nonzero("nfpm", nfpm)
        token0_in = _require_nonzero("token0", token0)
        token1_in = _require_nonzero("token1", token1)
        reward_token_in = _require_nonzero("reward_token", reward_token)

        gauge_in = _norm(gauge)
        reward_swap_pool_in = _norm(reward_swap_pool)

        pool_l = _norm_lower(pool_in)

        exists = self.pool_repo.get_by_pool(chain=chain, dex=dex, pool=pool_l)
        if exists:
            raise ValueError("Pool already exists for this (chain, dex, pool).")

        fee_bps_int = int(fee_bps)
        fee_rate = _fee_rate_from_bps(fee_bps_int)

        ent = DexPoolEntity(
            chain=chain,
            dex=dex,
            pool=pool_l,
            nfpm=_norm_lower(nfpm_in),
            gauge=_norm_lower(gauge_in),
            token0=_norm_lower(token0_in),
            token1=_norm_lower(token1_in),
            pair=_norm(pair),
            symbol=_norm(symbol),
            fee_bps=fee_bps_int,
            fee_rate=fee_rate,
            adapter=_norm_lower(adapter) if adapter else None,
            status=status,
            reward_token=_norm_lower(reward_token_in),
            reward_swap_pool=_norm_lower(reward_swap_pool_in),
            pool_type=pool_type,
            tick_spacing=int(tick_spacing) if tick_spacing is not None else None,
        )
        self.pool_repo.insert(ent)

        return {
            "ok": True,
            "message": "DEX pool created.",
            "data": {
                "chain": ent.chain,
                "dex": ent.dex,
                "pool": ent.pool,
                "nfpm": ent.nfpm,
                "gauge": ent.gauge,
                "token0": ent.token0,
                "token1": ent.token1,
                "pair": ent.pair,
                "symbol": ent.symbol,
                "fee_bps": ent.fee_bps,
                "fee_rate": ent.fee_rate,
                "adapter": ent.adapter,
                "reward_token": ent.reward_token,
                "reward_swap_pool": ent.reward_swap_pool,
                "pool_type": ent.pool_type,
                "tick_spacing": ent.tick_spacing,
                "status": ent.status,
                "created_at": getattr(ent, "created_at", None),
                "created_at_iso": getattr(ent, "created_at_iso", None),
                "updated_at": getattr(ent, "updated_at", None),
                "updated_at_iso": getattr(ent, "updated_at_iso", None),
            },
        }

    def update_pool(
        self,
        *,
        chain: str,
        dex: str,
        pool: str,
        nfpm: str,
        gauge: str,
        token0: str,
        token1: str,
        fee_bps: int,
        pair: str = "",
        symbol: str = "",
        adapter: Optional[str] = None,
        reward_token: str = "",
        reward_swap_pool: str = "0x0000000000000000000000000000000000000000",
        pool_type: DexPoolType = DexPoolType.CONCENTRATED,
        tick_spacing: Optional[int] = None,
        status: DexRegistryStatus = DexRegistryStatus.ACTIVE,
    ) -> dict:
        chain = _norm_lower(chain)
        dex = _norm_lower(dex)
        pool_l = _norm_lower(pool)

        if not chain:
            raise ValueError("chain is required")
        if not dex:
            raise ValueError("dex is required")
        if not pool_l:
            raise ValueError("pool is required")

        existing = self.pool_repo.get_by_pool(chain=chain, dex=dex, pool=pool_l)
        if not existing:
            raise ValueError("DEX pool not found.")

        nfpm_in = _require_nonzero("nfpm", nfpm)
        token0_in = _require_nonzero("token0", token0)
        token1_in = _require_nonzero("token1", token1)
        reward_token_in = _require_nonzero("reward_token", reward_token)

        gauge_in = _norm(gauge)
        reward_swap_pool_in = _norm(reward_swap_pool)

        fee_bps_int = int(fee_bps)
        fee_rate = _fee_rate_from_bps(fee_bps_int)

        updated = self.pool_repo.update_by_pool(
            chain=chain,
            dex=dex,
            pool=pool_l,
            nfpm=_norm_lower(nfpm_in),
            gauge=_norm_lower(gauge_in),
            token0=_norm_lower(token0_in),
            token1=_norm_lower(token1_in),
            pair=_norm(pair),
            symbol=_norm(symbol),
            fee_bps=fee_bps_int,
            fee_rate=fee_rate,
            adapter=_norm_lower(adapter) if adapter else None,
            reward_token=_norm_lower(reward_token_in),
            reward_swap_pool=_norm_lower(reward_swap_pool_in),
            pool_type=pool_type,
            tick_spacing=int(tick_spacing) if tick_spacing is not None else None,
            status=status,
        )
        if not updated:
            raise ValueError("DEX pool not found.")

        return {
            "ok": True,
            "message": "DEX pool updated.",
            "data": {
                "chain": updated.chain,
                "dex": updated.dex,
                "pool": updated.pool,
                "nfpm": updated.nfpm,
                "gauge": updated.gauge,
                "token0": updated.token0,
                "token1": updated.token1,
                "pair": updated.pair,
                "symbol": updated.symbol,
                "fee_bps": updated.fee_bps,
                "fee_rate": updated.fee_rate,
                "adapter": updated.adapter,
                "reward_token": updated.reward_token,
                "reward_swap_pool": updated.reward_swap_pool,
                "pool_type": getattr(updated, "pool_type", DexPoolType.CONCENTRATED),
                "tick_spacing": getattr(updated, "tick_spacing", None),
                "status": updated.status,
                "created_at": getattr(updated, "created_at", None),
                "created_at_iso": getattr(updated, "created_at_iso", None),
                "updated_at": getattr(updated, "updated_at", None),
                "updated_at_iso": getattr(updated, "updated_at_iso", None),
            },
        }

    def list_pools(self, *, chain: str, dex: str, limit: int = 500) -> dict:
        chain = _norm_lower(chain)
        dex = _norm_lower(dex)
        if not chain:
            raise ValueError("chain is required")
        if not dex:
            raise ValueError("dex is required")

        rows = self.pool_repo.list_by_dex(chain=chain, dex=dex, limit=int(limit))
        data = [
            {
                "chain": r.chain,
                "dex": r.dex,
                "pool": r.pool,
                "nfpm": r.nfpm,
                "gauge": r.gauge,
                "token0": r.token0,
                "token1": r.token1,
                "pair": r.pair,
                "symbol": r.symbol,
                "fee_bps": r.fee_bps,
                "fee_rate": r.fee_rate,
                "adapter": r.adapter,
                "status": r.status,
                "reward_token": r.reward_token,
                "reward_swap_pool": getattr(r, "reward_swap_pool", "0x0000000000000000000000000000000000000000"),
                "pool_type": getattr(r, "pool_type", DexPoolType.CONCENTRATED),
                "tick_spacing": getattr(r, "tick_spacing", None),
                "created_at": getattr(r, "created_at", None),
                "created_at_iso": getattr(r, "created_at_iso", None),
                "updated_at": getattr(r, "updated_at", None),
                "updated_at_iso": getattr(r, "updated_at_iso", None),
            }
            for r in rows
        ]
        return {"ok": True, "message": "OK", "data": data}