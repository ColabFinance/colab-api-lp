from __future__ import annotations

from enum import Enum


class AdapterStatus(str, Enum):
    """
    Adapter record status stored in MongoDB.

    ACTIVE: can be selected/used by services that resolve adapters.
    INACTIVE: kept for history but should not be used by default.
    """

    ACTIVE = "ACTIVE"
    ARCHIVED_CAN_CREATE_NEW = "ARCHIVED_CAN_CREATE_NEW"
