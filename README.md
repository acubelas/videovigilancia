# 🎥 Aplicación de Videovigilancia con Detección de Movimiento

Una aplicación Python profesional para capturar video en tiempo real, detectar movimiento y enviar alertas a través de Telegram o SMS (Twilio).

## 📋 Características

- ✅ **Captura de video en tiempo real** desde cámara web
- ✅ **Detección de movimiento** usando procesamiento de imagen (OpenCV)
- ✅ **Alertas inteligentes** por Telegram y SMS (Twilio)
- ✅ **Grabación de video** optativa con movimiento detectado
- ✅ **Sistema de logging** completo y configurable
- ✅ **Arquitectura modular** y escalable
- ✅ **Pruebas unitarias** incluidas

## 🏗️ Estructura del Proyecto

```
videovigilancia/
├── src/
│   ├── __init__.py
│   ├── main.py                    # Punto de entrada principal
│   ├── config.py                  # Configuración centralizada
│   ├── camera/
│   │   ├── __init__.py
│   │   └── camera_manager.py      # Gestor de captura de video
│   ├── motion/
│   │   ├── __init__.py
│   │   └── motion_detector.py     # Detección de movimiento
│   ├── alerts/
│   │   ├── __init__.py
│   │   ├── telegram_alert.py      # Alertas por Telegram
│   │   └── twilio_alert.py        # Alertas por SMS
│   └── utils/
│       ├── __init__.py
│       └── logger.py              # Sistema de logging
├── tests/
│   ├── __init__.py
│   ├── test_motion_detector.py
│   └── test_alerts.py
├── config/
│   └── config.example.yaml
├── logs/                          # Archivos de log automáticos
├── recordings/                    # Videos grabados
├── .env.example                   # Variables de entorno (plantilla)
├── .env                          # Variables de entorno (crear localmente)
├── requirements.txt              # Dependencias Python
├── videovigilancia.code-workspace
└── README.md

```

## 🚀 Guía de Instalación Paso a Paso

### **Paso 1: Clonar o descargar el proyecto**

```bash
cd c:\dev\videovigilancia
```

### **Paso 2: Crear un entorno virtual (recomendado)**

```bash
# En Windows (PowerShell o CMD)
python -m venv .venv

# Activar el entorno virtual
.\.venv\Scripts\Activate
```

### **Paso 3: Instalar dependencias**

```bash
# Actualizar pip
python -m pip install --upgrade pip

# Instalar dependencias del proyecto
pip install -r requirements.txt
```

### **Paso 4: Configurar variables de entorno**

1. **Copiar el archivo de ejemplo:**
   ```bash
   copy .env.example .env
   ```

2. **Editar `.env` con tus credenciales:**
   ```txt
   # Configuración básica
   CAMERA_INDEX=0
   FRAME_WIDTH=640
   FRAME_HEIGHT=480
   
   # Telegram (obtener credenciales)
   TELEGRAM_ENABLED=True
   TELEGRAM_BOT_TOKEN=tu_bot_token
   TELEGRAM_CHAT_ID=tu_chat_id
   
   # Twilio (opcional)
   TWILIO_ENABLED=False
   TWILIO_ACCOUNT_SID=tu_account_sid
   TWILIO_AUTH_TOKEN=tu_token
   TWILIO_FROM_NUMBER=+1234567890
   TWILIO_TO_NUMBER=+0987654321
   ```

## 🔧 Configuración de Servicios de Alerta

### **Opción 1: Telegram (RECOMENDADO - Gratis)**

#### Crear un Bot de Telegram:

1. Abre Telegram y busca a `@BotFather`
2. Escribe `/newbot` y sigue las instrucciones
3. Dale un nombre a tu bot (ej: "VideoSurveillanceBot")
4. Dale un usuario único (ej: "video_surveillance_bot")
5. **Copia el token** que recibas (ej: `1234567890:ABCDEFGhijklmnop...`)

#### Obtener tu Chat ID:

1. Busca a `@userinfobot` en Telegram
2. Escribe algo y presiona enviar
3. El bot te dará tu `Chat ID` (ej: `123456789`)

#### Actualizar `.env`:
```txt
TELEGRAM_ENABLED=True
TELEGRAM_BOT_TOKEN=1234567890:ABCDEFGhijklmnop
TELEGRAM_CHAT_ID=123456789
```

### **Opción 2: Twilio SMS (De pago)**

1. Crear cuenta en [twilio.com](https://www.twilio.com)
2. Obtener número de Twilio
3. Copiar `Account SID` y `Auth Token` desde el dashboard
4. Actualizar `.env`:
```txt
TWILIO_ENABLED=True
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=auth_token_aqui
TWILIO_FROM_NUMBER=+1234567890
TWILIO_TO_NUMBER=+0987654321
```

## ▶️ Ejecución de la Aplicación

### **Ejecución básica:**

```bash
python src/main.py
```

### **Con más información de logging:**

```bash
# En el archivo .env, cambiar:
LOG_LEVEL=DEBUG

# Luego ejecutar:
python src/main.py
```

### **Control de la aplicación:**

- **Presionar 'Q'** para salir gracefully
- **Ctrl+C** también detiene la aplicación

## 🧪 Ejecutar Pruebas

```bash
# Ejecutar todas las pruebas
pytest tests/ -v

# Ejecutar pruebas con cobertura
pytest tests/ --cov=src --cov-report=html

# Ejecutar pruebas específicas
pytest tests/test_motion_detector.py -v
```

## 📊 Configuración Avanzada

### **Parámetros de Detección de Movimiento:**

```txt
# En .env
MOTION_THRESHOLD=5.0              # Umbral de diferencia (0-100)
BLUR_KERNEL_SIZE=21              # Tamaño kernel gaussiano (debe ser impar)
MIN_CONTOUR_AREA=500.0           # Área mínima de contorno
CONFIDENCE_THRESHOLD=2.0          # Confianza mínima para alerta (%)
ALERT_COOLDOWN=30                # Segundos entre alertas
```

### **Grabación de Video:**

```txt
# En .env
RECORDING_ENABLED=True
RECORDING_DIR=./recordings
RECORDING_FPS=20
RECORDING_CODEC=mp4v
```

### **Logging:**

```txt
# En .env
LOG_LEVEL=INFO                    # DEBUG, INFO, WARNING, ERROR, CRITICAL
MAX_LOG_SIZE_MB=10
LOG_BACKUP_COUNT=5
```

## 🔍 Solución de Problemas

### **"No se pudo abrir la cámara"**

```bash
# Verificar cámaras disponibles en Windows:
powershell -Command "Get-PnpDevice -Class Camera | Select-Object Name, Status"

# Cambiar el índice en .env:
CAMERA_INDEX=0  # Prueba con 0, 1, 2, etc.
```

### **Mensaje de Telegram no se envía**

- Verifica que tu internet esté activo
- Confirma que el `BOT_TOKEN` y `CHAT_ID` sean correctos
- Intenta enviar un mensaje manual a tu bot desde Telegram

### **Errores de dependencias**

```bash
# Reinstalar dependencias
pip uninstall -r requirements.txt -y
pip install -r requirements.txt
```

## 📈 Mejoras Futuras

- [ ] Soporte para múltiples cámaras
- [ ] Base de datos para historial de alertas
- [ ] Dashboard web en tiempo real
- [ ] Reconocimiento facial avanzado
- [ ] Almacenamiento en la nube
- [ ] Análisis de patrones de movimiento
- [ ] Notificaciones por correo electrónico
- [ ] API REST para integración

## 📚 Librerías Utilizadas

| Librería | Propósito | Versión |
|----------|-----------|---------|
| **opencv-python** | Procesamiento de video y detección de movimiento | 4.8.1.78 |
| **numpy** | Operaciones numéricas | 1.24.3 |
| **scipy** | Análisis científico | 1.11.4 |
| **python-telegram-bot** | Alertas por Telegram | 20.3 |
| **twilio** | Alertas por SMS | 8.10.0 |
| **python-dotenv** | Gestión de variables de entorno | 1.0.0 |
| **pytest** | Framework de testing | 7.4.3 |

## 🔐 Seguridad

⚠️ **Importante:**
- **NUNCA** commits `.env` a control de versiones
- Usa `.env.example` como plantilla
- Cambia regularmente tus tokens de bot
- Usa variables de entorno para credenciales sensibles

```.gitignore
.env
.venv/
__pycache__/
*.pyc
logs/
recordings/
```

## 📝 Licencia

Este proyecto es de código abierto bajo licencia MIT.

## 👨‍💻 Autor

Tu Nombre - [Tu LinkedIn/GitHub]

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Por favor:

1. Haz un fork del proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## 📞 Soporte

Para reportar bugs o solicitar features, abre un issue en el repositorio.

---

**Última actualización:** Febrero 2026
**Versión:** 1.0.0
