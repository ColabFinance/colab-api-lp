# core/services/vault_adapter_service.py

from web3 import Web3
from fastapi import HTTPException

from config import get_settings
from adapters.chain.pancake_v3 import PancakeV3Adapter
from adapters.chain.uniswap_v3 import UniswapV3Adapter
from adapters.chain.aerodrome import AerodromeAdapter


def get_adapter_for(
    dex: str,
    pool: str,
    nfpm: str | None,
    vault: str,
    rpc_url: str | None,
    gauge: str | None = None,
):
    """
    Factory for DEX adapters.

    Args:
        dex: "uniswap" | "aerodrome" | "pancake".
        pool: Pool address.
        nfpm: Non-fungible position manager (if applicable).
        vault: Vault address.
        rpc_url: Optional custom RPC for this vault.
        gauge: Optional gauge / staking contract.

    Returns:
        A configured adapter instance.

    Raises:
        HTTPException(400): if dex is not supported.
    """
    s = get_settings()
    w3 = Web3(Web3.HTTPProvider(rpc_url or s.RPC_URL_DEFAULT))

    if dex == "uniswap":
        return UniswapV3Adapter(w3, pool, nfpm, vault, gauge)
    if dex == "aerodrome":
        return AerodromeAdapter(w3, pool, nfpm, vault, gauge)
    if dex == "pancake":
        return PancakeV3Adapter(w3, pool, nfpm, vault, gauge)

    raise HTTPException(400, "Unsupported DEX")
