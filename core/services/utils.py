# core/services/utils.py
from typing import Any
from collections.abc import Mapping, Iterable
from hexbytes import HexBytes
from web3 import Web3

def to_json_safe(obj: Any) -> Any:
    """
    Recursively convert web3 / HexBytes-heavy structures into plain JSON-serializable primitives.

    - HexBytes -> "0x..." str
    - bytes    -> "0x..." str
    - Mapping  -> {k: to_json_safe(v)}   (covers AttributeDict, dict-like)
    - list/tuple/set -> [to_json_safe(v), ...]
    - everything else -> unchanged if primitive, else str(obj)
    """
    # HexBytes
    if isinstance(obj, HexBytes):
        return Web3.to_hex(obj)

    # bytes (raw bytes)
    if isinstance(obj, (bytes, bytearray)):
        return "0x" + obj.hex()

    # basic primitives
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj

    # dict-like (IMPORTANT: covers web3.datastructures.AttributeDict)
    if isinstance(obj, Mapping):
        return {str(k): to_json_safe(v) for (k, v) in obj.items()}

    # list / tuple / set
    if isinstance(obj, (list, tuple, set)):
        return [to_json_safe(v) for v in obj]

    # some web3 objects may be iterable but not list (rare)
    if isinstance(obj, Iterable) and not isinstance(obj, (str, bytes, bytearray)):
        try:
            return [to_json_safe(v) for v in obj]
        except Exception:
            pass

    return str(obj)
