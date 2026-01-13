from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LIBS_ABI_DIR = Path("libs/abi")
OUT_DIR = Path("out")


def load_abi_json(*parts: str) -> list:
    """
    Loads an ABI JSON list from libs/abi/... path.

    Use this ONLY for third-party contracts (Uniswap/Pancake/Aerodrome, etc).
    """
    p = LIBS_ABI_DIR.joinpath(*parts)
    if not p.exists():
        raise FileNotFoundError(f"ABI file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected ABI JSON list in {p}, got {type(data).__name__}")
    return data


def load_artifact(*parts: str) -> dict[str, Any]:
    """
    Loads a Solidity artifact JSON from out/... path.

    Example (Foundry):
      load_artifact("StrategyFactory.sol", "StrategyFactory.json")
    """
    p = OUT_DIR.joinpath(*parts)
    if not p.exists():
        raise FileNotFoundError(f"Artifact file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected artifact JSON object in {p}, got {type(data).__name__}")
    return data


def artifact_abi(art: dict[str, Any]) -> list:
    """
    Extracts ABI from a Solidity artifact.
    Expected shape: { "abi": [ ... ] }
    """
    abi = art.get("abi")
    if not isinstance(abi, list) or not abi:
        raise ValueError("Invalid or missing ABI in artifact.")
    return abi


def artifact_bytecode(art: dict[str, Any]) -> str:
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


def load_contract_from_out(*parts: str) -> tuple[list, str]:
    """
    Convenience helper: returns (abi, bytecode) from an out artifact.

    Example:
      abi, bytecode = load_contract_from_out("StrategyFactory.sol", "StrategyFactory.json")
    """
    art = load_artifact(*parts)
    return artifact_abi(art), artifact_bytecode(art)
