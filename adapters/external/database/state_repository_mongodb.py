# state_repository_mongodb.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from adapters.external.database.vault_events_repository_mongodb import VaultEventsRepository
from adapters.external.database.vault_state_repository import VaultStateRepository
from core.domain.repositories.vault_events_repository_interface import VaultEventsRepositoryInterface
from core.domain.repositories.vault_state_repository_interface import VaultStateRepositoryInterface
from core.services.normalize import _norm_lower


_state_repo: VaultStateRepositoryInterface = VaultStateRepository()
_events_repo: VaultEventsRepositoryInterface = VaultEventsRepository()


def load_state(dex: str, alias: str) -> Dict[str, Any]:
    return _state_repo.get_state(_norm_lower(dex), _norm_lower(alias))


def save_state(dex: str, alias: str, data: Dict[str, Any]) -> None:
    _state_repo.upsert_state(_norm_lower(dex), _norm_lower(alias), data)


def update_state(dex: str, alias: str, updates: Dict[str, Any]) -> None:
    _state_repo.patch_state(_norm_lower(dex), _norm_lower(alias), updates)


def ensure_state_initialized(
    dex: str,
    alias: str,
    *,
    vault_address: str,
    nfpm: Optional[str] = None,
    pool: Optional[str] = None,
    gauge: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    dex_n = _norm_lower(dex)
    alias_n = _norm_lower(alias)

    st = load_state(dex_n, alias_n)
    changed = False

    vault_address_n = _norm_lower(vault_address)
    nfpm_n = _norm_lower(nfpm) if nfpm is not None else None
    pool_n = _norm_lower(pool) if pool is not None else None
    gauge_n = _norm_lower(gauge) if gauge is not None else None

    if not st:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        st = {
            "vault_address": vault_address_n,
            "nfpm": nfpm_n,
            "pool": pool_n,
            "gauge": gauge_n,
            "created_at": now_iso,
            "positions": [],
            "fees_collected_cum": {"token0_raw": 0, "token1_raw": 0},
            "fees_cum_usd": 0.0,
            "rewards_usdc_cum": {"usdc_raw": 0, "usdc_human": 0.0},
        }
        changed = True
    else:
        if "vault_address" not in st:
            st["vault_address"] = vault_address_n
            changed = True
        if "nfpm" not in st and nfpm_n is not None:
            st["nfpm"] = nfpm_n
            changed = True
        if "pool" not in st and pool_n is not None:
            st["pool"] = pool_n
            changed = True
        if "gauge" not in st and gauge_n is not None:
            st["gauge"] = gauge_n
            changed = True
        if "positions" not in st:
            st["positions"] = []
            changed = True
        if "fees_collected_cum" not in st:
            st["fees_collected_cum"] = {"token0_raw": 0, "token1_raw": 0}
            changed = True
        if "fees_cum_usd" not in st:
            st["fees_cum_usd"] = 0.0
            changed = True
        if "rewards_usdc_cum" not in st:
            st["rewards_usdc_cum"] = {"usdc_raw": 0, "usdc_human": 0.0}
            changed = True

    if extra:
        for k, v in extra.items():
            if k not in st:
                st[k] = v
                changed = True

    if changed:
        save_state(dex_n, alias_n, st)

    return st


def append_history(dex: str, alias: str, key: str, entry: Dict[str, Any]) -> None:
    mapping = {
        "exec_history": "exec",
        "collect_history": "collect",
        "deposit_history": "deposit",
        "error_history": "error",
        "rewards_collect_history": "rewards_collect",
    }
    kind = mapping.get(key, key)
    _events_repo.append_event(_norm_lower(dex), _norm_lower(alias), _norm_lower(kind), entry)


def add_collected_fees_snapshot(
    dex: str,
    alias: str,
    *,
    fees0_raw: int,
    fees1_raw: int,
    fees_usd_est: float,
) -> None:
    dex_n = _norm_lower(dex)
    alias_n = _norm_lower(alias)

    st = load_state(dex_n, alias_n)
    cum = st.get("fees_collected_cum", {"token0_raw": 0, "token1_raw": 0}) or {}

    cum["token0_raw"] = int(cum.get("token0_raw", 0)) + int(fees0_raw or 0)
    cum["token1_raw"] = int(cum.get("token1_raw", 0)) + int(fees1_raw or 0)

    st["fees_collected_cum"] = cum
    st["fees_cum_usd"] = float(st.get("fees_cum_usd", 0.0)) + float(fees_usd_est or 0.0)
    st["last_fees_update_ts"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    save_state(dex_n, alias_n, st)

    _events_repo.append_event(
        dex_n,
        alias_n,
        "fees_collect",
        {
            "fees0_raw": int(fees0_raw),
            "fees1_raw": int(fees1_raw),
            "fees_usd_est": float(fees_usd_est),
        },
    )


def add_rewards_usdc_snapshot(
    dex: str,
    alias: str,
    *,
    usdc_raw: int,
    usdc_human: float,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    dex_n = _norm_lower(dex)
    alias_n = _norm_lower(alias)

    st = load_state(dex_n, alias_n)
    cum = st.get("rewards_usdc_cum", {"usdc_raw": 0, "usdc_human": 0.0}) or {}

    cum["usdc_raw"] = int(cum.get("usdc_raw", 0)) + int(usdc_raw or 0)
    cum["usdc_human"] = float(cum.get("usdc_human", 0.0)) + float(usdc_human or 0.0)
    st["rewards_usdc_cum"] = cum

    save_state(dex_n, alias_n, st)

    _events_repo.append_event(
        dex_n,
        alias_n,
        "rewards_collect",
        {
            "usdc_raw": int(usdc_raw),
            "usdc_human": float(usdc_human),
            "meta": meta or {},
        },
    )
