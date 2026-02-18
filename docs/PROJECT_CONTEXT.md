# Videovigilancia – Contexto del proyecto

## Objetivo
App de videovigilancia en Python + OpenCV:
- Captura vídeo (webcam local, Android MJPEG, iPad/iPhone RTSP)
- Detección de personas
- Mosaico multi-cámara
- Alertas Telegram (mensaje + foto) indicando qué cámara detectó

## Estructura
- src/main.py: ejecución single-cam con --source
- src/main_multicam.py: mosaico multi-cámara usando config desde .env
- src/camera/camera_manager.py: captura (índice o URL). Para URLs usar FFmpeg.
- src/alerts/telegram_alert.py: envío Telegram (mensaje + foto)
- src/config.py: carga .env y configura CAMERA_CONFIG, TELEGRAM_CONFIG, etc.

## Configuración (.env)
- TELEGRAM_BOT_TOKEN=...
- TELEGRAM_CHAT_ID=...
- MULTICAM_CONFIG=Mac=0,Android=http://192.168.1.108:8080/video,iPad=rtsp://192.168.1.141:8554/stream

## Ejecución
Single cam:
- python3 src/main.py --source 0
- python3 src/main.py --source "http://192.168.1.108:8080/video"

Multi cam mosaico:
- python3 src/main_multicam.py --configured --drop-frames 12

Notas:
- Android (IP Webcam MJPEG): usar --drop-frames para reducir latencia
- iPad (OctoStream RTSP Server): RTSP funciona con ffmpeg en OpenCV

## Estado actual
- Telegram OK (mensaje + foto)
- Mosaico auto OK
- Nombres por cámara en mosaico OK
- Offline por defecto muestra "SIN SEÑAL"