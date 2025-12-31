from typing import Tuple
from web3 import Web3
from web3.contract import Contract
from web3.contract.contract import ContractFunction


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

    # ---- owner tx (missing in front)
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

    # ---- NEW executor tx
    {"name": "autoRebalancePancake", "inputs": [{
        "name": "p",
        "type": "tuple",
        "components": [
            {"type": "int24", "name": "newLowerTick"},
            {"type": "int24", "name": "newUpperTick"},
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
        return (t0, t1)

    # ---------------- fn builders (for TxService.send) ----------------

    def fn_set_automation_enabled(self, enabled: bool) -> ContractFunction:
        return self.contract.functions.setAutomationEnabled(bool(enabled))

    def fn_set_automation_config(self, cooldown_sec: int, max_slippage_bps: int, allow_swap: bool) -> ContractFunction:
        return self.contract.functions.setAutomationConfig(int(cooldown_sec), int(max_slippage_bps), bool(allow_swap))

    def fn_collect(self) -> ContractFunction:
        return self.contract.functions.collectToVault()

    def fn_exit_to_vault(self) -> ContractFunction:
        return self.contract.functions.exitPositionToVault()

    def fn_exit_withdraw_all(self, to_addr: str) -> ContractFunction:
        return self.contract.functions.exitPositionAndWithdrawAll(Web3.to_checksum_address(to_addr))

    # ---- new owner tx builders
    def fn_open_initial_position(self, lower_tick: int, upper_tick: int) -> ContractFunction:
        return self.contract.functions.openInitialPosition(int(lower_tick), int(upper_tick))

    def fn_rebalance_with_caps(self, lower_tick: int, upper_tick: int, cap0: int, cap1: int) -> ContractFunction:
        return self.contract.functions.rebalanceWithCaps(int(lower_tick), int(upper_tick), int(cap0), int(cap1))

    def fn_stake(self) -> ContractFunction:
        return self.contract.functions.stake()

    def fn_unstake(self) -> ContractFunction:
        return self.contract.functions.unstake()

    def fn_claim_rewards(self) -> ContractFunction:
        return self.contract.functions.claimRewards()

    def fn_swap_exact_in_pancake(
        self,
        token_in: str,
        token_out: str,
        fee: int,
        amount_in: int,
        amount_out_min: int,
        sqrt_price_limit_x96: int,
    ) -> ContractFunction:
        return self.contract.functions.swapExactInPancake(
            Web3.to_checksum_address(token_in),
            Web3.to_checksum_address(token_out),
            int(fee),
            int(amount_in),
            int(amount_out_min),
            int(sqrt_price_limit_x96),
        )

    # ---- executor tx builder
    def fn_auto_rebalance_pancake(self, p: dict) -> ContractFunction:
        return self.contract.functions.autoRebalancePancake((
            int(p["newLowerTick"]),
            int(p["newUpperTick"]),
            int(p["fee"]),
            Web3.to_checksum_address(p["tokenIn"]),
            Web3.to_checksum_address(p["tokenOut"]),
            int(p["swapAmountIn"]),
            int(p["swapAmountOutMin"]),
            int(p["sqrtPriceLimitX96"]),
        ))
