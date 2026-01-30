from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, getcontext

from adapters.external.database.dex_registry_repository_mongodb import DexRegistryRepositoryMongoDB
from adapters.external.database.dex_pool_repository_mongodb import DexPoolRepositoryMongoDB

from core.domain.entities.dex_registry_entity import DexRegistryEntity, DexPoolEntity
from core.domain.enums.dex_registry_enums import DexRegistryStatus
from core.domain.repositories.dex_registry_repository_interface import DexRegistryRepository
from core.domain.repositories.dex_pool_repository_interface import DexPoolRepository


getcontext().prec = 50


def _norm(s: str) -> str:
    return (s or "").strip()


def _norm_lower(s: str) -> str:
    return _norm(s).lower()


def _fee_rate_from_bps(bps: int) -> str:
    # bps / 10000 => string
    return str((Decimal(int(bps)) / Decimal(10_000)).normalize())


@dataclass
class DexRegistryUseCase:
    dex_repo: DexRegistryRepository
    pool_repo: DexPoolRepository

    @classmethod
    def from_settings(cls) -> "DexRegistryUseCase":
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
                "created_at": r.created_at_iso,
            }
            for r in rows
        ]
        return {"ok": True, "message": "OK", "data": data}

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
                "created_at": r.created_at_iso,
            }
            for r in rows
        ]
        return {"ok": True, "message": "OK", "data": data}

    def get_pool_by_pool(self, *, pool: str) -> dict:
        pool = _norm(pool)
        if not pool:
            raise ValueError("pool is required")

        r = self.pool_repo.get_by_pool_address(pool=pool)
        if not r:
            return {"ok": False, "message": "Pool not found", "data": None}

        data = {
            "chain": r.chain,
            "dex": r.dex,
            "pool": r.pool,
            "token0": r.token0,
            "token1": r.token1,
            "reward_token": getattr(r, "reward_token", "0x0000000000000000000000000000000000000000"),
            "adapter": r.adapter,
            "status": r.status,
            "created_at": r.created_at_iso,
        }
        return {"ok": True, "message": "OK", "data": data}