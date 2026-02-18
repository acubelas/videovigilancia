# Videovigilancia (Python + OpenCV) — Mosaico multicámara + detección + alertas Telegram

Proyecto de videovigilancia en Python que permite:
- Captura de vídeo desde **webcam local**, **Android MJPEG (IP Webcam)** y **RTSP (iPad/iPhone)**.
- Visualización en **mosaico** (grid automático) con nombre por cámara.
- **Detección de personas** (PersonDetector).
- **Alertas por Telegram** (mensaje + foto) indicando **qué cámara detectó**.
- Modo de baja latencia para streams (ej. Android MJPEG) mediante `--drop-frames`.

> ⚠️ Privacidad/Legal: usa este proyecto de forma responsable, con consentimiento y respetando normativa local.

---

## 📁 Estructura del proyecto

- `src/main.py`  
  Ejecución **single-cam** (una fuente: webcam o URL) mediante `--source`.
- `src/main_multicam.py`  
  Ejecución **multicámara** con **mosaico** y cámaras **configuradas** en `.env` vía `MULTICAM_CONFIG`.
- `src/camera/camera_manager.py`  
  Gestión de captura (índice o URL). Para URLs se recomienda usar FFmpeg cuando aplique.
- `src/alerts/telegram_alert.py`  
  Envío Telegram (mensaje + foto).
- `src/config.py`  
  Carga `.env` y define `CAMERA_CONFIG`, `TELEGRAM_CONFIG`, etc.
- `tests/`  
  Pruebas rápidas (p.ej. MJPEG/FFmpeg).

---

## ✅ Requisitos

- macOS (probado en Mac) con **Python 3.12+**
- `pip`, `venv`
- Dependencias Python (ver instalación más abajo)
- Para cámaras móviles:
  - Android: app tipo **IP Webcam** (MJPEG)
  - iPad/iPhone: app tipo **OctoStream RTSP Server** (RTSP)

---

## 🚀 Instalación

### 1) Crear y activar entorno virtual
Desde la raíz del proyecto:

```bash
python3 -m venv .venv
source .venv/bin/activate