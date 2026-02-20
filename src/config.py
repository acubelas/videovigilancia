# -*- coding: utf-8 -*-
"""
Configuración de la aplicación de videovigilancia
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# -------------------------------------------------------------
# Directorios base y carga de .env
# -------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent  # ✅ raíz del proyecto (../ desde src/)
SRC_DIR = BASE_DIR / "src"
LOGS_DIR = BASE_DIR / "logs"

# Carga garantizada del .env ubicado en la raíz del proyecto
load_dotenv(dotenv_path=BASE_DIR / ".env")

# -------------------------------------------------------------
# Helpers
# -------------------------------------------------------------
def _split_ids(env_value: str):
    """
    Convierte 'a,b,c' -> ['a','b','c'] eliminando espacios y valores vacíos.
    Devuelve [] si no hay nada.
    """
    if not env_value:
        return []
    return [x.strip() for x in env_value.split(",") if x.strip()]

# -------------------------------------------------------------
# Configuración de la cámara
# -------------------------------------------------------------
CAMERA_CONFIG = {
    "camera_index": int(os.getenv("CAMERA_INDEX", 0)),
    "frame_width": int(os.getenv("FRAME_WIDTH", 640)),
    "frame_height": int(os.getenv("FRAME_HEIGHT", 480)),
    "fps": int(os.getenv("FPS", 30)),
}

# -------------------------------------------------------------
# Configuración de detección de movimiento
# -------------------------------------------------------------
MOTION_CONFIG = {
    "threshold": float(os.getenv("MOTION_THRESHOLD", 5.0)),
    "blur_kernel_size": int(os.getenv("BLUR_KERNEL_SIZE", 21)),
    "min_contour_area": float(os.getenv("MIN_CONTOUR_AREA", 500.0)),
    "confidence_threshold": float(os.getenv("CONFIDENCE_THRESHOLD", 2.0)),
    "alert_cooldown_seconds": int(os.getenv("ALERT_COOLDOWN", 30)),
}

# -------------------------------------------------------------
# Configuración de Telegram (multi‑destinatario)
# -------------------------------------------------------------
TELEGRAM_CONFIG = {
    # Habilitado por defecto (envío gratuito)
    "enabled": os.getenv("TELEGRAM_ENABLED", "True").lower() == "true",

    # Bot principal
    "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),

    # (Compat opcional) Un único chat_id heredado (no recomendado ya)
    "chat_id": os.getenv("TELEGRAM_CHAT_ID", "").strip(),

    # Nuevo: listas de usuarios y grupos
    #   - Usuarios: IDs positivos (DM con personas)
    #   - Grupos:  IDs negativos (p. ej., -100xxxxxxxxxx)
    "user_chat_ids": _split_ids(os.getenv("TELEGRAM_USER_CHAT_IDS", "")),
    "group_chat_ids": _split_ids(os.getenv("TELEGRAM_GROUP_CHAT_IDS", "")),

    # (Opcional futuro) Segundo bot si quieres separar administración/alertas
    "bot2_token": os.getenv("TELEGRAM_BOT2_TOKEN", "").strip(),
}

# Atajos (si prefieres importarlos directamente)
TELEGRAM_ENABLED = TELEGRAM_CONFIG["enabled"]
TELEGRAM_BOT_TOKEN = TELEGRAM_CONFIG["bot_token"]
TELEGRAM_BOT2_TOKEN = TELEGRAM_CONFIG["bot2_token"]
TELEGRAM_USER_CHAT_IDS = TELEGRAM_CONFIG["user_chat_ids"]
TELEGRAM_GROUP_CHAT_IDS = TELEGRAM_CONFIG["group_chat_ids"]
TELEGRAM_CHAT_ID = TELEGRAM_CONFIG["chat_id"]  # compat opcional

def get_all_destination_ids():
    """
    Devuelve una lista unificada (sin duplicados) de destinos Telegram como cadenas:
    - Primero el chat único de compatibilidad si existe (TELEGRAM_CHAT_ID)
    - Luego los usuarios (TELEGRAM_USER_CHAT_IDS)
    - Luego los grupos (TELEGRAM_GROUP_CHAT_IDS)
    El orden de aparición se preserva y se eliminan duplicados.
    """
    combined = []
    if TELEGRAM_CHAT_ID:
        combined.append(str(TELEGRAM_CHAT_ID))
    combined.extend(str(x) for x in TELEGRAM_USER_CHAT_IDS)
    combined.extend(str(x) for x in TELEGRAM_GROUP_CHAT_IDS)

    seen = set()
    unique = []
    for cid in combined:
        if cid not in seen:
            unique.append(cid)
            seen.add(cid)
    return unique

# -------------------------------------------------------------
# Configuración de Twilio (deshabilitado por defecto para evitar costes)
# -------------------------------------------------------------
TWILIO_CONFIG = {
    "enabled": os.getenv("TWILIO_ENABLED", "False").lower() == "true",
    "account_sid": os.getenv("TWILIO_ACCOUNT_SID", ""),
    "auth_token": os.getenv("TWILIO_AUTH_TOKEN", ""),
    "from_number": os.getenv("TWILIO_FROM_NUMBER", ""),
    "to_number": os.getenv("TWILIO_TO_NUMBER", ""),
}

# -------------------------------------------------------------
# Configuración de logging
# -------------------------------------------------------------
LOGGING_CONFIG = {
    "level": os.getenv("LOG_LEVEL", "INFO"),
    "log_file": str(LOGS_DIR / "app.log"),
    "max_log_size_mb": int(os.getenv("MAX_LOG_SIZE_MB", 10)),
    "backup_count": int(os.getenv("LOG_BACKUP_COUNT", 5)),
}

# -------------------------------------------------------------
# Configuración de grabación de video
# -------------------------------------------------------------
RECORDING_CONFIG = {
    "enabled": os.getenv("RECORDING_ENABLED", "False").lower() == "true",
    "output_dir": os.getenv("RECORDING_DIR", str(BASE_DIR / "recordings")),
    "fps": int(os.getenv("RECORDING_FPS", 20)),
    "codec": os.getenv("RECORDING_CODEC", "mp4v"),
}

# -------------------------------------------------------------
# Crear directorios necesarios
# -------------------------------------------------------------
LOGS_DIR.mkdir(exist_ok=True)
Path(RECORDING_CONFIG["output_dir"]).mkdir(exist_ok=True)