# core/use_cases/vaults_registry_usecase.py

import json
from pathlib import Path
from datetime import datetime

from fastapi import HTTPException
from web3 import Web3

from config import get_settings
from adapters.external.database import state_repo, vault_repo
from core.domain.models import (
    DexName,
    VaultList,
    VaultRow,
    AddVaultRequest,
    SetPoolRequest,
    DeployVaultRequest,
    StatusResponse,
    StatusCore,
    BaselineRequest,
)
from core.services.exceptions import TransactionRevertedError
from core.services.tx_service import TxService
from core.services.status_service import (
    compute_status,
)
from core.services.vault_adapter_service import get_adapter_for
from routes.utils import ZERO_ADDR, normalize_swap_pools_input  # mantendo helper já existente


def list_vaults_uc(dex: DexName) -> VaultList:
    data = vault_repo.list_vaults(dex)
    rows = [
        VaultRow(alias=alias, dex=dex, **v)
        for alias, v in data.get("vaults", {}).items()
    ]
    return VaultList(active=data.get("active"), vaults=rows)


def add_vault_uc(dex: str, req: AddVaultRequest) -> dict:
    row = {
        "address": req.address,
        "pool": req.pool,
        "nfpm": req.nfpm,
        "rpc_url": req.rpc_url,
    }
    vault_repo.add_vault(dex, req.alias, row)

    state_repo.ensure_state_initialized(
        dex,
        req.alias,
        vault_address=req.address,
        nfpm=req.nfpm,
        pool=req.pool,
    )
    state_repo.append_history(
        dex,
        req.alias,
        "exec_history",
        {
            "ts": datetime.utcnow().isoformat(),
            "mode": "registry_add",
            "vault": req.address,
            "pool": req.pool,
            "nfpm": req.nfpm,
            "tx": None,
        },
    )
    return {"ok": True}


def set_pool_uc(dex: str, alias: str, req: SetPoolRequest) -> dict:
    v = vault_repo.get_vault(dex, alias)
    if not v:
        raise HTTPException(404, "Unknown alias")
    if not v.get("pool"):
        raise HTTPException(400, "Vault has no pool set")

    vault_repo.set_pool(dex, alias, req.pool)

    state_repo.ensure_state_initialized(dex, alias, vault_address=v["address"])
    state_repo.update_state(dex, alias, {"pool": req.pool})
    state_repo.append_history(
        dex,
        alias,
        "exec_history",
        {
            "ts": datetime.utcnow().isoformat(),
            "mode": "set_pool",
            "pool": req.pool,
            "tx": None,
        },
    )
    return {"ok": True}


def status_uc(dex: str, alias: str) -> StatusResponse:
    v = vault_repo.get_vault(dex, alias)
    if not v:
        raise HTTPException(404, "Unknown alias")
    if not v.get("pool"):
        raise HTTPException(400, "Vault has no pool set")

    ad = get_adapter_for(
        dex,
        v["pool"],
        v.get("nfpm"),
        v["address"],
        v.get("rpc_url"),
        v.get("gauge"),
    )

    # extra validation for Aerodrome
    if dex == "aerodrome":
        try:
            ad.assert_is_pool()
        except Exception as e:
            raise HTTPException(400, f"Invalid Slipstream pool address: {e}")

    core: StatusCore = compute_status(ad, dex, alias)
    return StatusResponse(
        alias=alias,
        vault=v["address"],
        pool=v.get("pool"),
        **core.model_dump(),
    )


def baseline_uc(dex: str, alias: str, req: BaselineRequest) -> dict:
    if req.action == "set":
        v = vault_repo.get_vault(dex, alias)
        if not v or not v.get("pool"):
            raise HTTPException(400, "Vault has no pool set")

        state_repo.ensure_state_initialized(dex, alias, vault_address=v["address"])
        st = state_repo.load_state(dex, alias)

        ad = get_adapter_for(
            dex,
            v["pool"],
            v.get("nfpm"),
            v["address"],
            v.get("rpc_url"),
            v.get("gauge"),
        )
        s: StatusCore = compute_status(ad, dex, alias)
        baseline_usd = float(s.usd_panel.usd_value)
        st["vault_initial_usd"] = baseline_usd
        st["baseline_set_ts"] = datetime.utcnow().isoformat()
        state_repo.save_state(dex, alias, st)

        state_repo.append_history(
            dex,
            alias,
            "exec_history",
            {
                "ts": datetime.utcnow().isoformat(),
                "mode": "baseline_set",
                "baseline_usd": baseline_usd,
                "tx": None,
            },
        )
        return {"ok": True, "baseline_usd": st["vault_initial_usd"]}

    st = state_repo.load_state(dex, alias)
    return {"baseline_usd": float(st.get("vault_initial_usd", 0.0) or 0.0)}


def deploy_vault_uc(dex: str, req: DeployVaultRequest) -> dict:
    """
    Deploy flow (artifact mode, default):
      1) Deploy the DEX-specific on-chain Adapter
      2) Deploy SingleUserVaultV2(owner)
      3) vault.setPoolOnce(adapter)
      4) Save registry/state

    Back-compat: if req.version == "v1", keep the old artifact path & constructor.
    """
    s = get_settings()
    rpc = req.rpc_url or s.RPC_URL_DEFAULT
    txs = TxService(rpc)
    w3 = txs.w3

    owner = Web3.to_checksum_address(req.owner) if req.owner else txs.sender_address()
    normalized_swap_pools = normalize_swap_pools_input(dex, req.swap_pools)

    # 1) Deploy adapter
    if dex == "uniswap":
        adapter_art_path = Path("out/UniV3Adapter.sol/UniV3Adapter.json")
        if not adapter_art_path.exists():
            raise HTTPException(501, "Adapter artifact (Uniswap) not found")
        aart = json.loads(adapter_art_path.read_text())
        aabi = aart["abi"]
        abyte = (
            aart["bytecode"]["object"]
            if isinstance(aart["bytecode"], dict)
            else aart["bytecode"]
        )
        adapter_res = txs.deploy(
            abi=aabi,
            bytecode=abyte,
            ctor_args=[
                Web3.to_checksum_address(req.nfpm),
                Web3.to_checksum_address(req.pool),
            ],
            wait=True,
        )
        adapter_addr = adapter_res["address"]

    elif dex == "aerodrome":
        adapter_art_path = Path("out/SlipstreamAdapter.sol/SlipstreamAdapter.json")
        if not adapter_art_path.exists():
            raise HTTPException(501, "Adapter artifact (Aerodrome) not found")
        aart = json.loads(adapter_art_path.read_text())
        aabi = aart["abi"]
        abyte = (
            aart["bytecode"]["object"]
            if isinstance(aart["bytecode"], dict)
            else aart["bytecode"]
        )
        ctor = [
            Web3.to_checksum_address(req.pool),
            Web3.to_checksum_address(req.nfpm),
        ]
        if req.gauge:
            ctor.append(Web3.to_checksum_address(req.gauge))
        adapter_res = txs.deploy(abi=aabi, bytecode=abyte, ctor_args=ctor, wait=True)
        adapter_addr = adapter_res["address"]

    elif dex == "pancake":
        HERE = Path(__file__).resolve()
        PROJECT_ROOT = HERE.parents[2]  # /app (ajuste se necessário)

        adapter_art_path = (
            PROJECT_ROOT / "out" / "PancakeV3Adapter.sol" / "PancakeV3Adapter.json"
        )
        if not adapter_art_path.exists():
            raise HTTPException(501, "Adapter artifact (Pancake) not found")
        aart = json.loads(adapter_art_path.read_text())
        aabi = aart["abi"]
        abyte = (
            aart["bytecode"]["object"]
            if isinstance(aart["bytecode"], dict)
            else aart["bytecode"]
        )
        ctor = [
            Web3.to_checksum_address(req.pool),
            Web3.to_checksum_address(req.nfpm),
            Web3.to_checksum_address(req.gauge)
            if req.gauge
            else Web3.to_checksum_address(ZERO_ADDR),
        ]
        adapter_res = txs.deploy(abi=aabi, bytecode=abyte, ctor_args=ctor, wait=True)
        adapter_addr = adapter_res["address"]

    else:
        raise HTTPException(400, "Unsupported dex for V2")

    # 2) Deploy SingleUserVaultV2(owner)
    HERE = Path(__file__).resolve()
    PROJECT_ROOT = HERE.parents[2]  # /app

    v2_path = PROJECT_ROOT / "out" / "SingleUserVaultV2.sol" / "SingleUserVaultV2.json"
    if not v2_path.exists():
        raise HTTPException(501, "Vault V2 artifact not found")
    vart = json.loads(v2_path.read_text())
    vabi = vart["abi"]
    vbyte = (
        vart["bytecode"]["object"]
        if isinstance(vart["bytecode"], dict)
        else vart["bytecode"]
    )

    vres = txs.deploy(abi=vabi, bytecode=vbyte, ctor_args=[owner], wait=True)
    vault_addr = vres["address"]
    vault = w3.eth.contract(address=Web3.to_checksum_address(vault_addr), abi=vabi)
    
    try:
        vault.functions.setPoolOnce(Web3.to_checksum_address(adapter_addr)).call()
        print("[SET_POOL_ONCE] static call: OK")
    except Exception as e:
        print("[SET_POOL_ONCE] static call REVERT:", e)
        
    # 3) setPoolOnce(adapter)
    try:
        tx_res = txs.send(
            vault.functions.setPoolOnce(Web3.to_checksum_address(adapter_addr)),
            wait=True,
            gas_strategy="aggressive"
        )
        print("[SET_POOL_ONCE] tx_res:", tx_res)
    except TransactionRevertedError as e:
        print("[SET_POOL_ONCE] REVERTED")
        print("  tx_hash:", e.tx_hash)
        print("  receipt:", e.receipt)
        print("  msg:", e.msg)
        raise HTTPException(500, f"setPoolOnce reverted: {e.msg}")
    except Exception as e:
        print("[SET_POOL_ONCE] OTHER ERROR:", repr(e))
        raise HTTPException(500, f"setPoolOnce failed (generic): {e}")

    # 4) registry/state
    vault_repo.add_vault(
        dex,
        req.alias,
        {
            "address": vault_addr,
            "adapter": adapter_addr,
            "pool": req.pool,
            "nfpm": req.nfpm,
            "gauge": req.gauge,
            "rpc_url": req.rpc_url,
            "version": "v2",
            "swap_pools": normalized_swap_pools,
        },
    )
    state_repo.ensure_state_initialized(
        dex,
        req.alias,
        vault_address=vault_addr,
        nfpm=req.nfpm,
        pool=req.pool,
        gauge=req.gauge,
    )
    vault_repo.set_active(dex, req.alias)

    state_repo.append_history(
        dex,
        req.alias,
        "exec_history",
        {
            "ts": datetime.utcnow().isoformat(),
            "mode": "deploy_vault_v2",
            "vault": vault_addr,
            "adapter": adapter_addr,
            "pool": req.pool,
            "nfpm": req.nfpm,
            "gauge": req.gauge,
            "tx_adapter": adapter_res["tx"],
            "tx_vault": vres["tx"],
        },
    )

    return {
        "tx_vault": vres["tx"],
        "tx_adapter": adapter_res["tx"],
        "vault": vault_addr,
        "adapter": adapter_addr,
        "alias": req.alias,
        "dex": dex,
        "version": "v2",
        "owner": owner,
    }
