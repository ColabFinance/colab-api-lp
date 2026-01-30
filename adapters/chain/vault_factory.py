# adapters/chain/vault_factory.py
from typing import Dict, Any, Optional
from web3 import Web3
from web3.contract import Contract
from web3.contract.contract import ContractFunction

from adapters.chain.artifacts import load_abi_from_out
from core.domain.schemas.onchain_types import VaultFactoryConfig

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


class VaultFactoryAdapter:
    """
    Thin wrapper for the on-chain VaultFactory.

    - User: build_create_client_vault_tx (wallet do usuário)
    - Admin: build_set_executor_tx, build_set_fee_collector_tx, build_set_defaults_tx
    """

    def __init__(self, w3: Web3, address: str):
        if not address:
            raise RuntimeError("VaultFactoryAdapter: address not configured")
        self.w3: Web3 = w3
        self.address = Web3.to_checksum_address(address)
        self.contract: Contract = w3.eth.contract(
            address=self.address,
            abi=load_abi_from_out("vaults", "VaultFactory.json")
        )

    # ------------------------------------------------------------------ #
    # Views
    # ------------------------------------------------------------------ #

    def get_config(self) -> VaultFactoryConfig:
        return VaultFactoryConfig(
            executor=self.contract.functions.executor().call(),
            fee_collector=self.contract.functions.feeCollector().call(),
            default_cooldown_sec=int(self.contract.functions.defaultCooldownSec().call()),
            default_max_slippage_bps=int(self.contract.functions.defaultMaxSlippageBps().call()),
            default_allow_swap=bool(self.contract.functions.defaultAllowSwap().call()),
        )

    # ---------------- fn builders (for TxService.send) ----------------

    def fn_create_client_vault(self, strategy_id: int, owner_override: Optional[str] = None) -> ContractFunction:
        owner_param = Web3.to_checksum_address(owner_override) if owner_override else ZERO_ADDRESS
        return self.contract.functions.createClientVault(int(strategy_id), owner_param)

    def fn_set_executor(self, new_executor: str) -> ContractFunction:
        return self.contract.functions.setExecutor(Web3.to_checksum_address(new_executor))

    def fn_set_fee_collector(self, new_collector: str) -> ContractFunction:
        return self.contract.functions.setFeeCollector(Web3.to_checksum_address(new_collector))

    def fn_set_defaults(self, cooldown_sec: int, max_slippage_bps: int, allow_swap: bool) -> ContractFunction:
        return self.contract.functions.setDefaults(int(cooldown_sec), int(max_slippage_bps), bool(allow_swap))
