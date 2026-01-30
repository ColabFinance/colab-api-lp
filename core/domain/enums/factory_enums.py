from __future__ import annotations

from enum import StrEnum


class FactoryStatus(StrEnum):
    """
    Status values stored in Mongo.

    Rules:
    - ACTIVE: this factory is currently used by the system.
    - ARCHIVED_CAN_CREATE_NEW: creation is allowed if the latest factory is in this status.
    """

    ACTIVE = "ACTIVE"
    ARCHIVED_CAN_CREATE_NEW = "ARCHIVED_CAN_CREATE_NEW"
