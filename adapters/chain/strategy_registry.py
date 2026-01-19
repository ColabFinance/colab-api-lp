# adapters/chain/strategy_registry.py
from typing import Dict, Any, Optional
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractLogicError
from web3.contract.contract import ContractFunction


ABI_STRATEGY_REGISTRY = [
    {
        "name": "getStrategy",
        "inputs": [
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "uint256", "name": "strategyId", "type": "uint256"},
        ],
        "outputs": [
            {
                "internalType": "struct StrategyRegistry.Strategy",
                "name": "s",
                "type": "tuple",
                "components": [
                    {"internalType": "address", "name": "adapter", "type": "address"},
                    {"internalType": "address", "name": "dexRouter", "type": "address"},
                    {"internalType": "address", "name": "token0", "type": "address"},
                    {"internalType": "address", "name": "token1", "type": "address"},
                    {"internalType": "string", "name": "name", "type": "string"},
                    {"internalType": "string", "name": "description", "type": "string"},
                    {"internalType": "bool", "name": "active", "type": "bool"},
                ],
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "isStrategyActive",
        "inputs": [
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "uint256", "name": "strategyId", "type": "uint256"},
        ],
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    # OPTIONAL: for listing
    {
        "name": "getAllStrategiesByOwner",
        "inputs": [{"internalType": "address", "name": "owner", "type": "address"}],
        "outputs": [
            {
                "internalType": "struct StrategyRegistry.Strategy[]",
                "name": "all",
                "type": "tuple[]",
                "components": [
                    {"internalType": "address", "name": "adapter", "type": "address"},
                    {"internalType": "address", "name": "dexRouter", "type": "address"},
                    {"internalType": "address", "name": "token0", "type": "address"},
                    {"internalType": "address", "name": "token1", "type": "address"},
                    {"internalType": "string", "name": "name", "type": "string"},
                    {"internalType": "string", "name": "description", "type": "string"},
                    {"internalType": "bool", "name": "active", "type": "bool"},
                ],
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "anonymous": False,
        "name": "StrategyRegistered",
        "type": "event",
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "owner", "type": "address"},
            {"indexed": True, "internalType": "uint256", "name": "strategyId", "type": "uint256"},
            {"indexed": True, "internalType": "address", "name": "adapter", "type": "address"},
            {"indexed": False, "internalType": "address", "name": "dexRouter", "type": "address"},
            {"indexed": False, "internalType": "address", "name": "token0", "type": "address"},
            {"indexed": False, "internalType": "address", "name": "token1", "type": "address"},
            {"indexed": False, "internalType": "string", "name": "name", "type": "string"},
        ],
    },
]



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
            abi=ABI_STRATEGY_REGISTRY,
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
