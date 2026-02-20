# Videovigilancia (UI Multicámara)

**UI de videovigilancia en Python** con:
- ✅ Multicámara (mosaico adaptable)  
- ✅ Fuentes: **Webcam**, **Android (IP Webcam MJPEG)**, **iPad (RTSP)**  
- ✅ **Scroll** y **Zoom** en la previsualización  
- ✅ **Detección** (personas/vehículos) con YOLO (ultralytics)  
- ✅ **Alertas Telegram** multi‑destinatario (usuarios + grupos), configurable desde la UI  
- ✅ Guardado de configuración en `.env` y persistencia de cámaras  
- ✅ Reconexión automática de cámaras (backoff) ante cortes

---

## Índice
- Requisitos
- Instalación
- Variables de entorno (.env)
- Ejecución
- Uso de la UI
- [Cámaras soportadas](#cámaras-soportadas Telegram
- Reconexión de cámaras
- Solución de problemas
- Estructura del proyecto
- Contribuir
- Licencia

---

## Requisitos

- **Python 3.10+** (probado en 3.12)
- macOS/Windows/Linux
- Paquetes en `requirements.txt` (ejemplo):
  ```txt
  opencv-python
  pillow
  python-dotenv
  numpy
  # Si usas ultralytics para YOLO:
  ultralytics
  requests
