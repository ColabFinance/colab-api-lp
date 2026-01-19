from __future__ import annotations

from enum import StrEnum


class GasStrategy(StrEnum):
    """
    Gas strategy selector for TxService calls.
    """

    DEFAULT = "default"
    BUFFERED = "buffered"
    AGGRESSIVE = "aggressive"
