# adapters/external/database/vault_registry_repository.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo.collection import Collection

from adapters.external.database.helper_repo import sanitize_for_mongo
from adapters.external.database.mongo_client import get_mongo_db
from core.domain.entities.vault_registry_entity import VaultRegistryEntry
from core.domain.repositories.vault_registry_repository_interface import VaultRegistryRepositoryInterface


class VaultRegistryRepository(VaultRegistryRepositoryInterface):
    """
    Repository responsible for persisting vault registry metadata in MongoDB.

    Each document represents a single vault configuration identified by the
    `(dex, alias)` pair. The document schema is:

        {
          "_id": ObjectId,
          "dex":       <str>,  # e.g. "uniswap", "aerodrome", "pancake"
          "alias":     <str>,  # user-defined alias for the vault
          "config":    <dict>, # the row previously stored in vaults.json
          "is_active": <bool>, # whether this is the active vault for this DEX
          "created_at": <iso8601 str>,
          "updated_at": <iso8601 str>
        }

    The repository provides convenience methods that mirror what the previous
    JSON-based implementation exposed via the `vault_repo` module.
    """

    def __init__(self, collection: Optional[Collection] = None) -> None:
        """
        Initialize the repository.

        Args:
            collection: Optional MongoDB collection to use. If omitted, the
                default `vault_registry` collection from the configured database
                is used. Supplying a collection makes this class easier to test.
        """
        db = get_mongo_db()
        self.collection: Collection = collection or db["vault_registry"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """
        Ensure the collection has the indexes required for efficient queries.

        The following indexes are created:

        - Unique compound index on (dex, alias) to guarantee that no duplicate
          vault aliases exist for the same DEX.
        - Non-unique index on (dex, is_active) to quickly fetch the active
          vault for a given DEX.
        """
        self.collection.create_index(
            [("dex", 1), ("alias", 1)], unique=True, name="u_dex_alias"
        )
        self.collection.create_index(
            [("dex", 1), ("is_active", 1)], name="i_dex_active"
        )

    # ------------ CRUD-like operations ------------

    def list_by_dex(self, dex: str) -> List[VaultRegistryEntry]:
        """
        List all vault registry documents for a given DEX.

        Args:
            dex: DEX identifier (e.g. "uniswap", "aerodrome", "pancake").

        Returns:
            A list of `VaultRegistryEntry` entities.
        """
        cursor = self.collection.find({"dex": dex})
        return [VaultRegistryEntry.from_mongo(doc) for doc in cursor]
    
    def get_active_for_dex(self, dex: str) -> Optional[VaultRegistryEntry]:
        """
        Fetch the active vault registry document for the given DEX.

        Args:
            dex: DEX identifier.

        Returns:
            The active `VaultRegistryEntry`, or None if none is active.
        """
        doc = self.collection.find_one({"dex": dex, "is_active": True})
        return VaultRegistryEntry.from_mongo(doc) if doc else None

    def get_by_dex_alias(self, dex: str, alias: str) -> Optional[VaultRegistryEntry]:
        """
        Retrieve a registry entry by `(dex, alias)`.

        Args:
            dex: DEX identifier.
            alias: Vault alias string.

        Returns:
            The `VaultRegistryEntry`, or None if not found.
        """
        doc = self.collection.find_one({"dex": dex, "alias": alias})
        return VaultRegistryEntry.from_mongo(doc) if doc else None

    def create_vault(self, dex: str, alias: str, config: Dict[str, Any]) -> VaultRegistryEntry:
        """
        Create a new vault registry document.

        If there is no active vault yet for the given DEX, the newly created
        vault is automatically marked as active.

        Args:
            dex: DEX identifier.
            alias: Vault alias.
            config: Arbitrary configuration dictionary for this vault. This is
                the same payload that used to be stored in `vaults.json`.

        Returns:
            The created registry document (without `_id`).

        Raises:
            ValueError: If a vault with the same `(dex, alias)` already exists.
        """
        existing = self.collection.find_one({"dex": dex, "alias": alias})
        if existing:
            raise ValueError(f"Vault alias '{alias}' already exists for DEX '{dex}'")

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        has_any_for_dex = self.collection.count_documents({"dex": dex}) > 0
        is_active = not has_any_for_dex

        entry = VaultRegistryEntry(
            dex=dex,
            alias=alias,
            config=config or {},
            is_active=is_active,
            created_at=now,
            updated_at=now,
        )
        mongo_doc = entry.to_mongo()
        mongo_doc = sanitize_for_mongo(mongo_doc)
        result = self.collection.insert_one(mongo_doc)
        entry.id = result.inserted_id
        return entry

    def set_active(self, dex: str, alias: str) -> None:
        """
        Mark a specific vault as active for the given DEX and deactivate others.

        Args:
            dex: DEX identifier.
            alias: Alias of the vault that should become active.

        Raises:
            ValueError: If no vault exists with the given `(dex, alias)`.
        """
        doc = self.collection.find_one({"dex": dex, "alias": alias})
        if not doc:
            raise ValueError(f"Unknown vault alias '{alias}' for DEX '{dex}'")

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Deactivate all for this DEX
        self.collection.update_many(
            {"dex": dex},
            {"$set": {"is_active": False, "updated_at": now}},
        )

        # Activate the selected one
        self.collection.update_one(
            {"dex": dex, "alias": alias},
            {"$set": {"is_active": True, "updated_at": now}},
        )

    def set_pool(self, dex: str, alias: str, pool_addr: str) -> None:
        """
        Update the `pool` field inside the vault configuration document.

        Args:
            dex: DEX identifier.
            alias: Vault alias to update.
            pool_addr: On-chain pool address to associate with this vault.

        Raises:
            ValueError: If no vault exists with the given `(dex, alias)`.
        """
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        result = self.collection.update_one(
            {"dex": dex, "alias": alias},
            {"$set": {"config.pool": pool_addr, "updated_at": now}},
        )
        if result.matched_count == 0:
            raise ValueError(f"Unknown vault alias '{alias}' for DEX '{dex}'")

    # ------------ cross-dex helper ------------

    def find_any_by_alias(self, alias: str) -> Tuple[Optional[str], Optional[VaultRegistryEntry]]:
        """
        Search for a vault alias across all supported DEXs.

        This method is intended to provide the same semantics as the original
        `vault_repo.get_vault_any` helper.

        Args:
            alias: Vault alias to search for.

        Returns:
            A tuple `(dex, entry)` where:
              - dex: the DEX identifier where the alias was found, or None.
              - entry: the `VaultRegistryEntry`, or None if not found.
        """
        for dex in ("uniswap", "aerodrome", "pancake"):
            entry = self.get_by_dex_alias(dex, alias)
            if entry is not None:
                return dex, entry
        return None, None
