from __future__ import annotations

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def _norm(a: str | None) -> str:
    return (a or "").strip()


def _norm_lower(a: str | None) -> str:
    return _norm(a).lower()


def _require_nonzero(name: str, addr: str | None) -> str:
    addr = _norm(addr)
    if not addr or _norm_lower(addr) == ZERO_ADDRESS:
        raise ValueError(f"{name} must not be zero address.")
    return addr


def _fee_bps_str(s: str | None) -> str:
    s = (s or "").strip()
    if not s:
        raise ValueError("fee_bps is required")
    if not s.isdigit():
        raise ValueError("fee_bps must be a numeric string")
    v = int(s)
    if v <= 0 or v > 1_000_000:
        raise ValueError("fee_bps out of range")
    return str(v)
