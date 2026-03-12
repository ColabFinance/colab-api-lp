from __future__ import annotations

from enum import StrEnum


class DexRegistryStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DexPoolType(StrEnum):
    VOLATILE = "VOLATILE"
    STABLE = "STABLE"
    WEIGHTED = "WEIGHTED"
    CONCENTRATED = "CONCENTRATED"