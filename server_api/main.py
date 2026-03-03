from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import secrets
import time
import os
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv(".env")
import requests
from server_api.db import init_db, get_chat_id_by_phone
from server_api.telegram_utils import telegram_send_message

from server_api.db import init_db, list_events, insert_event

app = FastAPI(title="Videovigilancia")
#inicializa SQLite
init_db()

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
    method: str = "qr"            # "qr" | "telegram" | "telegram_phone"
    serverUrl: str | None = None
    phone: str | None = None      # usado en telegram_phone

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

class EventIn(BaseModel):
    ts: str
    type: str
    cameraId: str | None = None
    confidence: float | None = None
    message: str | None = None
    snapshotPath: str | None = None

class EventOut(BaseModel):
    id: str
    ts: str
    type: str
    cameraId: str | None = None
    confidence: float | None = None
    message: str | None = None
    snapshotPath: str | None = None


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

    # ✅ DEFINIR ttl SIEMPRE ANTES DE USARLO
    ttl = PAIRING_TTL

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

    # --- TELEGRAM (bot + start) ---
    if method == "telegram":
        start_payload = f"PAIR_{pairing_id}"
        start_url = f"https://t.me/{TELEGRAM_BOT_USERNAME}?start={start_payload}"
        return {
            "pairingId": pairing_id,
            "ttlSeconds": ttl,
            "telegramStartUrl": start_url,
        }

    # --- TELEGRAM POR NÚMERO (Sprint 1.3) ---
    if method == "telegram_phone":
        phone = (req.phone or "").strip().replace(" ", "")
        if not phone:
            raise HTTPException(status_code=400, detail="phone is required")
        if not phone.startswith("+"):
            raise HTTPException(status_code=400, detail="phone must be E.164 format (e.g. +346XXXXXXXX)")

        chat_id = get_chat_id_by_phone(phone)

        # No vinculado -> devolvemos link LINK_<pairingId>
        if chat_id is None:
            start_payload = f"LINK_{pairing_id}"
            start_url = f"https://t.me/{TELEGRAM_BOT_USERNAME}?start={start_payload}"
            return {
                "pairingId": pairing_id,
                "ttlSeconds": ttl,
                "telegramStartUrl": start_url,
            }

        # Vinculado -> enviamos OTP directo por Telegram (Bot API sendMessage) 
        telegram_send_message(
            chat_id,
            f"✅ Tu OTP es: {otp}\n"
            f"⏳ Caduca en {ttl} segundos.\n\n"
            "Vuelve a Videovigilancia Mobile y confirma."
        )
        return {
            "pairingId": pairing_id,
            "ttlSeconds": ttl,
            "telegramStartUrl": None,
        }

    # --- QR (por defecto) ---
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

@app.get("/events")
def get_events(limit: int = 50):
    limit = max(1, min(limit, 200))
    return {"items": list_events(limit=limit)}

@app.post("/events")
def post_event(ev: EventIn):
    # Para pruebas (luego lo blindamos con auth)
    event_id = insert_event(
        ts=ev.ts,
        type_=ev.type,
        camera_id=ev.cameraId,
        confidence=ev.confidence,
        message=ev.message,
        snapshot_path=ev.snapshotPath,
    )
    return {"ok": True, "id": event_id}