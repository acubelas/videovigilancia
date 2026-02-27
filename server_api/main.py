from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import secrets
import time

app = FastAPI(title="Videovigilancia")

PAIRING_TTL = 120  # segundos (QR válido 2 min)
pairing_codes = {}  # code -> created_at (epoch)

class PairRequest(BaseModel):
    pairingCode: str

@app.get("/health")
def health():
    return {"ok": True, "app": "Videovigilancia"}

@app.post("/pairing/code")
def create_pairing_code():
    code = secrets.token_urlsafe(8)
    pairing_codes[code] = time.time()
    return {"pairingCode": code, "ttlSeconds": PAIRING_TTL}

@app.post("/pair")
def pair(req: PairRequest):
    code = req.pairingCode.strip()
    created = pairing_codes.get(code)

    if not created:
        raise HTTPException(status_code=400, detail="Invalid pairing code")
    if (time.time() - created) > PAIRING_TTL:
        raise HTTPException(status_code=400, detail="Expired pairing code")

    # one-time use
    del pairing_codes[code]

    # token simple (demo). Luego lo hacemos JWT si quieres.
    token = secrets.token_urlsafe(24)
    return {"accessToken": token}