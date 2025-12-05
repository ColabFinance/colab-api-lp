# services/state_repo.py

"""
Per-alias state repository backed by MongoDB.

This module provides a simple functional API that mirrors the previous
JSON-file based implementation, but internally delegates to MongoDB
repositories:

- VaultStateRepository: stores the *current* short state document.
- VaultEventsRepository: stores historical events (execution, collects, errors, etc.).

The goal is to keep the "state" document small and focused on the current
position and cumulative counters, while all detailed history is stored
append-only in a dedicated `vault_events` collection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from adapters.external.database.vault_events_repository import VaultEventsRepository
from adapters.external.database.vault_state_repository import VaultStateRepository


_state_repo = VaultStateRepository()
_events_repo = VaultEventsRepository()


def load_state(dex: str, alias: str) -> Dict[str, Any]:
    """
    Load the current vault state for a given (dex, alias).

    This returns the 'state' dictionary stored in the 'vault_state' collection,
    or an empty dict if nothing exists yet.

    Args:
        dex: DEX identifier (e.g. "uniswap", "aerodrome", "pancake").
        alias: Logical vault alias.

    Returns:
        The current state dictionary or an empty dict.
    """
    return _state_repo.get_state(dex, alias)


def save_state(dex: str, alias: str, data: Dict[str, Any]) -> None:
    """
    Persist the given state dictionary for (dex, alias) to MongoDB.

    The payload is stored inside the 'state' field of the `vault_state` document.

    Args:
        dex: DEX identifier.
        alias: Vault alias.
        data: Full state payload to persist.
    """
    _state_repo.upsert_state(dex, alias, data)


def update_state(dex: str, alias: str, updates: Dict[str, Any]) -> None:
    """
    Apply a shallow merge of 'updates' into the existing state for (dex, alias).

    If no state exists yet, one is created with only the provided fields.

    Args:
        dex: DEX identifier.
        alias: Vault alias.
        updates: Partial state dictionary to merge into the existing state.
    """
    _state_repo.patch_state(dex, alias, updates)


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
    """
    Ensure a minimal state document exists for (dex, alias).

    If the state is empty, a new baseline is created. Otherwise, mandatory keys
    are added in an idempotent way. The updated state is stored back into MongoDB
    and returned.

    Note:
        Historical arrays (exec_history, collect_history, etc.) are *not* stored
        in the state document anymore. They belong in the `vault_events`
        collection and are appended via `append_history` and related helpers.

    Args:
        dex: DEX identifier.
        alias: Vault alias.
        vault_address: On-chain vault contract address.
        nfpm: Optional NonFungiblePositionManager address.
        pool: Optional pool address.
        gauge: Optional gauge (staking) address.
        extra: Optional dictionary of additional fields that should be set only
               if they do not exist yet.

    Returns:
        The up-to-date state dictionary.
    """
    st = load_state(dex, alias)
    changed = False

    if not st:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        st = {
            "vault_address": vault_address,
            "nfpm": nfpm,
            "pool": pool,
            "gauge": gauge,
            "created_at": now_iso,
            "positions": [],
            "fees_collected_cum": {"token0_raw": 0, "token1_raw": 0},
            "fees_cum_usd": 0.0,
            "rewards_usdc_cum": {"usdc_raw": 0, "usdc_human": 0.0},
            # `vault_initial_usd` is optional and may be set later by chain_reader
        }
        changed = True
    else:
        if "vault_address" not in st:
            st["vault_address"] = vault_address
            changed = True
        if "nfpm" not in st and nfpm is not None:
            st["nfpm"] = nfpm
            changed = True
        if "pool" not in st and pool is not None:
            st["pool"] = pool
            changed = True
        if "gauge" not in st and gauge is not None:
            st["gauge"] = gauge
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
        # we intentionally do NOT reintroduce history arrays here
        # (exec_history, collect_history, etc.)
        # and we leave `vault_initial_usd` optional.

    if extra:
        for k, v in extra.items():
            if k not in st:
                st[k] = v
                changed = True

    if changed:
        save_state(dex, alias, st)

    return st


def append_history(
    dex: str,
    alias: str,
    key: str,
    entry: Dict[str, Any]
) -> None:
    """
    Append a history entry as an event in the 'vault_events' collection.

    Historically this function truncated an in-memory array in the JSON state
    file. In the MongoDB-backed implementation we instead insert one event
    document per entry and do *not* enforce a storage limit. The 'limit'
    parameter is kept for API compatibility and may be used by callers as a
    suggested maximum when fetching recent events.

    Args:
        dex: DEX identifier.
        alias: Vault alias.
        key: Logical history key, mapped to the event kind (e.g. 'exec_history'
             -> 'exec', 'collect_history' -> 'collect').
        entry: Arbitrary event payload to store.
        limit: Maximum number of events to *read* later; not enforced here.
    """
    mapping = {
        "exec_history": "exec",
        "collect_history": "collect",
        "deposit_history": "deposit",
        "error_history": "error",
        "rewards_collect_history": "rewards_collect",
    }
    kind = mapping.get(key, key)
    _events_repo.append_event(dex, alias, kind, entry)


def add_collected_fees_snapshot(
    dex: str,
    alias: str,
    *,
    fees0_raw: int,
    fees1_raw: int,
    fees_usd_est: float,
) -> None:
    """
    Update cumulative fee counters and optionally record a fee-collection event.

    This mirrors the previous behavior of incrementing the running
    'fees_collected_cum' totals, but now persists the state in MongoDB and
    stores a separate event document for historical analysis.

    Args:
        dex: DEX identifier.
        alias: Vault alias.
        fees0_raw: Raw amount of collected fees in token0 units.
        fees1_raw: Raw amount of collected fees in token1 units.
        fees_usd_est: Estimated USD value of the collected fees at the time.
    """
    st = load_state(dex, alias)
    cum = st.get("fees_collected_cum", {"token0_raw": 0, "token1_raw": 0}) or {}

    cum["token0_raw"] = int(cum.get("token0_raw", 0)) + int(fees0_raw or 0)
    cum["token1_raw"] = int(cum.get("token1_raw", 0)) + int(fees1_raw or 0)

    st["fees_collected_cum"] = cum
    st["fees_cum_usd"] = float(st.get("fees_cum_usd", 0.0)) + float(fees_usd_est or 0.0)
    st["last_fees_update_ts"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    save_state(dex, alias, st)

    _events_repo.append_event(
        dex,
        alias,
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
    """
    Accumulate rewards in USDC-equivalent units and record a reward-collection event.

    This function increases the running 'rewards_usdc_cum' totals and inserts a
    'rewards_collect' event into the historical events collection.

    Args:
        dex: DEX identifier.
        alias: Vault alias.
        usdc_raw: Raw integer amount of USDC-equivalent rewards.
        usdc_human: Human-readable float amount of USDC-equivalent rewards.
        meta: Optional metadata with additional context (e.g. source swap tx hash).
    """
    st = load_state(dex, alias)
    cum = st.get("rewards_usdc_cum", {"usdc_raw": 0, "usdc_human": 0.0}) or {}

    cum["usdc_raw"] = int(cum.get("usdc_raw", 0)) + int(usdc_raw or 0)
    cum["usdc_human"] = float(cum.get("usdc_human", 0.0)) + float(usdc_human or 0.0)
    st["rewards_usdc_cum"] = cum

    save_state(dex, alias, st)

    _events_repo.append_event(
        dex,
        alias,
        "rewards_collect",
        {
            "usdc_raw": int(usdc_raw),
            "usdc_human": float(usdc_human),
            "meta": meta or {},
        },
    )
