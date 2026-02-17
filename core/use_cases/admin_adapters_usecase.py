from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from web3 import Web3

from adapters.chain.artifacts import load_contract_from_out
from adapters.external.database.adapter_registry_repository_mongodb import AdapterRegistryRepositoryMongoDB
from adapters.external.database.dex_pool_repository_mongodb import DexPoolRepositoryMongoDB
from config import get_settings
from core.domain.entities.adapter_registry_entity import AdapterRegistryEntity
from core.domain.enums.adapter_enums import AdapterStatus
from core.domain.repositories.adapter_registry_repository_interface import AdapterRegistryRepository
from core.domain.repositories.dex_pool_repository_interface import DexPoolRepository
from core.services.tx_service import TxService

from core.services.normalize import (
    ZERO_ADDRESS,
    _norm,
    _norm_lower,
    _require_nonzero,
    _fee_bps_str,
)


def _cs_addr(field: str, v: str, *, allow_zero: bool = False) -> str:
    vv = (v or "").strip()
    if allow_zero:
        if not vv or _norm_lower(vv) == ZERO_ADDRESS:
            return ZERO_ADDRESS
    if not Web3.is_address(vv):
        raise ValueError(f"{field} must be a valid EVM address (0x...).")
    return Web3.to_checksum_address(vv)


@dataclass
class AdminAdaptersUseCase:
    """
    Admin use case to deploy adapters on-chain and persist registry records in MongoDB.

    After deploying, we also update dex_pools.adapter for the matching (chain,dex,pool).
    """

    txs: TxService
    repo: AdapterRegistryRepository
    pool_repo: DexPoolRepository

    @classmethod
    def from_settings(cls) -> "AdminAdaptersUseCase":
        s = get_settings()
        repo = AdapterRegistryRepositoryMongoDB()
        pool_repo = DexPoolRepositoryMongoDB()

        try:
            repo.ensure_indexes()
        except Exception:
            pass
        try:
            pool_repo.ensure_indexes()
        except Exception:
            pass

        return cls(
            txs=TxService(s.RPC_URL_DEFAULT),
            repo=repo,
            pool_repo=pool_repo,
        )

    def create_adapter(
        self,
        *,
        chain: str,
        dex: str,
        pool: str,
        nfpm: str,
        gauge: str,
        fee_buffer: str,
        token0: str,
        token1: str,
        pool_name: str,
        fee_bps: str,
        status: str = "ACTIVE",
        created_by: str | None = None,
        gas_strategy: str = "buffered",
    ) -> dict:
        chain = _norm_lower(chain)
        if not chain:
            raise ValueError("chain is required")

        dex = _norm_lower(dex)
        if not dex:
            raise ValueError("dex is required")

        # DB key rule: pool stored/query as lowercase
        pool_input = _require_nonzero("pool", pool)
        pool_l = _norm_lower(pool_input)

        # Validate pool exists FIRST
        pool_row = self.pool_repo.get_by_pool(chain=chain, dex=dex, pool=pool_l)
        if not pool_row:
            # backward-compat fallback (old mixed-case docs)
            pool_row = self.pool_repo.get_by_pool(chain=chain, dex=dex, pool=_norm(pool_input))
        if not pool_row:
            raise ValueError("DEX pool not found for this (chain, dex, pool). Create the pool first.")

        # Uniqueness by (chain,dex,pool)
        existing = self.repo.get_by_dex_pool(chain=chain, dex=dex, pool=pool_l)
        if existing:
            raise ValueError("Adapter already exists for this dex+pool.")

        # Contract constructor args (onchain ok; DB store lower)
        nfpm_in = _require_nonzero("nfpm", nfpm)
        gauge_in = _norm(gauge)  # may be zero
        fee_buffer_in = _require_nonzero("fee_buffer", fee_buffer)

        pool_cs = _cs_addr("pool", pool_input)
        nfpm_cs = _cs_addr("nfpm", nfpm_in)
        gauge_cs = _cs_addr("gauge", gauge_in, allow_zero=True)
        fee_buffer_cs = _cs_addr("fee_buffer", fee_buffer_in)

        # Metadata
        token0_in = _require_nonzero("token0", token0)
        token1_in = _require_nonzero("token1", token1)
        if _norm_lower(token0_in) == _norm_lower(token1_in):
            raise ValueError("token0 and token1 must be different")

        pool_name = _norm(pool_name)
        if not pool_name:
            raise ValueError("pool_name is required")

        fee_bps = _fee_bps_str(fee_bps)

        st = (_norm(status).upper() or "ACTIVE")
        if st not in ("ACTIVE", "ARCHIVED_CAN_CREATE_NEW"):
            raise ValueError("status must be ACTIVE or ARCHIVED_CAN_CREATE_NEW")

        # Deploy on-chain (PancakeV3Adapter)
        abi, bytecode = load_contract_from_out("vaults", "PancakeV3Adapter.json")
        res = self.txs.deploy(
            abi=abi,
            bytecode=bytecode,
            ctor_args=(pool_cs, nfpm_cs, gauge_cs, fee_buffer_cs),
            wait=True,
            gas_strategy=gas_strategy,
        )

        addr = (res.get("result") or {}).get("contract_address")
        if not addr:
            raise RuntimeError("Deploy succeeded but contract_address is missing.")

        ent = AdapterRegistryEntity(
            chain=chain,
            address=_norm_lower(str(addr)),
            tx_hash=_norm_lower(res.get("tx_hash")),
            dex=dex,
            pool=pool_l,
            nfpm=_norm_lower(nfpm_in),
            gauge=_norm_lower(gauge_in),
            fee_buffer=_norm_lower(fee_buffer_in),
            token0=_norm_lower(token0_in),
            token1=_norm_lower(token1_in),
            pool_name=pool_name,
            fee_bps=fee_bps,
            status=AdapterStatus(st),
            created_by=_norm_lower(created_by) if created_by else None,
        )

        self.repo.insert(ent)

        persisted = self.repo.get_by_address(address=ent.address)
        if not persisted or persisted.address.lower() != ent.address.lower():
            raise RuntimeError("Adapter deployed but failed to persist in MongoDB.")

        updated = self.pool_repo.set_adapter(chain=chain, dex=dex, pool=pool_l, adapter=ent.address)
        if updated <= 0:
            raise RuntimeError("Adapter deployed but failed to update dex_pool.adapter.")

        res["result"] = {
            "chain": ent.chain,
            "address": ent.address,
            "tx_hash": ent.tx_hash,
            "dex": ent.dex,
            "pool": ent.pool,
            "nfpm": ent.nfpm,
            "gauge": ent.gauge,
            "fee_buffer": ent.fee_buffer,
            "token0": ent.token0,
            "token1": ent.token1,
            "pool_name": ent.pool_name,
            "fee_bps": ent.fee_bps,
            "status": ent.status,
            "created_at": ent.created_at_iso,
            "created_by": ent.created_by,
        }
        return res

    def list_adapters(self, *, chain: str, limit: int = 200) -> list[dict]:
        chain = _norm_lower(chain)
        if not chain:
            raise ValueError("chain is required")

        out: list[dict] = []
        for e in self.repo.list_all(chain=chain, limit=int(limit)):
            out.append(
                {
                    "chain": e.chain,
                    "address": e.address,
                    "tx_hash": e.tx_hash,
                    "dex": e.dex,
                    "pool": e.pool,
                    "nfpm": e.nfpm,
                    "gauge": e.gauge,
                    "fee_buffer": e.fee_buffer,
                    "token0": e.token0,
                    "token1": e.token1,
                    "pool_name": e.pool_name,
                    "fee_bps": e.fee_bps,
                    "status": e.status,
                    "created_at": e.created_at_iso,
                    "created_by": e.created_by,
                }
            )
        return out
