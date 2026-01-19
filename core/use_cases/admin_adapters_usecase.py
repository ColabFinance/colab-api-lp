from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from adapters.chain.artifacts import load_contract_from_out
from adapters.external.database.adapter_registry_repository_mongodb import AdapterRegistryRepositoryMongoDB
from config import get_settings
from core.domain.entities.adapter_registry_entity import AdapterRegistryEntity
from core.domain.enums.adapter_enums import AdapterStatus
from core.domain.repositories.adapter_registry_repository_interface import AdapterRegistryRepository
from core.services.tx_service import TxService


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def _norm(a: str) -> str:
    return (a or "").strip()


def _norm_lower(a: str) -> str:
    return _norm(a).lower()


def _require_nonzero(name: str, addr: str) -> str:
    addr = _norm(addr)
    if not addr or _norm_lower(addr) == ZERO_ADDRESS:
        raise ValueError(f"{name} must not be zero address.")
    return addr


def _fee_bps_str(s: str) -> str:
    s = (s or "").strip()
    if not s:
        raise ValueError("fee_bps is required")
    if not s.isdigit():
        raise ValueError("fee_bps must be a numeric string")
    v = int(s)
    if v <= 0 or v > 1_000_000:
        raise ValueError("fee_bps out of range")
    return str(v)


@dataclass
class AdminAdaptersUseCase:
    """
    Admin use case to deploy adapters on-chain and persist registry records in MongoDB.

    Security considerations:
      - Server must validate addresses and enforce uniqueness by (dex, pool).
      - Deployed contract address is only trusted after receipt is obtained.
      - Persisted record is validated by re-reading from MongoDB after insert.
    """

    txs: TxService
    repo: AdapterRegistryRepository

    @classmethod
    def from_settings(cls) -> "AdminAdaptersUseCase":
        s = get_settings()
        repo = AdapterRegistryRepositoryMongoDB()
        try:
            repo.ensure_indexes()
        except Exception:
            pass
        return cls(
            txs=TxService(s.RPC_URL_DEFAULT),
            repo=repo,
        )

    def create_adapter(
        self,
        *,
        chain: str,
        dex: str,
        pool: str,
        nfpm: str,
        gauge: str,
        token0: str,
        token1: str,
        pool_name: str,
        fee_bps: str,
        status: str = "ACTIVE",
        created_by: str | None = None,
        gas_strategy: str = "buffered",
    ) -> dict:
        chain = (chain or "").strip().lower()
        if not chain:
            raise ValueError("chain is required")
        
        dex = (dex or "").strip()
        if not dex:
            raise ValueError("dex is required")

        # Uniqueness by (dex, pool)
        pool_l = _norm_lower(pool)
        existing = self.repo.get_by_dex_pool(chain=chain, dex=dex, pool=pool_l)
        if existing:
            raise ValueError("Adapter already exists for this dex+pool.")

        # Contract constructor args
        pool = _require_nonzero("pool", pool)
        nfpm = _require_nonzero("nfpm", nfpm)
        gauge = _norm(gauge)  # may be zero

        # Metadata
        token0 = _require_nonzero("token0", token0)
        token1 = _require_nonzero("token1", token1)
        if _norm_lower(token0) == _norm_lower(token1):
            raise ValueError("token0 and token1 must be different")

        pool_name = (pool_name or "").strip()
        if not pool_name:
            raise ValueError("pool_name is required")

        fee_bps = _fee_bps_str(fee_bps)

        st = (status or "ACTIVE").strip().upper()
        if st not in ("ACTIVE", "INACTIVE"):
            raise ValueError("status must be ACTIVE or INACTIVE")

        # Deploy on-chain (PancakeV3Adapter)
        abi, bytecode = load_contract_from_out("PancakeV3Adapter.sol", "PancakeV3Adapter.json")

        res = self.txs.deploy(
            abi=abi,
            bytecode=bytecode,
            ctor_args=(pool, nfpm, gauge),
            wait=True,
            gas_strategy=gas_strategy,
        )

        addr = (res.get("result") or {}).get("contract_address")
        if not addr:
            raise RuntimeError("Deploy succeeded but contract_address is missing.")

        ent = AdapterRegistryEntity(
            chain=chain,
            address=str(addr),
            tx_hash=res.get("tx_hash"),
            dex=dex,
            pool=pool_l,
            nfpm=_norm_lower(nfpm),
            gauge=_norm_lower(gauge),
            token0=_norm_lower(token0),
            token1=_norm_lower(token1),
            pool_name=pool_name,
            fee_bps=fee_bps,
            status=AdapterStatus(st),
            created_by=_norm_lower(created_by) if created_by else None,
        )

        self.repo.insert(ent)

        persisted = self.repo.get_by_address(address=ent.address)
        if not persisted or persisted.address.lower() != ent.address.lower():
            raise RuntimeError("Adapter deployed but failed to persist in MongoDB.")

        # Normalize API output like factories
        res["result"] = {
            "chain": ent.chain,
            "address": ent.address,
            "tx_hash": ent.tx_hash,
            "dex": ent.dex,
            "pool": ent.pool,
            "nfpm": ent.nfpm,
            "gauge": ent.gauge,
            "token0": ent.token0,
            "token1": ent.token1,
            "pool_name": ent.pool_name,
            "fee_bps": ent.fee_bps,
            "status": ent.status.value,
            "created_at": ent.created_at_iso,
            "created_by": ent.created_by,
        }
        return res

    def list_adapters(self, *, chain: str, limit: int = 200) -> list[dict]:
        chain = (chain or "").strip().lower()
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
                    "token0": e.token0,
                    "token1": e.token1,
                    "pool_name": e.pool_name,
                    "fee_bps": e.fee_bps,
                    "status": e.status.value,
                    "created_at": e.created_at_iso,
                    "created_by": e.created_by,
                }
            )
        return out
