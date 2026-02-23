# src/server/storage.py
import sqlite3
import secrets
import time
from pathlib import Path
from typing import Optional, Tuple

DB_PATH = Path("data/server.db")


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with _connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS pairing_codes (
                code TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                claimed_at INTEGER,
                claimed_device_id TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                device_name TEXT,
                platform TEXT
            )
            """
        )
        con.commit()


def new_pair_code(ttl_seconds: int = 300) -> Tuple[str, int]:
    """Devuelve (code, expires_at_epoch). Code = 6 dígitos."""
    now = int(time.time())
    expires_at = now + ttl_seconds

    # 6 dígitos
    code = f"{secrets.randbelow(1_000_000):06d}"

    with _connect() as con:
        # Si colisiona (muy raro), reintenta
        for _ in range(5):
            try:
                con.execute(
                    "INSERT INTO pairing_codes(code, created_at, expires_at) VALUES(?,?,?)",
                    (code, now, expires_at),
                )
                con.commit()
                return code, expires_at
            except sqlite3.IntegrityError:
                code = f"{secrets.randbelow(1_000_000):06d}"

    raise RuntimeError("No se pudo generar pair_code (colisiones repetidas)")


def claim_pair_code(code: str, device_name: str = "", platform: str = "") -> Optional[str]:
    """
    Si el code existe, no ha expirado y no está reclamado:
      - crea/actualiza el dispositivo
      - marca el code como claimed
      - devuelve device_id
    Si no, devuelve None.
    """
    now = int(time.time())
    device_id = secrets.token_urlsafe(16)

    with _connect() as con:
        row = con.execute(
            "SELECT code, expires_at, claimed_at FROM pairing_codes WHERE code = ?",
            (code,),
        ).fetchone()

        if not row:
            return None

        if row["claimed_at"] is not None:
            return None

        if now > int(row["expires_at"]):
            return None

        # registrar device
        con.execute(
            "INSERT INTO devices(device_id, created_at, last_seen_at, device_name, platform) VALUES(?,?,?,?,?)",
            (device_id, now, now, device_name or None, platform or None),
        )

        # marcar claimed
        con.execute(
            "UPDATE pairing_codes SET claimed_at = ?, claimed_device_id = ? WHERE code = ?",
            (now, device_id, code),
        )

        con.commit()
        return device_id


def touch_device(device_id: str):
    now = int(time.time())
    with _connect() as con:
        con.execute("UPDATE devices SET last_seen_at=? WHERE device_id=?", (now, device_id))
        con.commit()