"""
Utilidades de logging
"""

import logging
import logging.handlers
import os
import sys
import io
from pathlib import Path


def setup_logger(name: str = __name__, log_level: int = logging.INFO, 
                 log_file: str = "logs/app.log") -> logging.Logger:
    """
    Configura un logger con salida a consola y archivo.
    
    Args:
        name: Nombre del logger
        log_level: Nivel de logging
        log_file: Ruta del archivo de log
        
    Returns:
        Logger configurado
    """
    # Crear directorio de logs si no existe
    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Crear logger
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    
    # Evitar duplicar handlers
    if logger.hasHandlers():
        return logger
    
    # Formato de log
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Handler para archivo con rotación
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Handler para consola: forzamos UTF-8 cuando la consola no lo soporta
    stream = sys.stdout
    try:
        stdout_enc = (sys.stdout.encoding or '').lower()
        if 'utf' not in stdout_enc and getattr(sys.stdout, 'buffer', None) is not None:
            stream = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except Exception:
        stream = sys.stdout

    console_handler = logging.StreamHandler(stream)
    console_handler.setLevel(log_level)
    
    # Usar colores en consola
    try:
        import colorlog
        console_formatter = colorlog.ColoredFormatter(
            '%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            }
        )
        console_handler.setFormatter(console_formatter)
    except ImportError:
        console_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    
    return logger
