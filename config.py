import os
from dotenv import load_dotenv
from dataclasses import dataclass, field
from pydantic import Field
from functools import lru_cache
from typing import List

load_dotenv()


def _parse_csv(value: str, *, lower: bool = False) -> List[str]:
    if not value:
        return []
    items = [x.strip() for x in value.split(",")]
    items = [x for x in items if x]
    if lower:
        items = [x.lower() for x in items]
    return items


@dataclass
class Settings:
    # MongoDB
    MONGO_URI: str
    MONGO_DB: str

    PANCAKE_V3_QUOTER: str
    PANCAKE_V3_ROUTER: str
    PANCAKE_FACTORY: str
    PANCAKE_TICK_SPACINGS: str
    PANCAKE_MASTERCHEF_V3: str

    AERO_POOL_FACTORY_AMM: str

    AERO_QUOTER: str
    AERO_ROUTER: str
    AERO_ROUTER_AMM: str
    AERO_TICK_SPACINGS: str

    UNI_V3_ROUTER: str
    UNI_V3_QUOTER: str
    DEFAULT_SWAP_POOL_FEE: int

    # signing / chain
    RPC_URL_DEFAULT: str
    PRIVATE_KEY: str

    # on-chain registry / factory
    STRATEGY_REGISTRY_ADDRESS: str
    VAULT_FACTORY_ADDRESS: str

    # ---- Admin / Privy Auth (NEW) ----
    PRIVY_APP_ID: str
    PRIVY_APP_SECRET: str
    PRIVY_JWKS_URL: str
    ADMIN_WALLETS: str 

    # data roots (simulate DB)
    DATA_ROOT: str = "data"
    UNISWAP_ROOT: str = "uniswap"
    AERODROME_ROOT: str = "aerodrome"

    # default TWAP/policies
    TWAP_WINDOW_SEC: int = 60
    MAX_TWAP_DEVIATION_TICKS: int = 50
    MIN_REBALANCE_COOLDOWN_SEC: int = 1800

    # generic
    ENV: str = Field(default="dev")
    LOG_LEVEL: str = Field(default="INFO")

    STABLE_TOKEN_ADDRESSES: List[str] = field(default_factory=list)


@lru_cache()
def get_settings() -> Settings:
    stable_default = [
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "0x1c7d4b196cb0c7b01d743fbc6116a902379c7238",
    ]

    stable_raw = os.getenv("STABLE_TOKEN_ADDRESSES", "")
    stable_list = _parse_csv(stable_raw, lower=True) or [x.lower() for x in stable_default]

    return Settings(
        # Aerodrome
        AERO_QUOTER=os.getenv("AERO_QUOTER", "0x254cF9E1E6e233aa1AC962CB9B05b2cfeAaE15b0"),
        AERO_ROUTER=os.getenv("AERO_ROUTER", "0xBE6D8f0d05cC4be24d5167a3eF062215bE6D18a5"),
        AERO_ROUTER_AMM=os.getenv("AERO_ROUTER_AMM", "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"),
        AERO_TICK_SPACINGS=os.getenv("AERO_TICK_SPACINGS", "1,10,100"),
        AERO_POOL_FACTORY_AMM=os.getenv("AERO_POOL_FACTORY_AMM", "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"),

        # Pancake
        PANCAKE_V3_QUOTER=os.getenv("PANCAKE_QUOTER", "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"),
        PANCAKE_V3_ROUTER=os.getenv("PANCAKE_V3_ROUTER", "0x1b81D678ffb9C0263b24A97847620C99d213eB14"),
        PANCAKE_FACTORY=os.getenv("PANCAKE_FACTORY", "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"),
        PANCAKE_TICK_SPACINGS=os.getenv("PANCAKE_TICK_SPACINGS", "1,10,100"),
        PANCAKE_MASTERCHEF_V3=os.getenv("PANCAKE_MASTERCHEF_V3", "0xC6A2Db661D5a5690172d8eB0a7DEA2d3008665A3"),

        # Uniswap
        UNI_V3_ROUTER=os.getenv("UNI_V3_ROUTER", "0x2626664c2603336E57B271c5C0b26F421741e481"),
        UNI_V3_QUOTER=os.getenv("UNI_V3_QUOTER", "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"),
        DEFAULT_SWAP_POOL_FEE=int(os.getenv("DEFAULT_SWAP_POOL_FEE", "3000")),

        # Core chain
        PRIVATE_KEY=os.getenv("PRIVATE_KEY", ""),
        RPC_URL_DEFAULT=os.getenv("RPC_SEPOLIA", ""),  # keep as-is, but name suggests you may rename later
        STABLE_TOKEN_ADDRESSES=stable_list,

        # Mongo
        MONGO_URI=os.getenv("MONGO_URI", "mongodb://mongo-lp:27017/lp_vaults"),
        MONGO_DB=os.getenv("MONGO_DB", "lp_vaults"),

        # Contracts
        STRATEGY_REGISTRY_ADDRESS=os.getenv("STRATEGY_REGISTRY_ADDRESS", ""),
        VAULT_FACTORY_ADDRESS=os.getenv("VAULT_FACTORY_ADDRESS", ""),

        # Admin / Privy Auth (NEW)
        PRIVY_APP_ID=os.getenv("PRIVY_APP_ID", ""),
        PRIVY_JWKS_URL=os.getenv("PRIVY_JWKS_URL", "https://auth.privy.io/api/v1/apps/jwks"),
        ADMIN_WALLETS=os.getenv("ADMIN_WALLETS", ""),
        PRIVY_APP_SECRET=os.getenv("PRIVY_APP_SECRET", ""),
    )
