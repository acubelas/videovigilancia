import os
import sqlite3
from datetime import datetime, timezone

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
