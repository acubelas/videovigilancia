from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import secrets
import time
from dataclasses import dataclass

app = FastAPI(title="Videovigilancia")

PAIRING_TTL = 600  # 10 min
MAX_ATTEMPTS = 5

@dataclass
class PairingSession:
    pairing_id: str
    code: str
    created_at: float
    used: bool = False
    attempts: int = 0

# En memoria (por ahora). OJO: si reinicias uvicorn, se pierde.
pairings: dict[str, PairingSession] = {}


# ---------- MODELOS ----------
class PairingRequestIn(BaseModel):
    method: str = "qr"  # por ahora solo "qr", luego añadimos "email"/"telegram"
    # serverUrl se usa solo para construir qrPayload en respuesta (dev)
    serverUrl: str | None = None


class PairingRequestOut(BaseModel):
    pairingId: str
    ttlSeconds: int
    # Para desarrollo: devolvemos el OTP para que el servidor lo muestre.
    # En producción esto se devolvería solo a un panel admin o no se devolvería.
    otp: str
    qrPayload: dict


class PairingConfirmIn(BaseModel):
    pairingId: str
    code: str
    deviceId: str | None = None
    deviceName: str | None = None


class PairingConfirmOut(BaseModel):
    accessToken: str


# ---------- ENDPOINTS ----------
@app.get("/health")
def health():
    return {"ok": True, "app": "Videovigilancia"}


@app.post("/pairing/request", response_model=PairingRequestOut)
def pairing_request(req: PairingRequestIn):
    # pairingId corto y otp 6 dígitos
    pairing_id = "P_" + secrets.token_urlsafe(6)
    otp = f"{secrets.randbelow(1_000_000):06d}"

    pairings[pairing_id] = PairingSession(
        pairing_id=pairing_id,
        code=otp,
        created_at=time.time(),
        used=False,
        attempts=0,
    )

    server_url = (req.serverUrl or "").strip()
    qr_payload = {"serverUrl": server_url, "pairingId": pairing_id}

    return {
        "pairingId": pairing_id,
        "ttlSeconds": PAIRING_TTL,
        "otp": otp,
        "qrPayload": qr_payload,
    }


@app.post("/pairing/confirm", response_model=PairingConfirmOut)
def pairing_confirm(req: PairingConfirmIn):
    pairing_id = req.pairingId.strip()
    code = req.code.strip()

    sess = pairings.get(pairing_id)
    if not sess:
        raise HTTPException(status_code=400, detail="Invalid pairingId")

    # TTL
    if (time.time() - sess.created_at) > PAIRING_TTL:
        raise HTTPException(status_code=400, detail="Expired code")

    # one-time
    if sess.used:
        raise HTTPException(status_code=400, detail="Code already used")

    sess.attempts += 1
    if sess.attempts > MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts")

    if code != sess.code:
        raise HTTPException(status_code=400, detail="Invalid code")

    sess.used = True

    # Token simple para dev (luego JWT si quieres)
    token = secrets.token_urlsafe(24)
    return {"accessToken": token}


# (Opcional) Raíz para que no haya 404 si abres en Safari
@app.get("/")
def index():
    return {
        "ok": True,
        "message": "Videovigilancia API",
        "endpoints": ["/health", "/pairing/request", "/pairing/confirm"],
    }