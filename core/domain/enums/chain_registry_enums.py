from __future__ import annotations

from enum import StrEnum


class ChainRegistryStatus(StrEnum):
    ENABLED = "ENABLED"
    MAINTENANCE = "MAINTENANCE"
    DISABLED = "DISABLED"