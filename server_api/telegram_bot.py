import os
import logging
import requests
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ------------------------------------------------------------
# CARGA DE CONFIG
# ------------------------------------------------------------
load_dotenv(".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BOT_SECRET = os.getenv("BOT_SHARED_SECRET", "")
API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8080")
BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "acubelasbot")

# Nivel de log configurable: DEBUG / INFO / WARNING / ERROR
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("telegram_bot")

# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------
HELP_TEXT = (
    "👋 Hola, soy el bot de Videovigilancia.\n\n"
    "Para emparejar, abre el enlace desde la app y pulsa START.\n"
    f"Ejemplo:\nhttps://t.me/{BOT_USERNAME}?start=PAIR_<pairingId>\n"
)

def extract_pairing_id(start_arg: str) -> str | None:
    """
    Espera un payload tipo: PAIR_P_xxx
    Devuelve pairingId: P_xxx
    """
    start_arg = (start_arg or "").strip()
    if start_arg.startswith("PAIR_"):
        return start_arg.replace("PAIR_", "", 1)
    return None

def safe_preview(text: str, max_len: int = 180) -> str:
    if text is None:
        return ""
    text = str(text)
    return text if len(text) <= max_len else text[:max_len] + "…"

# ------------------------------------------------------------
# HANDLERS
# ------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start
    /start PAIR_P_xxx
    """
    chat_id = update.effective_chat.id if update.effective_chat else None
    user = update.effective_user
    user_id = user.id if user else None
    username = user.username if user else None

    args = context.args or []
    logger.info("CMD /start | chat_id=%s user_id=%s username=%s args=%s", chat_id, user_id, username, args)

    if not args:
        await update.message.reply_text(HELP_TEXT)
        return

    payload = args[0].strip()
    pairing_id = extract_pairing_id(payload)

    logger.info("Payload recibido: %s | pairing_id extraído: %s", payload, pairing_id)

    if not pairing_id:
        await update.message.reply_text(
            "⚠️ Payload no reconocido.\n"
            "Vuelve a abrir el enlace desde la app y pulsa START.\n\n"
            f"Ejemplo: https://t.me/{BOT_USERNAME}?start=PAIR_<pairingId>"
        )
        return

    # Consultar OTP al servidor (endpoint privado)
    url = f"{API_BASE}/pairing/otp/{pairing_id}"
    headers = {"X-BOT-SECRET": BOT_SECRET}

    logger.info("Consultando OTP en servidor: %s", url)

    try:
        resp = requests.get(url, headers=headers, timeout=10)

        logger.info("Respuesta servidor OTP: HTTP %s", resp.status_code)
        logger.debug("Body servidor OTP: %s", safe_preview(resp.text, 600))

        if resp.status_code != 200:
            await update.message.reply_text(
                "❌ No puedo obtener el OTP del servidor.\n"
                f"HTTP {resp.status_code}\n{resp.text}"
            )
            return

        data = resp.json()
        otp = data.get("otp")
        ttl = data.get("ttlRemaining")

        logger.info("OTP obtenido OK | pairing_id=%s otp=%s ttlRemaining=%s", pairing_id, otp, ttl)

        await update.message.reply_text(
            f"✅ Tu OTP es: {otp}\n"
            f"⏳ Caduca en {ttl} segundos.\n\n"
            "Vuelve a la app Videovigilancia Mobile, escribe el OTP y confirma."
        )

    except requests.Timeout:
        logger.exception("Timeout consultando OTP (requests.Timeout)")
        await update.message.reply_text("❌ Timeout consultando el servidor. Inténtalo de nuevo.")
    except Exception as e:
        logger.exception("Error consultando OTP: %s", e)
        await update.message.reply_text(f"❌ Error consultando el servidor: {e}")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando simple para comprobar que el bot está vivo."""
    logger.info("CMD /ping recibido")
    await update.message.reply_text("pong ✅")

# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------
def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Falta TELEGRAM_BOT_TOKEN en .env")
    if not BOT_SECRET:
        raise SystemExit("Falta BOT_SHARED_SECRET en .env")

    logger.info("Arrancando bot @%s (polling)", BOT_USERNAME)
    logger.info("API_BASE=%s | LOG_LEVEL=%s", API_BASE, LOG_LEVEL)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))

    # Polling loop
    logger.info("🤖 Bot listo. Ctrl+C para parar.")
    app.run_polling()

if __name__ == "__main__":
    main()