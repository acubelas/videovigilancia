"""
GUÍA DE ARQUITECTURA - Aplicación de Videovigilancia

Este documento explica la arquitectura y el flujo de la aplicación.

# DIAGRAMA DE FLUJO DE DATOS

┌─────────────┐
│  Cámara Web │
└──────┬──────┘
       │
       ▼
┌──────────────────────┐
│  CameraManager       │
│  - Captura frames    │
│  - Configuración     │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────────┐
│  MotionDetector          │
│  - Análisis de frames    │
│  - Cálculo de confianza  │
│  - Contornos detectados  │
└──────┬───────────────────┘
       │
       ▼ (Si movimiento detectado)
┌──────────────────────────┐
│  AlertSystem             │
├──────────────────────────┤
│  ├─ TelegramAlert        │
│  └─ TwilioAlert          │
└──────┬───────────────────┘
       │
       ▼
┌──────────────────────────┐
│  Usuarios/Móvil          │
│  (Telegram/SMS)          │
└──────────────────────────┘


# FLUJO DE EJECUCIÓN

1. INICIALIZACIÓN (main.py)
   ├─ Crear instancia VideoSurveillanceApp
   ├─ Inicializar CameraManager
   │  └─ Abrir conexión con cámara web
   ├─ Inicializar MotionDetector
   ├─ Inicializar TelegramAlert (si está habilitado)
   ├─ Inicializar TwilioAlert (si está habilitado)
   └─ Inicializar logger

2. BUCLE PRINCIPAL (run())
   Repetir indefinidamente:
   ├─ Capturar frame de cámara (30 FPS)
   ├─ Procesar frame:
   │  └─ Detector de movimiento:
   │     ├─ Convertir a escala de grises
   │     ├─ Aplicar desenfoque gaussiano
   │     ├─ Comparar con frame anterior
   │     ├─ Calcular diferencia (%)
   │     ├─ Encontrar contornos
   │     └─ Determinar si hay movimiento significativo
   ├─ Si movimiento detectado:
   │  ├─ Acumular contador
   │  ├─ Si contador >= 3:
   │     ├─ Crear mensaje de alerta
   │     ├─ Guardar captura (opcional)
   │     ├─ Enviar por Telegram
   │     ├─ Enviar por SMS (Twilio)
   │     └─ Activar cooldown (no repetir alertas)
   ├─ Grabar video (si habilitado)
   ├─ Mostrar frame con anotaciones
   └─ Si usuario presiona 'Q' → salir

3. LIMPIEZA (cleanup())
   ├─ Liberar cámara
   ├─ Cerrar grabación de video
   ├─ Cerrar ventanas de OpenCV
   └─ Guardar logs


# ESTRUCTURA DE CLASES

VideoSurveillanceApp (main.py)
├─ Atributos:
│  ├─ camera: CameraManager
│  ├─ motion_detector: MotionDetector
│  ├─ telegram_alert: TelegramAlert
│  ├─ twilio_alert: TwilioAlert
│  ├─ last_alert_time: float
│  └─ motion_detected_frames: int
│
└─ Métodos:
   ├─ __init__(): Inicialización
   ├─ _initialize_components(): Crear objetos
   ├─ _initialize_video_writer(): Iniciar grabación
   ├─ _send_alert(): Enviar alertas
   ├─ run(): Bucle principal
   └─ cleanup(): Liberar recursos


CameraManager (camera/camera_manager.py)
├─ Atributos:
│  ├─ camera_index: int
│  ├─ frame_width: int
│  ├─ frame_height: int
│  ├─ fps: int
│  └─ cap: cv2.VideoCapture
│
└─ Métodos:
   ├─ init_camera(): Abrir cámara
   ├─ get_frame(): Obtener siguiente frame
   ├─ release(): Cerrar cámara
   └─ __enter__/__exit__: Context manager


MotionDetector (motion/motion_detector.py)
├─ Atributos:
│  ├─ threshold: float
│  ├─ blur_kernel_size: int
│  ├─ min_contour_area: float
│  └─ previous_frame: ndarray
│
└─ Métodos:
   ├─ detect_motion(frame): Detectar movimiento
   └─ set_threshold(threshold): Cambiar umbral


TelegramAlert (alerts/telegram_alert.py)
├─ Atributos:
│  ├─ bot_token: str
│  ├─ chat_id: str
│  └─ bot: telegram.Bot
│
└─ Métodos:
   ├─ send_alert(message, photo_path): Enviar alerta
   └─ send_alert_async(): Envío no-bloqueante


TwilioAlert (alerts/twilio_alert.py)
├─ Atributos:
│  ├─ account_sid: str
│  ├─ auth_token: str
│  ├─ from_number: str
│  ├─ to_number: str
│  └─ client: twilio.rest.Client
│
└─ Métodos:
   ├─ send_alert(message): Enviar SMS
   └─ send_alert_async(): Envío no-bloqueante


# ALGORITMO DE DETECCIÓN DE MOVIMIENTO

Entrada: Fotograma actual (frame)
Salida: (movimiento_detectado, confianza, frame_anotado)

1. Convertir frame a escala de grises
2. Aplicar desenfoque gaussiano
3. Si 1er frame:
   - Guardar como referencia
   - Retornar (False, 0%, frame)
4. Calcular diferencia absoluta con frame anterior
5. Aplicar umbral binario (30)
6. Aplicar operaciones morfológicas:
   - Cierre (closing) para conectar regiones
   - Apertura (opening) para eliminar ruido
7. Encontrar contornos
8. Para cada contorno:
   - Si área > min_contour_area:
     - Dibujar rectángulo
     - Marcar como movimiento
9. Calcular porcentaje de píxeles cambiados
10. Actualizar frame anterior
11. Retornar (movimiento, confianza, frame_anotado)


# CONFIGURACIÓN RECOMENDADA

┌─────────────────────────────────────────────────┐
│ Detección Sensible (Mayor número de alertas)    │
├─────────────────────────────────────────────────┤
│ MOTION_THRESHOLD=3.0                            │
│ MIN_CONTOUR_AREA=300.0                          │
│ CONFIDENCE_THRESHOLD=1.0                        │
│ ALERT_COOLDOWN=15                              │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│ Detección Equilibrada (Recomendado)             │
├─────────────────────────────────────────────────┤
│ MOTION_THRESHOLD=5.0                            │
│ MIN_CONTOUR_AREA=500.0                          │
│ CONFIDENCE_THRESHOLD=2.0                        │
│ ALERT_COOLDOWN=30                              │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│ Detección Estricta (Menos alertas falsas)       │
├─────────────────────────────────────────────────┤
│ MOTION_THRESHOLD=8.0                            │
│ MIN_CONTOUR_AREA=1000.0                         │
│ CONFIDENCE_THRESHOLD=3.0                        │
│ ALERT_COOLDOWN=60                              │
└─────────────────────────────────────────────────┘


# RENDIMIENTO Y OPTIMIZACIÓN

Requisitos mínimos:
- CPU: Intel i5 o equivalente
- RAM: 4 GB
- Cámara: USB 2.0 o superior
- Conexión: Con internet (para alertas)

Optimizaciones incluidas:
- Procesamiento en escala de grises (reducción de datos)
- Desenfoque gaussiano (reducción de ruido)
- Alert cooldown (evitar saturación de mensajes)
- Threading para alertas no-bloqueantes
- Rotación automática de logs

Mejoras posibles:
- Procesar a menor resolución internamente
- Usar procesamiento CUDA si tiene GPU NVIDIA
- Implementar caché de frames
- Paralelizar procesamiento de múltiples cámaras


# MANEJO DE ERRORES

┌────────────────────────────────────────────────┐
│ Punto de Fallo          │ Manejo               │
├────────────────────────────────────────────────┤
│ Cámara no disponible    │ Exit con error       │
│ Telegram no responde    │ Log error, continúa  │
│ Twilio no responde      │ Log error, continúa  │
│ Frame corrupto          │ Skip frame           │
│ Memoria insuficiente    │ Reducir resolución   │
└────────────────────────────────────────────────┘


# LOG DE EVENTOS TÍPICOS

[INFO] Aplicación iniciada
[INFO] Cámara inicializada: 640x480 @ 30 FPS
[INFO] Motor de detección de movimiento cargado
[INFO] Alertas por Telegram habilitadas
[WARNING] ALERTA: Movimiento detectado - 5.23%
[INFO] Alerta enviada por Telegram
[INFO] Cámara liberada
[INFO] Aplicación finalizada
"""

# REFERENCIAS Y RECURSOS

## OpenCV (Procesamiento de Video)
# - Documentación: https://docs.opencv.org/
# - Motion detection: Diferencia de frames
# - Contour detection: Encontrar objetos

## Telegram API
# - BotFather: @BotFather en Telegram
# - python-telegram-bot: https://pypi.org/project/python-telegram-bot/

## Twilio SMS
# - Sitio web: https://www.twilio.com/
# - Documentación: https://www.twilio.com/docs/

## Python Async
# - Threading: Para operaciones no-bloqueantes
# - Context managers: Para manejo de recursos
