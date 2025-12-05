# adapters/external/database/mongo_client.py

from __future__ import annotations

from typing import Optional

from pymongo import MongoClient
from pymongo.database import Database

from config import get_settings

_client: Optional[MongoClient] = None
_db: Optional[Database] = None


def get_mongo_client() -> MongoClient:
    """
    Return a singleton MongoClient instance configured from application settings.

    The following settings are expected to be provided by `get_settings()`:

    - MONGO_URI: Full MongoDB connection string
      (for example: "mongodb://localhost:27017" or an Atlas connection string)

    The client is created lazily and cached at module level so that subsequent
    calls reuse the same underlying connection pool.
    """
    global _client
    if _client is None:
        settings = get_settings()
        uri = getattr(settings, "MONGO_URI", None)
        if not uri:
            raise RuntimeError(
                "MONGO_URI is not configured. Please set it in your settings "
                "so the vault subsystem can connect to MongoDB."
            )
        _client = MongoClient(uri)
    return _client


def get_mongo_db() -> Database:
    """
    Return the default MongoDB Database instance used by the vault subsystem.

    The database name is taken from the application settings:

    - MONGO_DB: Logical database name inside the MongoDB deployment.

    The database object is cached at module level so that multiple repository
    instances share the same underlying client and database.
    """
    global _db
    if _db is None:
        settings = get_settings()
        db_name = getattr(settings, "MONGO_DB", None)
        if not db_name:
            raise RuntimeError(
                "MONGO_DB is not configured. Please set it in your settings "
                "so the vault subsystem can select a MongoDB database."
            )
        _db = get_mongo_client()[db_name]
    return _db
