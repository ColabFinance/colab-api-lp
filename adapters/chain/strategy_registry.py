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

    def get_strategy(self, *, owner: str, strategy_id: int) -> Dict[str, Any]:
        owner = Web3.to_checksum_address((owner or "").strip())
        try:
            adapter, dex_router, token0, token1, name, description, active = (
                self.contract.functions.getStrategy(owner, int(strategy_id)).call()
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

    def is_strategy_active(self, *, owner: str, strategy_id: int) -> bool:
        owner = Web3.to_checksum_address((owner or "").strip())
        try:
            return bool(self.contract.functions.isStrategyActive(owner, int(strategy_id)).call())
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
