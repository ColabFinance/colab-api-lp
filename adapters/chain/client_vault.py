from typing import Tuple

from web3 import Web3
from web3.contract import Contract
from web3.contract.contract import ContractFunction

from core.domain.schemas.onchain_types import AutoRebalancePancakeParams


ABI_CLIENT_VAULT = [
    # ---- views (wiring)
    {"name": "owner", "inputs": [], "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"name": "executor", "inputs": [], "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"name": "adapter", "inputs": [], "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"name": "dexRouter", "inputs": [], "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"name": "feeCollector", "inputs": [], "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"name": "strategyId", "inputs": [], "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},

    # ---- views (state)
    {"name": "positionTokenId", "inputs": [], "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"name": "lastRebalanceTs", "inputs": [], "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"name": "tokens", "inputs": [], "outputs": [{"type": "address"}, {"type": "address"}], "stateMutability": "view", "type": "function"},

    # ---- owner tx
    {"name": "setAutomationEnabled", "inputs": [{"type": "bool", "name": "enabled"}], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "setAutomationConfig", "inputs": [{"type": "uint32", "name": "cooldownSec"}, {"type": "uint16", "name": "maxSlippageBps"}, {"type": "bool", "name": "allowSwap"}], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "collectToVault", "inputs": [], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "exitPositionToVault", "inputs": [], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "exitPositionAndWithdrawAll", "inputs": [{"type": "address", "name": "to"}], "outputs": [], "stateMutability": "nonpayable", "type": "function"},

    {"name": "openInitialPosition", "inputs": [{"type": "int24", "name": "lowerTick"}, {"type": "int24", "name": "upperTick"}], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "rebalanceWithCaps", "inputs": [{"type": "int24", "name": "lowerTick"}, {"type": "int24", "name": "upperTick"}, {"type": "uint256", "name": "cap0"}, {"type": "uint256", "name": "cap1"}], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "stake", "inputs": [], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "unstake", "inputs": [], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "claimRewards", "inputs": [], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "swapExactInPancake", "inputs": [
        {"type": "address", "name": "tokenIn"},
        {"type": "address", "name": "tokenOut"},
        {"type": "uint24", "name": "fee"},
        {"type": "uint256", "name": "amountIn"},
        {"type": "uint256", "name": "amountOutMin"},
        {"type": "uint160", "name": "sqrtPriceLimitX96"},
    ], "outputs": [{"type": "uint256", "name": "amountOut"}], "stateMutability": "nonpayable", "type": "function"},

    # ---- executor tx
    {"name": "autoRebalancePancake", "inputs": [{
        "name": "params",
        "type": "tuple",
        "components": [
            {"type": "int24", "name": "newLower"},
            {"type": "int24", "name": "newUpper"},
            {"type": "uint24", "name": "fee"},
            {"type": "address", "name": "tokenIn"},
            {"type": "address", "name": "tokenOut"},
            {"type": "uint256", "name": "swapAmountIn"},
            {"type": "uint256", "name": "swapAmountOutMin"},
            {"type": "uint160", "name": "sqrtPriceLimitX96"},
        ],
    }], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
]


class ClientVaultAdapter:
    """
    Thin Web3 adapter for ClientVault.sol.

    This class is meant to be the single source of truth for vault-level calls.
    DEX-specific adapters (pancake/uniswap/aerodrome) should not re-declare vault ABI.
    """

    def __init__(self, w3: Web3, address: str):
        if not address:
            raise RuntimeError("ClientVaultAdapter: address not configured")
        self.w3 = w3
        self.address = Web3.to_checksum_address(address)
        self.contract: Contract = w3.eth.contract(address=self.address, abi=ABI_CLIENT_VAULT)

    # ---------------- views ----------------

    def owner(self) -> str:
        return self.contract.functions.owner().call()

    def executor(self) -> str:
        return self.contract.functions.executor().call()

    def adapter(self) -> str:
        return self.contract.functions.adapter().call()

    def dex_router(self) -> str:
        return self.contract.functions.dexRouter().call()

    def fee_collector(self) -> str:
        return self.contract.functions.feeCollector().call()

    def strategy_id(self) -> int:
        return int(self.contract.functions.strategyId().call())

    def position_token_id(self) -> int:
        return int(self.contract.functions.positionTokenId().call())

    def last_rebalance_ts(self) -> int:
        return int(self.contract.functions.lastRebalanceTs().call())

    def tokens(self) -> Tuple[str, str]:
        t0, t1 = self.contract.functions.tokens().call()
        return (Web3.to_checksum_address(t0), Web3.to_checksum_address(t1))

    # ---------------- tx builders ----------------

    def fn_auto_rebalance_pancake(self, params: AutoRebalancePancakeParams) -> ContractFunction:
        p = params.to_abi_dict()
        p["tokenIn"] = Web3.to_checksum_address(p["tokenIn"])
        p["tokenOut"] = Web3.to_checksum_address(p["tokenOut"])
        return self.contract.functions.autoRebalancePancake(p)
