# scripts/migrate_vaults_to_mongo.py

"""
One-off migration script to move vault metadata and state from local JSON files
to MongoDB collections.

Usage (from project root):

    python -m scripts.migrate_vaults_to_mongo

Assumptions:

- The current filesystem layout follows:

    DATA_ROOT/
      <dex>/
        vaults.json         # registry for that DEX (optional, per DEX)
        state/              # per-alias state JSONs (optional)
          <alias>.json
          ...

- The MongoDB connection is configured via application settings used by
  `get_settings()` and `mongo_client.get_mongo_db()`.

Collections created/used:

- `vault_registry`
    One document per (dex, alias) with fields:
      - dex, alias, config, is_active, created_at, updated_at

- `vault_state`
    One document per (dex, alias) with fields:
      - dex, alias, state, created_at, updated_at

- `vault_events`
    One document per historical event, extracted from the legacy state JSON:
      - dex, alias, kind, ts, ts_iso, payload

This script is idempotent in the following sense:

- If a document for (dex, alias) already exists in MongoDB in `vault_state`,
  that alias is skipped entirely (state and events), assuming it was already
  migrated successfully.

If you need to re-run the migration from scratch, drop the collections
(`vault_registry`, `vault_state`, `vault_events`) before running this script
again.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from config import get_settings
from adapters.external.database.mongo_client import get_mongo_db
from adapters.external.database.vault_registry_repository import VaultRegistryRepository
from adapters.external.database.vault_state_repository import VaultStateRepository

logger = logging.getLogger("migrate_vaults_to_mongo")


INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


def normalize_for_bson(obj: Any) -> Any:
    """
    Recursively walk a JSON-like structure and ensure it is BSON-safe.

    - All ints that do not fit into 64 bits are converted to strings.
    - dicts, lists and tuples are traversed recursively.
    - Other scalar types are returned as-is.

    This avoids OverflowError: MongoDB can only handle up to 8-byte ints.
    """
    # bool is subclass of int, so check it first
    if isinstance(obj, bool):
        return obj

    # large ints -> string
    if isinstance(obj, int):
        if obj < INT64_MIN or obj > INT64_MAX:
            return str(obj)
        return obj

    # dict
    if isinstance(obj, dict):
        return {k: normalize_for_bson(v) for k, v in obj.items()}

    # list / tuple / set
    if isinstance(obj, (list, tuple, set)):
        return [normalize_for_bson(v) for v in obj]

    # leave everything else (str, float, None, etc.) as-is
    return obj


def _discover_dexes(data_root: Path) -> List[str]:
    """
    Discover DEX directories under DATA_ROOT.

    Every direct subdirectory of DATA_ROOT is considered a DEX folder
    (e.g. "uniswap", "aerodrome", "pancake").

    Args:
        data_root: Root directory where the vault JSON files are stored.

    Returns:
        A sorted list of subdirectory names representing DEX identifiers.
    """
    dexes: List[str] = []
    if not data_root.exists():
        logger.warning("DATA_ROOT does not exist on disk: %s", data_root)
        return dexes

    for child in data_root.iterdir():
        if child.is_dir():
            dexes.append(child.name)

    dexes.sort()
    return dexes


def _load_vaults_json(vaults_path: Path) -> Dict:
    """
    Load a vaults.json file if it exists, otherwise return an empty structure.

    Args:
        vaults_path: Filesystem path where vaults.json is expected.

    Returns:
        A dictionary with keys "active" and "vaults". If the file does not
        exist or is invalid, the default is:

            {"active": None, "vaults": {}}
    """
    if not vaults_path.exists():
        logger.info("No vaults.json found at %s, skipping registry migration.", vaults_path)
        return {"active": None, "vaults": {}}

    try:
        with vaults_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("vaults.json is not a JSON object")
        active = data.get("active")
        vaults = data.get("vaults") or {}
        if not isinstance(vaults, dict):
            raise ValueError("vaults.json['vaults'] must be a dict")
        return {"active": active, "vaults": vaults}
    except Exception as exc:
        logger.error("Failed to read vaults.json at %s: %s", vaults_path, exc)
        return {"active": None, "vaults": {}}


def migrate_vault_registry_for_dex(
    dex: str,
    data_root: Path,
    registry_repo: VaultRegistryRepository,
) -> Tuple[int, int]:
    """
    Migrate vault registry information for a single DEX from `vaults.json`
    to the `vault_registry` collection.

    Args:
        dex: DEX identifier (directory name under DATA_ROOT).
        data_root: Root data directory.
        registry_repo: Repository used to interact with MongoDB.

    Returns:
        A tuple `(inserted_count, skipped_count)` with the number of vault
        entries inserted into MongoDB and the number of entries skipped because
        they already existed.
    """
    dex_root = data_root / dex
    vaults_path = dex_root / "vaults.json"
    payload = _load_vaults_json(vaults_path)

    active_alias = payload.get("active")
    vaults_dict: Dict[str, Dict] = payload.get("vaults", {})

    inserted = 0
    skipped = 0

    coll = registry_repo.collection
    now = datetime.utcnow().isoformat()

    for alias, config in vaults_dict.items():
        existing = coll.find_one({"dex": dex, "alias": alias})
        if existing:
            logger.info(
                "[registry] DEX=%s alias=%s already exists in Mongo, skipping.",
                dex,
                alias,
            )
            skipped += 1
            continue

        is_active = bool(active_alias and alias == active_alias)
        doc = {
            "dex": dex,
            "alias": alias,
            "config": config or {},
            "is_active": is_active,
            "created_at": now,
            "updated_at": now,
        }
        safe_doc = normalize_for_bson(doc)
        coll.insert_one(safe_doc)
        logger.info(
            "[registry] Inserted DEX=%s alias=%s is_active=%s",
            dex,
            alias,
            is_active,
        )
        inserted += 1

    return inserted, skipped


def _split_state_and_events(
    dex: str,
    alias: str,
    state_data: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Split the legacy state JSON into a short state payload and a list of event
    documents suitable for insertion into the `vault_events` collection.

    The following keys are interpreted as historical arrays and converted into
    events:

        - exec_history          -> kind="exec"
        - collect_history       -> kind="collect"
        - deposit_history       -> kind="deposit"
        - error_history         -> kind="error"
        - rewards_collect_history -> kind="rewards_collect"

    Args:
        dex: DEX identifier.
        alias: Vault alias.
        state_data: Raw state dictionary loaded from the JSON file.

    Returns:
        A tuple `(short_state, events)` where:
          - short_state: state_data without the history arrays.
          - events: list of event documents with fields
                    {dex, alias, kind, ts, ts_iso, payload}.
    """
    # Shallow copy so we can pop history keys without mutating the original
    short_state: Dict[str, Any] = dict(state_data)

    mapping = {
        "exec_history": "exec",
        "collect_history": "collect",
        "deposit_history": "deposit",
        "error_history": "error",
        "rewards_collect_history": "rewards_collect",
    }

    events: List[Dict[str, Any]] = []

    for key, kind in mapping.items():
        raw = short_state.pop(key, None)
        if not isinstance(raw, list):
            continue

        for entry in raw:
            if isinstance(entry, dict):
                payload = entry
            else:
                payload = {"value": entry}

            ts_val = payload.get("ts")
            if isinstance(ts_val, (int, float)):
                ts_s = int(ts_val)
                ts_iso = datetime.fromtimestamp(ts_s, tz=timezone.utc).isoformat().replace(
                    "+00:00", "Z"
                )
            else:
                now_s = int(time.time())
                ts_s = now_s
                ts_iso = datetime.fromtimestamp(ts_s, tz=timezone.utc).isoformat().replace(
                    "+00:00", "Z"
                )

            event_doc: Dict[str, Any] = {
                "dex": dex,
                "alias": alias,
                "kind": kind,
                "ts": ts_s,
                "ts_iso": ts_iso,
                "payload": payload,
            }
            events.append(event_doc)

    return short_state, events


def migrate_state_for_dex(
    dex: str,
    data_root: Path,
    state_repo: VaultStateRepository,
    events_collection_name: str = "vault_events",
) -> Tuple[int, int]:
    """
    Migrate per-alias state JSON files for a single DEX into the
    `vault_state` and `vault_events` collections.

    All `*.json` files under `<DATA_ROOT>/<dex>/state/` are treated as state
    documents. The alias is derived from the filename without the extension.

    The migration performs:

      - Insert one `vault_state` document per (dex, alias) containing a short,
        non-historical state payload.
      - Insert one `vault_events` document per historical entry found in the
        legacy state JSON.

    Args:
        dex: DEX identifier (directory name under DATA_ROOT).
        data_root: Root data directory.
        state_repo: Repository used to interact with MongoDB for state.
        events_collection_name: Name of the collection used for events.

    Returns:
        A tuple `(inserted_count, skipped_count)` with the number of state
        documents inserted and the number skipped because they already existed.
    """
    dex_root = data_root / dex
    state_dir = dex_root / "state"

    if not state_dir.exists():
        logger.info("No state directory found for DEX=%s at %s, skipping.", dex, state_dir)
        return 0, 0

    inserted = 0
    skipped = 0
    state_coll = state_repo.collection

    db = get_mongo_db()
    events_coll = db[events_collection_name]

    now = datetime.utcnow().isoformat()

    for json_path in sorted(state_dir.glob("*.json")):
        alias = json_path.stem

        existing = state_coll.find_one({"dex": dex, "alias": alias})
        if existing:
            logger.info(
                "[state] DEX=%s alias=%s already exists in Mongo, skipping.",
                dex,
                alias,
            )
            skipped += 1
            continue

        try:
            with json_path.open("r", encoding="utf-8") as fh:
                state_data = json.load(fh)
            if not isinstance(state_data, dict):
                logger.warning(
                    "[state] File %s is not a JSON object, wrapping under 'raw' key.",
                    json_path,
                )
                state_data = {"raw": state_data}
        except Exception as exc:
            logger.error("Failed to read state file %s: %s", json_path, exc)
            continue

        short_state, events = _split_state_and_events(dex, alias, state_data)

        state_doc = {
            "dex": dex,
            "alias": alias,
            "state": short_state,
            "created_at": now,
            "updated_at": now,
        }
        safe_state_doc = normalize_for_bson(state_doc)
        state_coll.insert_one(safe_state_doc)

        if events:
            safe_events = [normalize_for_bson(e) for e in events]
            events_coll.insert_many(safe_events)
            logger.info(
                "[state] Inserted DEX=%s alias=%s from %s (events=%d)",
                dex,
                alias,
                json_path.name,
                len(events),
            )
        else:
            logger.info(
                "[state] Inserted DEX=%s alias=%s from %s (no events found)",
                dex,
                alias,
                json_path.name,
            )

        inserted += 1

    return inserted, skipped


def main() -> None:
    """
    Entry point for the migration script.

    - Discovers DEX folders under DATA_ROOT (or uses a CLI-provided filter).
    - For each DEX:
        - Migrates registry from vaults.json → vault_registry.
        - Migrates per-alias state JSONs → vault_state + vault_events.
    """
    parser = argparse.ArgumentParser(
        description="Migrate vault registry and state from JSON files to MongoDB."
    )
    parser.add_argument(
        "--dex",
        dest="dexes",
        nargs="*",
        help=(
            "Optional list of DEX names to migrate. "
            "If omitted, all subdirectories under DATA_ROOT are considered."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    settings = get_settings()
    data_root_str = getattr(settings, "DATA_ROOT", None)
    if not data_root_str:
        raise RuntimeError(
            "DATA_ROOT is not configured in settings. "
            "Set it before running the migration script."
        )

    data_root = Path(data_root_str)
    logger.info("Using DATA_ROOT: %s", data_root)

    detected_dexes = _discover_dexes(data_root)
    if args.dexes:
        dexes = [d for d in args.dexes if d in detected_dexes]
        missing = set(args.dexes) - set(dexes)
        for m in missing:
            logger.warning("DEX %s not found under DATA_ROOT, ignoring.", m)
    else:
        dexes = detected_dexes

    if not dexes:
        logger.warning("No DEX directories found. Nothing to migrate.")
        return

    logger.info("DEXes selected for migration: %s", ", ".join(dexes))

    registry_repo = VaultRegistryRepository()
    state_repo = VaultStateRepository()

    total_registry_inserted = 0
    total_registry_skipped = 0
    total_state_inserted = 0
    total_state_skipped = 0

    for dex in dexes:
        logger.info("---- Migrating DEX: %s ----", dex)

        reg_ins, reg_skip = migrate_vault_registry_for_dex(dex, data_root, registry_repo)
        st_ins, st_skip = migrate_state_for_dex(dex, data_root, state_repo)

        total_registry_inserted += reg_ins
        total_registry_skipped += reg_skip
        total_state_inserted += st_ins
        total_state_skipped += st_skip

        logger.info(
            "DEX=%s registry: inserted=%d skipped=%d | state: inserted=%d skipped=%d",
            dex,
            reg_ins,
            reg_skip,
            st_ins,
            st_skip,
        )

    logger.info("==== Migration summary ====")
    logger.info(
        "vault_registry: inserted=%d skipped=%d",
        total_registry_inserted,
        total_registry_skipped,
    )
    logger.info(
        "vault_state: inserted=%d skipped=%d",
        total_state_inserted,
        total_state_skipped,
    )
    logger.info("Migration finished.")


if __name__ == "__main__":
    main()
