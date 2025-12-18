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
            {"internalType": "uint256", "name": "strategyId", "type": "uint256"}
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
        "inputs": [{"internalType": "uint256", "name": "strategyId", "type": "uint256"}],
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },

    {
        "name": "registerStrategy",
        "inputs": [
            {"internalType": "address", "name": "adapter", "type": "address"},
            {"internalType": "address", "name": "dexRouter", "type": "address"},
            {"internalType": "address", "name": "token0", "type": "address"},
            {"internalType": "address", "name": "token1", "type": "address"},
            {"internalType": "string", "name": "name", "type": "string"},
            {"internalType": "string", "name": "description", "type": "string"},
        ],
        "outputs": [{"internalType": "uint256", "name": "strategyId", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },

    {
        "name": "updateStrategy",
        "inputs": [
            {"internalType": "uint256", "name": "strategyId", "type": "uint256"},
            {"internalType": "address", "name": "adapter", "type": "address"},
            {"internalType": "address", "name": "dexRouter", "type": "address"},
            {"internalType": "address", "name": "token0", "type": "address"},
            {"internalType": "address", "name": "token1", "type": "address"},
            {"internalType": "string", "name": "name", "type": "string"},
            {"internalType": "string", "name": "description", "type": "string"},
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },

    {
        "name": "setStrategyActive",
        "inputs": [
            {"internalType": "uint256", "name": "strategyId", "type": "uint256"},
            {"internalType": "bool", "name": "active", "type": "bool"},
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
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

    def get_strategy(self, strategy_id: int) -> Dict[str, Any]:
        try:
            adapter, dex_router, token0, token1, name, description, active = (
                self.contract.functions.getStrategy(int(strategy_id)).call()
            )
        except ContractLogicError as exc:
            raise exc

        return {
            "adapter": adapter,
            "dex_router": dex_router,
            "token0": token0,
            "token1": token1,
            "name": name,
            "description": description,
            "active": bool(active),
        }

    def is_strategy_active(self, strategy_id: int) -> bool:
        try:
            return bool(
                self.contract.functions.isStrategyActive(int(strategy_id)).call()
            )
        except ContractLogicError:
            return False

    # ------------- ContractFunction builders (for TxService) -------------

    def fn_register_strategy(
        self, *, adapter: str, dex_router: str, token0: str, token1: str, name: str, description: str
    ) -> ContractFunction:
        return self.contract.functions.registerStrategy(
            Web3.to_checksum_address(adapter),
            Web3.to_checksum_address(dex_router),
            Web3.to_checksum_address(token0),
            Web3.to_checksum_address(token1),
            name,
            description,
        )

    def fn_update_strategy(
        self,
        *,
        strategy_id: int,
        adapter: str,
        dex_router: str,
        token0: str,
        token1: str,
        name: str,
        description: str,
    ) -> ContractFunction:
        return self.contract.functions.updateStrategy(
            int(strategy_id),
            Web3.to_checksum_address(adapter),
            Web3.to_checksum_address(dex_router),
            Web3.to_checksum_address(token0),
            Web3.to_checksum_address(token1),
            name,
            description,
        )

    def fn_set_strategy_active(self, *, strategy_id: int, active: bool) -> ContractFunction:
        return self.contract.functions.setStrategyActive(int(strategy_id), bool(active))


    # ---------------- Receipt parsing ----------------

    def parse_strategy_registered_strategy_id(self, receipt: dict) -> Optional[int]:
        try:
            evs = self.contract.events.StrategyRegistered().process_receipt(receipt)
            if not evs:
                return None
            return int(evs[0]["args"]["strategyId"])
        except Exception:
            return None
