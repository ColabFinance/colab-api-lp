from __future__ import annotations
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from adapters.entry.http.dtos.vault_user_events_dtos import (
    VaultUserEventDepositIn,
    VaultUserEventTransfer,
    VaultUserEventWithdrawIn,
    VaultUserEventOut,
    VaultUserEventsListOut,
)
from core.use_cases.vault_user_events_usecase import VaultUserEventsUseCase

router = APIRouter(prefix="/vaults", tags=["vault-user-events"])


def _normalize_transfers(raw: Any) -> Optional[List[VaultUserEventTransfer]]:
    if not raw:
        return None
    return [VaultUserEventTransfer.model_validate(t, from_attributes=True) for t in raw]


def get_use_case() -> VaultUserEventsUseCase:
    return VaultUserEventsUseCase.from_settings()


@router.post(
    "/{alias_or_address}/events/deposit",
    response_model=VaultUserEventOut,
    summary="Persist a user deposit event (frontend confirmed tx) into Mongo (vault_user_events)",
)
async def record_deposit(
    alias_or_address: str,
    body: VaultUserEventDepositIn,
    use_case: VaultUserEventsUseCase = Depends(get_use_case),
):
    try:
        saved = use_case.record_deposit(
            alias_or_address=alias_or_address,
            chain=body.chain,
            dex=body.dex,
            owner=body.owner,
            token=body.token,
            amount_human=body.amount_human,
            amount_raw=body.amount_raw,
            decimals=body.decimals,
            tx_hash=body.tx_hash,
            receipt=body.receipt,
            from_addr=body.from_addr,
            to_addr=body.to_addr,
        )
        
        transfers = _normalize_transfers(getattr(saved, "transfers", None))
        
        return VaultUserEventOut(
            id=saved.id,
            vault=saved.vault,
            alias=getattr(saved, "alias", None),
            chain=saved.chain,
            dex=getattr(saved, "dex", None),
            event_type=saved.event_type,
            owner=getattr(saved, "owner", None),
            token=getattr(saved, "token", None),
            amount_human=getattr(saved, "amount_human", None),
            amount_raw=getattr(saved, "amount_raw", None),
            decimals=getattr(saved, "decimals", None),
            to=getattr(saved, "to", None),
            transfers=transfers,
            tx_hash=saved.tx_hash,
            block_number=getattr(saved, "block_number", None),
            ts_ms=int(getattr(saved, "ts_ms", 0) or 0),
            ts_iso=str(getattr(saved, "ts_iso", "") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to persist deposit event: {exc}") from exc


@router.post(
    "/{alias_or_address}/events/withdraw",
    response_model=VaultUserEventOut,
    summary="Persist a user withdraw event (frontend confirmed tx) into Mongo (vault_user_events)",
)
async def record_withdraw(
    alias_or_address: str,
    body: VaultUserEventWithdrawIn,
    use_case: VaultUserEventsUseCase = Depends(get_use_case),
):
    try:
        saved = use_case.record_withdraw(
            alias_or_address=alias_or_address,
            chain=body.chain,
            dex=body.dex,
            owner=body.owner,
            to=body.to,
            tx_hash=body.tx_hash,
            receipt=body.receipt,
            token_addresses=body.token_addresses,
        )
        
        transfers = _normalize_transfers(getattr(saved, "transfers", None))

        return VaultUserEventOut(
            id=saved.id,
            vault=saved.vault,
            alias=getattr(saved, "alias", None),
            chain=saved.chain,
            dex=getattr(saved, "dex", None),
            event_type=saved.event_type,
            owner=getattr(saved, "owner", None),
            token=getattr(saved, "token", None),
            amount_human=getattr(saved, "amount_human", None),
            amount_raw=getattr(saved, "amount_raw", None),
            decimals=getattr(saved, "decimals", None),
            to=getattr(saved, "to", None),
            transfers=transfers,
            tx_hash=saved.tx_hash,
            block_number=getattr(saved, "block_number", None),
            ts_ms=int(getattr(saved, "ts_ms", 0) or 0),
            ts_iso=str(getattr(saved, "ts_iso", "") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to persist withdraw event: {exc}") from exc


@router.get(
    "/{alias_or_address}/events",
    response_model=VaultUserEventsListOut,
    summary="List user events for a vault (Mongo only)",
)
async def list_events(
    alias_or_address: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    use_case: VaultUserEventsUseCase = Depends(get_use_case),
):
    try:
        out = use_case.list_events(alias_or_address=alias_or_address, limit=limit, offset=offset)
        items = out.get("items") or []
        total = out.get("total")

        data = []
        for it in items:
            transfers = _normalize_transfers(getattr(it, "transfers", None))

            data.append(
                VaultUserEventOut(
                    id=it.id,
                    vault=it.vault,
                    alias=getattr(it, "alias", None),
                    chain=it.chain,
                    dex=getattr(it, "dex", None),
                    event_type=it.event_type,
                    owner=getattr(it, "owner", None),
                    token=getattr(it, "token", None),
                    amount_human=getattr(it, "amount_human", None),
                    amount_raw=getattr(it, "amount_raw", None),
                    decimals=getattr(it, "decimals", None),
                    to=getattr(it, "to", None),
                    transfers=transfers,
                    tx_hash=it.tx_hash,
                    block_number=getattr(it, "block_number", None),
                    ts_ms=int(getattr(it, "ts_ms", 0) or 0),
                    ts_iso=str(getattr(it, "ts_iso", "") or ""),
                )
            )

        return VaultUserEventsListOut(ok=True, message="ok", data=data, total=int(total) if total is not None else None)

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list vault events: {exc}") from exc
