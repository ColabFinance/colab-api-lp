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

    # signing / chain
    RPC_URL_DEFAULT: str
    PRIVATE_KEY: str

    # on-chain registry / factory
    STRATEGY_REGISTRY_ADDRESS: str
    VAULT_FACTORY_ADDRESS: str

    # ---- Admin / Privy Auth ----
    PRIVY_APP_ID: str
    PRIVY_APP_SECRET: str
    PRIVY_JWKS_URL: str
    ADMIN_WALLETS: str 

    API_SIGNALS_URL: str
    API_MARKET_DATA_URL: str
    
    # generic
    ENV: str = Field(default="dev")
    LOG_LEVEL: str = Field(default="INFO")

    STABLE_TOKEN_ADDRESSES: List[str] = field(default_factory=list)


@lru_cache()
def get_settings() -> Settings:
    stable_default = [
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "0x1c7d4b196cb0c7b01d743fbc6116a902379c7238",
    ]

    stable_raw = os.getenv("STABLE_TOKEN_ADDRESSES", "")
    stable_list = _parse_csv(stable_raw) or [x for x in stable_default]

    return Settings(
        # Core chain
        PRIVATE_KEY=os.getenv("PRIVATE_KEY", ""),
        RPC_URL_DEFAULT=os.getenv("RPC_URL_DEFAULT", ""),  # keep as-is, but name suggests you may rename later
        STABLE_TOKEN_ADDRESSES=stable_list,

        # Mongo
        MONGO_URI=os.getenv("MONGO_URI", "mongodb://mongo-lp:27017/lp_vaults"),
        MONGO_DB=os.getenv("MONGO_DB", "lp_vaults"),

        # Contracts
        STRATEGY_REGISTRY_ADDRESS=os.getenv("STRATEGY_REGISTRY_ADDRESS", ""),
        VAULT_FACTORY_ADDRESS=os.getenv("VAULT_FACTORY_ADDRESS", ""),

        # Admin / Privy Auth
        PRIVY_APP_ID=os.getenv("PRIVY_APP_ID", ""),
        PRIVY_JWKS_URL=os.getenv("PRIVY_JWKS_URL", "https://auth.privy.io/api/v1/apps/jwks"),
        ADMIN_WALLETS=os.getenv("ADMIN_WALLETS", ""),
        PRIVY_APP_SECRET=os.getenv("PRIVY_APP_SECRET", ""),
        
        API_SIGNALS_URL=os.getenv("API_SIGNALS_URL", "http://172.17.0.1:8080"),
        API_MARKET_DATA_URL=os.getenv("API_MARKET_DATA_URL", "http://172.17.0.1:8081"),
    )
