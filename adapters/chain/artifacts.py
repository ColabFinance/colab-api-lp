from __future__ import annotations

import json
from pathlib import Path
from typing import Any


LIBS_ABI_DIR = Path("libs/abi")
OUT_DIR = Path("out")


def load_abi_json(*parts: str) -> list:
    """
    Loads an ABI JSON list from libs/abi/... path.

    Example:
      load_abi_json("aerodrome", "PoolImplementation.json")
    """
    p = LIBS_ABI_DIR.joinpath(*parts)
    if not p.exists():
        raise FileNotFoundError(f"ABI file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def load_artifact(*parts: str) -> dict[str, Any]:
    """
    Loads a Solidity artifact JSON from out/... path.

    Example:
      load_artifact("StrategyFactory.sol", "StrategyFactory.json")
    """
    p = OUT_DIR.joinpath(*parts)
    if not p.exists():
        raise FileNotFoundError(f"Artifact file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def artifact_bytecode(art: dict) -> str:
    """
    Extracts deployable bytecode from a Solidity artifact.
    Supports both {bytecode:{object:"0x.."}} and {bytecode:"0x.."} shapes.
    """
    bc = art.get("bytecode")
    if isinstance(bc, dict):
        bc = bc.get("object")
    if not isinstance(bc, str) or not bc.startswith("0x") or len(bc) < 10:
        raise ValueError("Invalid or missing bytecode in artifact.")
    return bc
