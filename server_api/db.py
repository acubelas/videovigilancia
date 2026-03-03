import os
import sqlite3
from datetime import datetime, timezone
import secrets

SQLITE_PATH = os.getenv("SQLITE_PATH", "data/vigi.db")

def _conn():
    os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
    return sqlite3.connect(SQLITE_PATH)

def init_db():
    with _conn() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS telegram_links (
            phone_e164 TEXT PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            telegram_user_id INTEGER NOT NULL,
            username TEXT,
            linked_at TEXT NOT NULL
        )
        """)
        con.commit()

        con.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                ts TEXT NOT NULL,                 -- ISO timestamp (UTC recomendado)
                type TEXT NOT NULL,               -- ej: person_detected
                camera_id TEXT,                   -- ej: cam1
                confidence REAL,                  -- ej: 0.87
                message TEXT,                     -- texto libre
                snapshot_path TEXT,               -- ruta local opcional
                created_at TEXT NOT NULL          -- ISO timestamp
            )
            """)
        con.commit()

def upsert_link(phone_e164: str, chat_id: int, telegram_user_id: int, username: str | None):
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute("""
        INSERT INTO telegram_links(phone_e164, chat_id, telegram_user_id, username, linked_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(phone_e164) DO UPDATE SET
            chat_id=excluded.chat_id,
            telegram_user_id=excluded.telegram_user_id,
            username=excluded.username,
            linked_at=excluded.linked_at
        """, (phone_e164, chat_id, telegram_user_id, username, now))
        con.commit()

def get_chat_id_by_phone(phone_e164: str) -> int | None:
    with _conn() as con:
        cur = con.execute("SELECT chat_id FROM telegram_links WHERE phone_e164=?", (phone_e164,))
        row = cur.fetchone()
        return int(row[0]) if row else None



def insert_event(
    ts: str,
    type_: str,
    camera_id: str | None = None,
    confidence: float | None = None,
    message: str | None = None,
    snapshot_path: str | None = None,
    event_id: str | None = None,
) -> str:
    """
    Inserta evento y devuelve su id.
    """
    if not event_id:
        event_id = "evt_" + secrets.token_urlsafe(8)

    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute("""
        INSERT INTO events(id, ts, type, camera_id, confidence, message, snapshot_path, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (event_id, ts, type_, camera_id, confidence, message, snapshot_path, now))
        con.commit()
    return event_id

def list_events(limit: int = 50) -> list[dict]:
    with _conn() as con:
        cur = con.execute("""
        SELECT id, ts, type, camera_id, confidence, message, snapshot_path
        FROM events
        ORDER BY ts DESC
        LIMIT ?
        """, (limit,))
        rows = cur.fetchall()

    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "ts": r[1],
            "type": r[2],
            "cameraId": r[3],
            "confidence": r[4],
            "message": r[5],
            "snapshotPath": r[6],
        })
    return out       
