"""
Chain reader facade.

Historically this module contained the full implementation of `compute_status`.
That logic has been moved to `status_service` so it can be reused and tested
independently. This module now acts as a thin compatibility layer, exposing
the same public API as before.
"""

from __future__ import annotations

from typing import Any

from .status_service import compute_status as _compute_status


def compute_status(adapter: Any, dex: str, alias: str):
    """
    Backwards-compatible wrapper around `status_service.compute_status`.

    Args:
        adapter: DEX adapter bound to the vault contract.
        dex: DEX identifier ("uniswap", "aerodrome", "pancake", etc.).
        alias: Logical alias of the vault.

    Returns:
        A `StatusCore` instance with the vault's status snapshot.
    """
    return _compute_status(adapter, dex, alias)
