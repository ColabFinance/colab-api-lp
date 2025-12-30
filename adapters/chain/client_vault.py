from typing import Any, Dict, Tuple
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

    # ---- tx
    {"name": "setAutomationEnabled", "inputs": [{"type": "bool", "name": "enabled"}], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "setAutomationConfig", "inputs": [{"type": "uint32", "name": "cooldownSec"}, {"type": "uint16", "name": "maxSlippageBps"}, {"type": "bool", "name": "allowSwap"}], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "collectToVault", "inputs": [], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "exitPositionToVault", "inputs": [], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "exitPositionAndWithdrawAll", "inputs": [{"type": "address", "name": "to"}], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
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
