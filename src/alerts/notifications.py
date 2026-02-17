"""
Módulo de notificaciones.

Proporciona funciones para enviar mensajes usando Twilio (SMS/WhatsApp)
o Telegram (bot). Las claves y credenciales se leen desde variables de
entorno pero también incluyen marcadores de posición donde aplicable.
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def send_via_telegram(message: str, chat_id: Optional[str] = None, bot_token: Optional[str] = None) -> bool:
    """
    Envía un mensaje utilizando el Bot de Telegram mediante HTTP API.

    Args:
        message: Texto del mensaje a enviar.
        chat_id: ID del chat destino (si None, se lee de TELEGRAM_CHAT_ID).
        bot_token: Token del bot (si None, se lee de TELEGRAM_BOT_TOKEN).

    Returns:
        True si la API de Telegram devuelve OK, False en caso contrario.

    NOTA: Requiere `requests` instalado o usa la librería estándar si se quiere.
    """
    import requests

    bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID', '')

    if not bot_token or not chat_id:
        logger.error('Telegram no está configurado: falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID')
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': int(chat_id),  # Convertir a int
        'text': message,
        'parse_mode': 'Markdown'
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)  # Usar json en lugar de data
        resp.raise_for_status()
        data = resp.json()
        if data.get('ok'):
            logger.info('Telegram: mensaje enviado correctamente')
            return True
        else:
            logger.error(f"Telegram API error: {data}")
            return False
    except Exception as e:
        logger.error(f"Error al enviar mensaje por Telegram: {e}")
        return False


__all__ = [
    'send_via_telegram',
]
