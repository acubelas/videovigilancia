from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import secrets
import time
import os
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv(".env")

app = FastAPI(title="Videovigilancia")

# --- Config desde entorno (.env) ---
PAIRING_TTL = int(os.getenv("PAIRING_TTL_SECONDS", "600"))  # 10 min
MAX_ATTEMPTS = int(os.getenv("PAIRING_MAX_ATTEMPTS", "5"))

BOT_SHARED_SECRET = os.getenv("BOT_SHARED_SECRET", "")
TAILSCALE_SERVER_URL = os.getenv("TAILSCALE_SERVER_URL", "http://100.88.172.7:8080")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "acubelasbot")

# --- Modelo de sesión de emparejamiento ---
@dataclass
class PairingSession:
    pairing_id: str
    code: str
    created_at: float
    used: bool = False
    attempts: int = 0

# En memoria (por ahora). Si reinicias uvicorn, se pierde.
pairings: dict[str, PairingSession] = {}

# --- Modelos API ---
class PairingRequestIn(BaseModel):
    method: str = "qr"           # "qr" | "telegram"
    serverUrl: str | None = None # para construir el payload QR

class PairingRequestOut(BaseModel):
    pairingId: str
    ttlSeconds: int
    otp: str | None = None
    qrPayload: dict | None = None
    telegramStartUrl: str | None = None

class PairingConfirmIn(BaseModel):
    pairingId: str
    code: str
    deviceId: str | None = None
    deviceName: str | None = None

class PairingConfirmOut(BaseModel):
    accessToken: str

# --- Endpoints ---
@app.get("/health")
def health():
    return {"ok": True, "app": "Videovigilancia"}

@app.get("/")
def index():
    return {
        "ok": True,
        "message": "Videovigilancia API",
        "endpoints": ["/health", "/pairing/request", "/pairing/confirm", "/pairing/otp/{pairingId}"],
    }

@app.post("/pairing/request", response_model=PairingRequestOut)
def pairing_request(req: PairingRequestIn):
    method = (req.method or "qr").strip().lower()

    pairing_id = "P_" + secrets.token_urlsafe(6)
    otp = f"{secrets.randbelow(1_000_000):06d}"

    pairings[pairing_id] = PairingSession(
        pairing_id=pairing_id,
        code=otp,
        created_at=time.time(),
        used=False,
        attempts=0,
    )

    public_url = (req.serverUrl or TAILSCALE_SERVER_URL).strip()
    ttl = PAIRING_TTL

    if method == "telegram":
        start_payload = f"PAIR_{pairing_id}"
        start_url = f"https://t.me/{TELEGRAM_BOT_USERNAME}?start={start_payload}"
        return {
            "pairingId": pairing_id,
            "ttlSeconds": ttl,
            "telegramStartUrl": start_url,
        }

    qr_payload = {"serverUrl": public_url, "pairingId": pairing_id}
    return {
        "pairingId": pairing_id,
        "ttlSeconds": ttl,
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

    if (time.time() - sess.created_at) > PAIRING_TTL:
        raise HTTPException(status_code=400, detail="Expired code")

    if sess.used:
        raise HTTPException(status_code=400, detail="Code already used")

    sess.attempts += 1
    if sess.attempts > MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts")

    if code != sess.code:
        raise HTTPException(status_code=400, detail="Invalid code")

    sess.used = True
    token = secrets.token_urlsafe(24)
    return {"accessToken": token}

# Endpoint PRIVADO para el bot: obtener OTP de un pairingId
@app.get("/pairing/otp/{pairing_id}")
def pairing_get_otp(pairing_id: str, x_bot_secret: str | None = Header(default=None)):
    if not BOT_SHARED_SECRET:
        raise HTTPException(status_code=500, detail="BOT_SHARED_SECRET not configured")

    if x_bot_secret != BOT_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized bot")

    sess = pairings.get(pairing_id)
    if not sess:
        raise HTTPException(status_code=404, detail="pairingId not found")

    if sess.used:
        raise HTTPException(status_code=400, detail="Code already used")

    age = time.time() - sess.created_at
    if age > PAIRING_TTL:
        raise HTTPException(status_code=400, detail="Expired code")

    remaining = int(PAIRING_TTL - age)
    return {"pairingId": pairing_id, "otp": sess.code, "ttlRemaining": remaining}
