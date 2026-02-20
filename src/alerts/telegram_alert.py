import logging
import os
import threading
from typing import List, Optional, Tuple
from datetime import datetime

import requests


class TelegramAlert:
    """Envía alertas por Telegram usando Bot API HTTP a múltiples destinos."""

    def __init__(self, bot_token: str, user_chat_ids: List[str], group_chat_ids: List[str]):
        self.logger = logging.getLogger(__name__)
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

        self.user_chat_ids = [str(c).strip() for c in user_chat_ids if str(c).strip()]
        self.group_chat_ids = [str(c).strip() for c in group_chat_ids if str(c).strip()]
        self.destinations = self._unique(self.user_chat_ids + self.group_chat_ids)

        self.logger.info("TelegramAlert inicializado: %d destinos", len(self.destinations))

    @staticmethod
    def _unique(items: List[str]) -> List[str]:
        seen = set()
        out = []
        for x in items:
            if x not in seen:
                out.append(x)
                seen.add(x)
        return out

    @staticmethod
    def parse_ids(raw: str) -> List[str]:
        if not raw:
            return []
        parts = [p.strip() for p in raw.split(",")]
        return [p for p in parts if p]

    @classmethod
    def from_env(cls) -> Optional["TelegramAlert"]:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            return None

        user_ids = cls.parse_ids(os.getenv("TELEGRAM_USER_CHAT_IDS", "").strip())
        group_ids = cls.parse_ids(os.getenv("TELEGRAM_GROUP_CHAT_IDS", "").strip())

        legacy_single = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        legacy_multi = os.getenv("TELEGRAM_CHAT_IDS", "").strip()

        if legacy_single and legacy_single not in user_ids and legacy_single not in group_ids:
            user_ids.append(legacy_single)

        for x in cls.parse_ids(legacy_multi):
            if x not in user_ids and x not in group_ids:
                user_ids.append(x)

        if not (user_ids or group_ids):
            return None

        return cls(token, user_ids, group_ids)

    # ------------------------------------------------------------------
    # ENVÍO BÁSICO
    # ------------------------------------------------------------------

    def send_message(self, chat_id: str, text: str) -> bool:
        try:
            url = f"{self.base_url}/sendMessage"
            r = requests.post(
                url,
                data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=20,
            )
            if r.status_code == 200:
                return True
            self.logger.error("Telegram sendMessage %s: %s", r.status_code, r.text)
            return False
        except Exception as e:
            self.logger.error("Telegram sendMessage error: %s", e)
            return False

    def send_photo(self, chat_id: str, caption: str, photo_path: str) -> bool:
        try:
            url = f"{self.base_url}/sendPhoto"
            with open(photo_path, "rb") as f:
                r = requests.post(
                    url,
                    data={
                        "chat_id": chat_id,
                        "caption": caption,
                        "parse_mode": "Markdown",
                    },
                    files={"photo": f},
                    timeout=20,
                )
            if r.status_code == 200:
                return True
            self.logger.error("Telegram sendPhoto %s: %s", r.status_code, r.text)
            return False
        except Exception as e:
            self.logger.error("Telegram sendPhoto error: %s", e)
            return False

    # ------------------------------------------------------------------
    # 🚨 ALERTA DE PERSONA (NUEVO)
    # ------------------------------------------------------------------

    def send_person_alert(
        self,
        camera_name: str,
        photo_path: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> Tuple[int, int]:
        """
        Envía una alerta indicando QUÉ CÁMARA detectó la persona y CUÁNDO.
        """
        if timestamp is None:
            timestamp = datetime.now()

        message = (
            "🚨 *ALERTA DE PERSONA*\n"
            f"📷 Cámara: *{camera_name}*\n"
            f"🕒 {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        total = len(self.destinations)
        ok = 0

        for chat_id in self.destinations:
            if photo_path:
                ok += 1 if self.send_photo(chat_id, message, photo_path) else 0
            else:
                ok += 1 if self.send_message(chat_id, message) else 0

        return ok, total

    def send_person_alert_async(
        self,
        camera_name: str,
        photo_path: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ):
        t = threading.Thread(
            target=self.send_person_alert,
            args=(camera_name, photo_path, timestamp),
            daemon=True,
        )
        t.start()

    # ------------------------------------------------------------------

    def send_alert(self, message: str, photo_path: Optional[str] = None) -> Tuple[int, int]:
        total = len(self.destinations)
        ok = 0
        for chat_id in self.destinations:
            if photo_path:
                ok += 1 if self.send_photo(chat_id, message, photo_path) else 0
            else:
                ok += 1 if self.send_message(chat_id, message) else 0
        return ok, total

    def send_alert_async(self, message: str, photo_path: Optional[str] = None):
        t = threading.Thread(target=self.send_alert, args=(message, photo_path), daemon=True)
        t.start()

    def get_updates(self, timeout: int = 5, limit: int = 100, offset: Optional[int] = None):
        params = {"timeout": timeout, "limit": limit}
        if offset is not None:
            params["offset"] = offset
        url = f"{self.base_url}/getUpdates"
        r = requests.get(url, params=params, timeout=timeout + 5)
        r.raise_for_status()
        return r.json()