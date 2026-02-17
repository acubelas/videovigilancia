# ⚡ INICIO RÁPIDO - 5 PASOS

## Paso 1️⃣: Instalar Entorno Virtual

```bash
cd c:\dev\videovigilancia
python -m venv .venv
.\.venv\Scripts\Activate
```

## Paso 2️⃣: Instalar Dependencias

```bash
pip install -r requirements.txt
```

## Paso 3️⃣: Configurar Telegram (Recomendado)

**En tu móvil con Telegram:**

1. Busca `@BotFather`
2. Escribe `/newbot`
3. Elige un nombre: `Mi VideoSurveillance Bot`
4. Elige un usuario: `mi_videosurveillance_bot`
5. 📋 **Copia el token** → `1234567890:ABCDEFGhijklmnop...`

**Obtener tu Chat ID:**

1. Busca `@userinfobot`
2. Envía un mensaje
3. 📋 **Copia tu ID** → `123456789`

## Paso 4️⃣: Crear Archivo de Configuración

```bash
copy .env.example .env
```

**Edita `.env` y añade:**

```txt
TELEGRAM_ENABLED=True
TELEGRAM_BOT_TOKEN=1234567890:ABCDEFGhijklmnop
TELEGRAM_CHAT_ID=123456789
```

## Paso 5️⃣: ¡Ejecutar!

```bash
python src/main.py
```

**Espera a que vea:**
```
[INFO] Cámara inicializada correctamente: 640x480 @ 30 FPS
[INFO] Alertas por Telegram habilitadas
```

---

## ✅ Lista de Verificación

- [ ] Python 3.8+
- [ ] Entorno virtual activado
- [ ] Dependencias instaladas (`pip list` debe mostrar opencv, numpy, etc)
- [ ] Archivo `.env` creado y configurado
- [ ] Token de Telegram obtenido
- [ ] Chat ID de Telegram obtenido
- [ ] Cámara web funcionando (prueba con cualquier app)

---

## 🆘 Solución Rápida de Problemas

| Problema | Solución |
|----------|----------|
| "Cámara no abre" | Cambia `CAMERA_INDEX=0` a 1, 2, etc en .env |
| "Module not found" | `pip install -r requirements.txt` |
| "Telegram no funciona" | Verifica bot token y chat ID |
| "ImportError: cv2" | `pip install opencv-python` |

---

## 📞 Próximos Pasos

- 📖 Lee [README.md](README.md) para documentación completa
- 🏗️ Lee [ARCHITECTURE.md](ARCHITECTURE.md) para entender el flujo
- 🧪 Ejecuta pruebas: `pytest tests/ -v`
- 🔧 Ajusta parámetros de detección en `.env`

---

**¿Tienes preguntas?** Abre un issue en el repositorio 🐛
