# adapters/chain/vault_factory.py
from typing import Dict, Any, Optional
from web3 import Web3
from web3.contract import Contract
from web3.contract.contract import ContractFunction

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


ABI_VAULT_FACTORY = [
    # createClientVault
    {
        "name": "createClientVault",
        "inputs": [
            {"internalType": "uint256", "name": "strategyId", "type": "uint256"},
            {"internalType": "address", "name": "ownerOverride", "type": "address"},
        ],
        "outputs": [
            {"internalType": "address", "name": "vaultAddr", "type": "address"},
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # views
    {
        "name": "executor",
        "inputs": [],
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "feeCollector",
        "inputs": [],
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "defaultCooldownSec",
        "inputs": [],
        "outputs": [{"internalType": "uint32", "name": "", "type": "uint32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "defaultMaxSlippageBps",
        "inputs": [],
        "outputs": [{"internalType": "uint16", "name": "", "type": "uint16"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "defaultAllowSwap",
        "inputs": [],
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    # owner-only setters
    {
        "name": "setExecutor",
        "inputs": [
            {"internalType": "address", "name": "newExecutor", "type": "address"},
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "name": "setFeeCollector",
        "inputs": [
            {"internalType": "address", "name": "newCollector", "type": "address"},
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "name": "setDefaults",
        "inputs": [
            {"internalType": "uint32", "name": "_cooldownSec", "type": "uint32"},
            {"internalType": "uint16", "name": "_maxSlippageBps", "type": "uint16"},
            {"internalType": "bool", "name": "_allowSwap", "type": "bool"},
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


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
            abi=ABI_VAULT_FACTORY,
        )

    # ------------------------------------------------------------------ #
    # Views
    # ------------------------------------------------------------------ #

    def get_config(self) -> Dict[str, Any]:
        return {
            "executor": self.contract.functions.executor().call(),
            "feeCollector": self.contract.functions.feeCollector().call(),
            "defaultCooldownSec": int(
                self.contract.functions.defaultCooldownSec().call()
            ),
            "defaultMaxSlippageBps": int(
                self.contract.functions.defaultMaxSlippageBps().call()
            ),
            "defaultAllowSwap": bool(
                self.contract.functions.defaultAllowSwap().call()
            ),
        }

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
