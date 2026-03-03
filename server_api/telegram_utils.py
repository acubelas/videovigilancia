import os
import requests
from fastapi import HTTPException

def telegram_send_message(chat_id: int, text: str) -> None:
    """
    Envía un mensaje usando Telegram Bot API (sendMessage).
    POST a: https://api.telegram.org/bot<TOKEN>/sendMessage con chat_id y text.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN not configured")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(
        url,
        data={"chat_id": str(chat_id), "text": text},
        timeout=10,
    )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Telegram sendMessage failed: {resp.status_code} {resp.text}",
        )
