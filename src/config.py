"""
Configuración de la aplicación de videovigilancia
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()


from pathlib import Path
from dotenv import load_dotenv
import os




# Directorios
BASE_DIR = Path(__file__).resolve().parent.parent  # ✅ raíz del proyecto
load_dotenv(dotenv_path=BASE_DIR / ".env")         # ✅ carga garantizada del .env

SRC_DIR = BASE_DIR / "src"
LOGS_DIR = BASE_DIR / "logs"

# Configuración de la cámara
CAMERA_CONFIG = {
    'camera_index': int(os.getenv('CAMERA_INDEX', 0)),
    'frame_width': int(os.getenv('FRAME_WIDTH', 640)),
    'frame_height': int(os.getenv('FRAME_HEIGHT', 480)),
    'fps': int(os.getenv('FPS', 30)),
}

# Configuración de detección de movimiento
MOTION_CONFIG = {
    'threshold': float(os.getenv('MOTION_THRESHOLD', 5.0)),
    'blur_kernel_size': int(os.getenv('BLUR_KERNEL_SIZE', 21)),
    'min_contour_area': float(os.getenv('MIN_CONTOUR_AREA', 500.0)),
    'confidence_threshold': float(os.getenv('CONFIDENCE_THRESHOLD', 2.0)),
    'alert_cooldown_seconds': int(os.getenv('ALERT_COOLDOWN', 30)),
}

# Configuración de Telegram (habilitado por defecto para envío gratuito)
TELEGRAM_CONFIG = {
    'enabled': os.getenv('TELEGRAM_ENABLED', 'True').lower() == 'true',
    'bot_token': os.getenv('TELEGRAM_BOT_TOKEN', '').strip(),
    'chat_id': os.getenv('TELEGRAM_CHAT_ID', '').strip(),
}

# Configuración de Twilio (deshabilitado por defecto para evitar costes SMS)
TWILIO_CONFIG = {
    'enabled': os.getenv('TWILIO_ENABLED', 'False').lower() == 'true',
    'account_sid': os.getenv('TWILIO_ACCOUNT_SID', ''),
    'auth_token': os.getenv('TWILIO_AUTH_TOKEN', ''),
    'from_number': os.getenv('TWILIO_FROM_NUMBER', ''),
    'to_number': os.getenv('TWILIO_TO_NUMBER', ''),
}

# Configuración de logging
LOGGING_CONFIG = {
    'level': os.getenv('LOG_LEVEL', 'INFO'),
    'log_file': str(LOGS_DIR / 'app.log'),
    'max_log_size_mb': int(os.getenv('MAX_LOG_SIZE_MB', 10)),
    'backup_count': int(os.getenv('LOG_BACKUP_COUNT', 5)),
}

# Configuración de grabación de video
RECORDING_CONFIG = {
    'enabled': os.getenv('RECORDING_ENABLED', 'False').lower() == 'true',
    'output_dir': os.getenv('RECORDING_DIR', str(BASE_DIR / 'recordings')),
    'fps': int(os.getenv('RECORDING_FPS', 20)),
    'codec': os.getenv('RECORDING_CODEC', 'mp4v'),
}

# Crear directorios necesarios
LOGS_DIR.mkdir(exist_ok=True)
Path(RECORDING_CONFIG['output_dir']).mkdir(exist_ok=True)
