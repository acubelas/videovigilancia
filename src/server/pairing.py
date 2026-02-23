# src/server/pairing.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import time

from .storage import new_pair_code, claim_pair_code

router = APIRouter(prefix="/api/pair", tags=["pairing"])


class PairRequestResponse(BaseModel):
    pair_code: str
    expires_at: int


class PairClaimRequest(BaseModel):
    pair_code: str
    device_name: str | None = None
    platform: str | None = None


class PairClaimResponse(BaseModel):
    device_id: str
    paired_at: int


@router.post("/request", response_model=PairRequestResponse)
def pair_request():
    code, expires_at = new_pair_code(ttl_seconds=300)  # 5 min
    return PairRequestResponse(pair_code=code, expires_at=expires_at)


@router.post("/claim", response_model=PairClaimResponse)
def pair_claim(body: PairClaimRequest):
    device_id = claim_pair_code(
        code=body.pair_code.strip(),
        device_name=(body.device_name or "").strip(),
        platform=(body.platform or "").strip(),
    )
    if not device_id:
        raise HTTPException(status_code=400, detail="pair_code inválido, expirado o ya usado")

    return PairClaimResponse(device_id=device_id, paired_at=int(time.time()))