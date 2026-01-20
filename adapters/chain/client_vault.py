from typing import Tuple

from web3 import Web3
from web3.contract import Contract
from web3.contract.contract import ContractFunction

from adapters.chain.artifacts import load_abi_from_out
from core.domain.schemas.onchain_types import AutoRebalancePancakeParams


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
        self.contract: Contract = w3.eth.contract(address=self.address, abi=load_abi_from_out("vaults", "ClientVault.json"))

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
