# adapters/chain/strategy_registry.py
from typing import Dict, Any, Optional
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractLogicError
from web3.contract.contract import ContractFunction

from adapters.chain.artifacts import load_abi_from_out


class StrategyRegistryAdapter:
    """
    Thin wrapper for the on-chain StrategyRegistry.

    - Leituras: getStrategy, isStrategyActive
    - Admin (onlyOwner): registerStrategy, updateStrategy, setStrategyActive
      (só montamos a tx; quem assina é a wallet owner no front)
    """

    def __init__(self, w3: Web3, address: str):
        if not address:
            raise RuntimeError("StrategyRegistryAdapter: address not configured")
        self.w3: Web3 = w3
        self.address = Web3.to_checksum_address(address)
        self.contract: Contract = w3.eth.contract(
            address=self.address,
            abi=load_abi_from_out("vaults", "StrategyRegistry.json")
        )

    # ------------------------------------------------------------------ #
    # Views
    # ------------------------------------------------------------------ #

    def is_strategy_active(self, *, owner: str, strategy_id: int) -> bool:
        owner = Web3.to_checksum_address((owner or "").strip())
        try:
            return bool(self.contract.functions.isStrategyActive(owner, int(strategy_id)).call())
        except ContractLogicError:
            return False
