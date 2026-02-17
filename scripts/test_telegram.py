"""
Script de prueba para enviar un mensaje por Telegram usando el módulo de notificaciones.

Uso:
  python scripts/test_telegram.py "Mensaje de prueba"

Requisitos:
  - Tener `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en el entorno o en un archivo `.env` en la raíz del proyecto.
"""

import os
import sys
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.alerts.notifications import send_via_telegram


def main():
    if len(sys.argv) > 1:
        message = " ".join(sys.argv[1:])
    else:
        message = "Mensaje de prueba desde videovigilancia"

    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    if not bot_token or not chat_id:
        print('Error: falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en el entorno.')
        print('Crea un archivo .env con esas variables o expórtalas en tu shell.')
        sys.exit(1)

    print('Enviando mensaje...')
    ok = send_via_telegram(message, chat_id=chat_id, bot_token=bot_token)
    if ok:
        print('Mensaje enviado correctamente')
        sys.exit(0)
    else:
        print('Error al enviar el mensaje')
        sys.exit(2)


if __name__ == '__main__':
    main()
