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

        exists = self.dex_repo.get_by_key(chain=chain, dex=dex)
        if exists:
            raise ValueError("DEX already exists for this (chain, dex).")

        ent = DexRegistryEntity(
            chain=chain,
            dex=dex,
            dex_router=dex_router,
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
                "created_at": ent.created_at_iso,
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
                "created_at": r.created_at_iso,
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
        adapter: str | None = None,
        reward_token: str,
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

        exists = self.pool_repo.get_by_pool(chain=chain, dex=dex, pool=pool)
        if exists:
            raise ValueError("Pool already exists for this (chain, dex, pool).")

        fee_bps_int = int(fee_bps)
        fee_rate = _fee_rate_from_bps(fee_bps_int)

        ent = DexPoolEntity(
            chain=chain,
            dex=dex,
            pool=pool,
            nfpm=nfpm,
            gauge=gauge,
            token0=token0,
            token1=token1,
            pair=_norm(pair),
            symbol=_norm(symbol),
            fee_bps=fee_bps_int,
            fee_rate=fee_rate,
            adapter=adapter,
            status=status,
            reward_token=reward_token
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
                "status": ent.status,
                "created_at": ent.created_at_iso,
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
                "created_at": r.created_at_iso,
            }
            for r in rows
        ]
        return {"ok": True, "message": "OK", "data": data}
