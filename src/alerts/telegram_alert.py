import logging
from typing import Optional
import requests

class TelegramAlert:
    """Envía alertas por Telegram usando API HTTP (texto + foto)."""

    def __init__(self, bot_token: str, chat_id: str):
        self.logger = logging.getLogger(__name__)
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.logger.info("TelegramAlert (HTTP) inicializado")

    def send_alert(self, message: str, photo_path: Optional[str] = None) -> bool:
        try:
            if photo_path:
                url = f"{self.base_url}/sendPhoto"
                with open(photo_path, "rb") as f:
                    r = requests.post(
                        url,
                        data={"chat_id": self.chat_id, "caption": message},
                        files={"photo": f},
                        timeout=20
                    )
            else:
                url = f"{self.base_url}/sendMessage"
                r = requests.post(
                    url,
                    data={"chat_id": self.chat_id, "text": message},
                    timeout=20
                )

            if r.status_code == 200:
                self.logger.info("Alerta Telegram enviada correctamente")
                return True

            self.logger.error(f"Telegram HTTP {r.status_code}: {r.text}")
            return False

        except Exception as e:
            self.logger.error(f"Error enviando Telegram: {e}")
            return False

    def send_alert_async(self, message: str, photo_path: Optional[str] = None):
        import threading
        t = threading.Thread(target=self.send_alert, args=(message, photo_path), daemon=True)
        t.start()