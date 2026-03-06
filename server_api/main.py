from __future__ import annotations

import os
import time
import secrets
from dataclasses import dataclass

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel

from fastapi.responses import FileResponse
import os


from server_api.db import (
    init_db, get_chat_id_by_phone, list_events, insert_event,
    upsert_session, session_is_valid, get_event_snapshot_path,
    delete_event,  # 👈 AÑADIR
    )

from server_api.telegram_utils import telegram_send_message
from pathlib import Path

from server_api.db import delete_event  # añade este import

# ------------------------------------------------------------
# ENV
# ------------------------------------------------------------
load_dotenv(".env")

PAIRING_TTL = int(os.getenv("PAIRING_TTL_SECONDS", "600"))
MAX_ATTEMPTS = int(os.getenv("PAIRING_MAX_ATTEMPTS", "5"))

BOT_SHARED_SECRET = os.getenv("BOT_SHARED_SECRET", "")
TAILSCALE_SERVER_URL = os.getenv("TAILSCALE_SERVER_URL", "http://100.88.172.7:8080")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "acubelasbot")

app = FastAPI(title="Videovigilancia")

# Inicializa SQLite (telegram_links, events, sessions, etc.)
init_db()

# ------------------------------------------------------------
# Pairing sessions (memoria)
# ------------------------------------------------------------
@dataclass
class PairingSession:
    pairing_id: str
    code: str
    created_at: float
    used: bool = False
    attempts: int = 0


# OJO: si reinicias uvicorn se pierde el dict (normal en Sprint actual)
pairings: dict[str, PairingSession] = {}

# ------------------------------------------------------------
# Models
# ------------------------------------------------------------
class PairingRequestIn(BaseModel):
    method: str = "qr"            # "qr" | "telegram" | "telegram_phone"
    serverUrl: str | None = None
    phone: str | None = None      # usado en telegram_phone (E.164)


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
    snapshotBase64: str | None = None  # 👈 para test
# ------------------------------------------------------------
# Auth (Sprint 2.2)
# ------------------------------------------------------------
def require_auth(authorization: str | None = Header(default=None)) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization format (expected Bearer token)")

    token = parts[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    if not session_is_valid(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # ✅ NUEVO: actualizar last_seen_at en cada request autenticada
    upsert_session(token)

    return token


# ------------------------------------------------------------
# Basic endpoints
# ------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True, "app": "Videovigilancia"}


@app.get("/")
def index():
    return {
        "ok": True,
        "message": "Videovigilancia API",
        "endpoints": [
            "/health",
            "/pairing/request",
            "/pairing/confirm",
            "/pairing/otp/{pairingId}",
            "/events",
        ],
    }


# ------------------------------------------------------------
# Pairing endpoints
# ------------------------------------------------------------
@app.post("/pairing/request", response_model=PairingRequestOut)
def pairing_request(req: PairingRequestIn):
    method = (req.method or "qr").strip().lower()

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

    # ---- Telegram: bot + Start (Sprint 1.2) ----
    if method == "telegram":
        start_payload = f"PAIR_{pairing_id}"
        start_url = f"https://t.me/{TELEGRAM_BOT_USERNAME}?start={start_payload}"
        return {
            "pairingId": pairing_id,
            "ttlSeconds": ttl,
            "telegramStartUrl": start_url,
        }

    # ---- Telegram por número (Sprint 1.3) ----
    if method == "telegram_phone":
        phone = (req.phone or "").strip().replace(" ", "")
        if not phone:
            raise HTTPException(status_code=400, detail="phone is required")
        if not phone.startswith("+"):
            raise HTTPException(status_code=400, detail="phone must be E.164 format (e.g. +346XXXXXXXX)")

        chat_id = get_chat_id_by_phone(phone)

        # No vinculado: devolver link LINK_<pairingId>
        if chat_id is None:
            start_payload = f"LINK_{pairing_id}"
            start_url = f"https://t.me/{TELEGRAM_BOT_USERNAME}?start={start_payload}"
            return {
                "pairingId": pairing_id,
                "ttlSeconds": ttl,
                "telegramStartUrl": start_url,
            }

        # Vinculado: enviar OTP directo al chat_id
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

    # ---- QR (por defecto) ----
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

    # Crear token + persistir sesión en SQLite (Sprint 2.2)
    token = secrets.token_urlsafe(24)
    upsert_session(token)

    return {"accessToken": token}


# ------------------------------------------------------------
# Private endpoint for Telegram bot to fetch OTP
# ------------------------------------------------------------
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

# ------------------------------------------------------------
# Events endpoints (Sprint 2.3: protected + snapshots robustos)
# ------------------------------------------------------------
import base64
from pathlib import Path
from datetime import datetime, timezone
from pydantic import BaseModel, Field

MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", "2000000"))  # 2MB por defecto

SNAP_DIR = Path(os.getenv("SNAP_DIR", "data/snapshots"))
SNAP_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_b64(raw: str) -> str:
    """Acepta base64 puro o data URL 'data:image/jpeg;base64,...'."""
    s = (raw or "").strip().replace("\n", "").replace("\r", "")
    if s.startswith("data:"):
        # data:image/jpeg;base64,AAAA
        if "," not in s:
            raise HTTPException(status_code=400, detail="Invalid data URL base64")
        s = s.split(",", 1)[1]
    return s


def _detect_ext(image_bytes: bytes) -> str:
    """Detecta PNG/JPEG por magic bytes."""
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if image_bytes.startswith(b"\xff\xd8"):
        return "jpg"
    # si no se reconoce, guardamos como jpg por defecto
    return "jpg"


def _safe_resolve_under(base: Path, target: Path) -> Path:
    """Garantiza que target está dentro de base (anti path traversal)."""
    base_r = base.resolve()
    target_r = target.resolve()
    if base_r not in target_r.parents and base_r != target_r:
        raise HTTPException(status_code=400, detail="Invalid snapshot path")
    return target_r


class EventIn(BaseModel):
    ts: str | None = None
    type: str = "snapshot"
    cameraId: str | None = None
    confidence: float | None = None
    message: str | None = None

    # compatibilidad: si en cliente usas snapshotBase64 o imageBase64, aceptamos ambos
    snapshotBase64: str | None = None
    imageBase64: str | None = None


@app.get("/events")
def get_events(
    limit: int = 50,
    before: str | None = None,
    _token: str = Depends(require_auth)
):
    limit = max(1, min(limit, 200))

    # Si tu db.list_events aún no soporta before, puedes ignorarlo,
    # pero te recomiendo añadirlo (te digo cómo debajo).
    try:
        items = list_events(limit=limit, before=before)  # si lo implementas en db.py
    except TypeError:
        items = list_events(limit=limit)

    # Añadimos URL de snapshot para la app
    for it in items:
        it["snapshotUrl"] = f"/events/{it['id']}/snapshot.jpg"

    return {"items": items}


@app.post("/events")
def post_event(ev: EventIn, _token: str = Depends(require_auth)):
    # ts por defecto = ahora UTC
    ts = ev.ts or datetime.now(timezone.utc).isoformat()

    # elegimos base64 de cualquiera de los campos
    b64_payload = ev.snapshotBase64 or ev.imageBase64

    snapshot_path: str | None = None
    event_id: str | None = None

    if b64_payload:
        raw = _normalize_b64(b64_payload)

        # decode estricto + límite
        try:
            img_bytes = base64.b64decode(raw, validate=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64: {e}")

        if not img_bytes:
            raise HTTPException(status_code=400, detail="Empty image")

        if len(img_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Image too large (max {MAX_IMAGE_BYTES} bytes)"
            )

        # Creamos ID estable para que snapshot y event coincidan
        event_id = "evt_" + secrets.token_urlsafe(8)

        ext = _detect_ext(img_bytes)
        file_path = SNAP_DIR / f"{event_id}.{ext}"
        file_path = _safe_resolve_under(SNAP_DIR, file_path)

        # Guardamos a disco (si falla, no insertamos evento)
        try:
            file_path.write_bytes(img_bytes)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Saving image failed: {e}")

        snapshot_path = str(file_path)

    # Insert event (con event_id si lo hemos creado arriba)
    try:
        new_id = insert_event(
            ts=ts,
            type_=ev.type,
            camera_id=ev.cameraId,
            confidence=ev.confidence,
            message=ev.message,
            snapshot_path=snapshot_path,
            event_id=event_id,
        )
    except Exception as e:
        # Si insert falla y ya guardamos fichero, limpiamos
        if snapshot_path:
            try:
                Path(snapshot_path).unlink(missing_ok=True)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"DB insert failed: {e}")

    return {
        "ok": True,
        "id": new_id,
        "ts": ts,
        "snapshotUrl": f"/events/{new_id}/snapshot.jpg" if snapshot_path else None,
    }


@app.get("/events/{event_id}/snapshot.jpg")
def get_event_snapshot(event_id: str, _token: str = Depends(require_auth)):
    path = get_event_snapshot_path(event_id)
    if not path:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    p = Path(path)
    # Si es relativo, lo hacemos relativo a cwd
    if not p.is_absolute():
        p = Path(os.getcwd()) / p

    # Blindaje: solo servir ficheros dentro de SNAP_DIR
    p = _safe_resolve_under(SNAP_DIR, p)

    if not p.exists():
        raise HTTPException(status_code=404, detail="Snapshot file missing")

    ext = p.suffix.lower()
    media_type = "image/png" if ext == ".png" else "image/jpeg"
    return FileResponse(str(p), media_type=media_type)


@app.delete("/events/{event_id}")
def delete_event_api(event_id: str, _token: str = Depends(require_auth)):
    """
    Borra un evento y su snapshot asociado (si existe).
    """

    # 1) Localiza el snapshot (si existe en DB)
    path = get_event_snapshot_path(event_id)

    # 2) Borra el fichero de snapshot (si existe) con blindaje: solo dentro de SNAP_DIR
    if path:
        p = Path(path)
        if not p.is_absolute():
            p = Path(os.getcwd()) / p

        try:
            snap_dir = SNAP_DIR.resolve()
            pr = p.resolve()

            # ✅ solo borramos si está dentro de la carpeta de snapshots
            if snap_dir in pr.parents and pr.exists():
                pr.unlink()
        except Exception:
            # No abortamos por fallo de IO
            pass

    # 3) Borra el evento de la BD
    ok = delete_event(event_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Event not found")

    return {"ok": True, "id": event_id}