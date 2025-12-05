# services/vault_repo.py

"""
Vault registry facade for the liquidity provider API.

This module keeps the old, function-based API that used to read and write
`vaults.json` on disk, but internally delegates to the MongoDB-backed
`VaultRegistryRepository`.

Public functions preserved:

- list_vaults(dex)     -> {"active": <alias or None>, "vaults": {alias: config}}
- add_vault(dex, alias, row)
- set_active(dex, alias)
- get_vault(dex, alias) -> config or None
- set_pool(dex, alias, pool_addr)
- get_vault_any(alias) -> (dex or None, config or None)
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from adapters.external.database.vault_registry_repository import VaultRegistryRepository


_repo = VaultRegistryRepository()


def list_vaults(dex: str) -> Dict[str, Any]:
    """
    List all vault configurations for a given DEX.

    This keeps the legacy shape:

        {
          "active": <alias or None>,
          "vaults": {
            "<alias>": <config dict>,
            ...
          }
        }

    Args:
        dex: DEX identifier (e.g. "uniswap", "aerodrome", "pancake").

    Returns:
        A dictionary containing the active alias and a mapping of aliases
        to configuration dicts.
    """
    entries = _repo.list_by_dex(dex)
    active_entry = _repo.get_active_for_dex(dex)

    active_alias = active_entry.alias if active_entry else None
    vaults_dict = {e.alias: e.config for e in entries}

    return {
        "active": active_alias,
        "vaults": vaults_dict,
    }


def add_vault(dex: str, alias: str, row: Dict[str, Any]) -> None:
    """
    Create a new vault entry in the registry.

    This mirrors the old behavior of appending a new row to `vaults.json`.
    The first vault created for a given DEX becomes the active one by default.

    Args:
        dex: DEX identifier.
        alias: Vault alias.
        row: Configuration payload for this vault.
    """
    _repo.create_vault(dex, alias, row)


def set_active(dex: str, alias: str) -> None:
    """
    Mark a specific vault as active for the given DEX.

    All other vaults for that DEX are deactivated.

    Args:
        dex: DEX identifier.
        alias: Vault alias that should become active.
    """
    _repo.set_active(dex, alias)


def get_vault(dex: str, alias: str) -> Optional[Dict[str, Any]]:
    """
    Fetch the configuration for a given `(dex, alias)`.

    Args:
        dex: DEX identifier.
        alias: Vault alias.

    Returns:
        The configuration dictionary for the vault, or None if not found.
    """
    entry = _repo.get_by_dex_alias(dex, alias)
    if not entry:
        return None
    return entry.config


def set_pool(dex: str, alias: str, pool_addr: str) -> None:
    """
    Update the `pool` field inside the configuration of a vault.

    Args:
        dex: DEX identifier.
        alias: Vault alias.
        pool_addr: On-chain pool address to associate with this vault.

    Raises:
        ValueError: If the vault does not exist.
    """
    _repo.set_pool(dex, alias, pool_addr)


def get_vault_any(alias: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Search for a vault alias across all supported DEXs.

    This preserves the semantics of the original `get_vault_any` helper:
    it returns the first matching DEX and its configuration.

    Args:
        alias: Vault alias to search for.

    Returns:
        A tuple `(dex, config)` where:
            - dex: DEX identifier where the alias was found, or None.
            - config: Vault configuration dict, or None if not found.
    """
    dex, entry = _repo.find_any_by_alias(alias)
    if not entry:
        return None, None
    return dex, entry.config
