from typing import Tuple
from web3 import Web3
from web3.contract import Contract


ABI_CL_ADAPTER = [
    {"name": "pool", "inputs": [], "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"name": "nfpm", "inputs": [], "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"name": "gauge", "inputs": [], "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},

    {"name": "tokens", "inputs": [], "outputs": [{"type": "address"}, {"type": "address"}], "stateMutability": "view", "type": "function"},
    {"name": "tickSpacing", "inputs": [], "outputs": [{"type": "int24"}], "stateMutability": "view", "type": "function"},
    {"name": "slot0", "inputs": [], "outputs": [{"type": "uint160"}, {"type": "int24"}], "stateMutability": "view", "type": "function"},
    {"name": "currentTokenId", "inputs": [{"type": "address", "name": "vault"}], "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]


class CLAdapter:
    def __init__(self, w3: Web3, address: str):
        self.w3 = w3
        self.address = Web3.to_checksum_address(address)
        self.contract: Contract = w3.eth.contract(address=self.address, abi=ABI_CL_ADAPTER)

    def pool(self) -> str:
        return self.contract.functions.pool().call()

    def nfpm(self) -> str:
        return self.contract.functions.nfpm().call()

    def gauge(self) -> str:
        return self.contract.functions.gauge().call()

    def tokens(self) -> Tuple[str, str]:
        t0, t1 = self.contract.functions.tokens().call()
        return (t0, t1)

    def tick_spacing(self) -> int:
        return int(self.contract.functions.tickSpacing().call())

    def slot0(self) -> Tuple[int, int]:
        sqrtP, tick = self.contract.functions.slot0().call()
        return int(sqrtP), int(tick)

    def current_token_id(self, vault_addr: str) -> int:
        return int(self.contract.functions.currentTokenId(Web3.to_checksum_address(vault_addr)).call())
