import os
import logging
import requests
from dotenv import load_dotenv

from telegram import (
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from server_api.db import init_db, upsert_link

# ------------------------------------------------------------
# CARGA DE CONFIG
# ------------------------------------------------------------
load_dotenv(".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BOT_SECRET = os.getenv("BOT_SHARED_SECRET", "")
API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8080")
BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "acubelasbot")

# Para normalizar teléfonos sin '+', por defecto España (+34)
DEFAULT_COUNTRY_CALLING_CODE = os.getenv("DEFAULT_COUNTRY_CALLING_CODE", "34")

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
# DB INIT
# ------------------------------------------------------------
init_db()

# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------
HELP_TEXT = (
    "👋 Hola, soy el bot de Videovigilancia.\n\n"
    "✅ Emparejar por Telegram (recibir OTP):\n"
    f"   https://t.me/{BOT_USERNAME}?start=PAIR_<pairingId>\n\n"
    "✅ Vincular tu teléfono (para que el servidor pueda enviarte OTP por número):\n"
    f"   https://t.me/{BOT_USERNAME}?start=LINK_<pairingId>\n\n"
    "Comandos:\n"
    "  /ping  -> comprobar bot\n"
)

def safe_preview(text: str, max_len: int = 400) -> str:
    if text is None:
        return ""
    text = str(text)
    return text if len(text) <= max_len else text[:max_len] + "…"

def parse_start_payload(arg: str) -> tuple[str | None, str | None]:
    """
    PAIR_<pairingId> => ("PAIR", "<pairingId>")
    LINK_<pairingId> => ("LINK", "<pairingId>")
    """
    s = (arg or "").strip()
    if s.startswith("PAIR_"):
        return "PAIR", s.replace("PAIR_", "", 1)
    if s.startswith("LINK_"):
        return "LINK", s.replace("LINK_", "", 1)
    return None, None

def normalize_phone_e164(raw_phone: str) -> str:
    """
    Normaliza a E.164 (básico):
    - Si viene con '+' => se respeta
    - Si viene '34XXXXXXXXX' => '+34XXXXXXXXX'
    - Si viene 9 dígitos => '+34' + número (por defecto España)
    - fallback: '+' + raw
    """
    raw = (raw_phone or "").strip().replace(" ", "")
    if not raw:
        return ""

    if raw.startswith("+"):
        return raw

    if raw.startswith(DEFAULT_COUNTRY_CALLING_CODE):
        return f"+{raw}"

    if raw.isdigit() and len(raw) == 9:
        return f"+{DEFAULT_COUNTRY_CALLING_CODE}{raw}"

    return f"+{raw}"

def get_otp_from_server(pairing_id: str) -> tuple[str, int]:
    """
    Llama al endpoint privado del server:
      GET {API_BASE}/pairing/otp/{pairing_id}
      Header: X-BOT-SECRET
    """
    url = f"{API_BASE}/pairing/otp/{pairing_id}"
    headers = {"X-BOT-SECRET": BOT_SECRET}

    logger.info("Consultando OTP en servidor: %s", url)

    resp = requests.get(url, headers=headers, timeout=10)

    logger.info("Respuesta servidor OTP: HTTP %s", resp.status_code)
    logger.debug("Body servidor OTP: %s", safe_preview(resp.text, 1000))

    if resp.status_code != 200:
        raise RuntimeError(f"OTP error {resp.status_code}: {resp.text}")

    data = resp.json()
    otp = str(data.get("otp", "")).strip()
    ttl = int(data.get("ttlRemaining", 0))
    if not otp:
        raise RuntimeError("OTP vacío en respuesta del servidor")
    return otp, ttl

# ------------------------------------------------------------
# HANDLERS
# ------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start
    /start PAIR_<pairingId>
    /start LINK_<pairingId>
    """
    msg = update.message
    chat = update.effective_chat
    user = update.effective_user

    args = context.args or []
    logger.info(
        "CMD /start | chat_id=%s user_id=%s username=%s args=%s",
        chat.id if chat else None,
        user.id if user else None,
        user.username if user else None,
        args,
    )

    if not args:
        await msg.reply_text(HELP_TEXT)
        return

    mode, pairing_id = parse_start_payload(args[0])
    logger.info("Payload mode=%s pairing_id=%s", mode, pairing_id)

    if not mode or not pairing_id:
        await msg.reply_text("⚠️ Payload no reconocido. Abre el enlace desde la app.")
        await msg.reply_text(HELP_TEXT)
        return

    if mode == "PAIR":
        # Envía OTP directamente
        try:
            otp, ttl = get_otp_from_server(pairing_id)
            logger.info("OTP obtenido OK | pairing_id=%s otp=%s ttl=%s", pairing_id, otp, ttl)
            await msg.reply_text(
                f"✅ Tu OTP es: {otp}\n"
                f"⏳ Caduca en {ttl} segundos.\n\n"
                "Vuelve a la app Videovigilancia Mobile, escribe el OTP y confirma."
            )
        except Exception as e:
            logger.exception("Error en PAIR: %s", e)
            await msg.reply_text(f"❌ No puedo obtener el OTP.\n{e}")
        return

    if mode == "LINK":
        # Guardamos pairingId pendiente para enviar OTP tras vincular contacto
        context.user_data["pending_pairing_id"] = pairing_id

        # Botón “Compartir contacto” (Telegram enviará el teléfono al bot) 
        button = KeyboardButton(text="📱 Compartir mi contacto", request_contact=True)
        keyboard = ReplyKeyboardMarkup([[button]], resize_keyboard=True, one_time_keyboard=True)

        await msg.reply_text(
            "Para vincular tu número, pulsa el botón y comparte tu contacto.\n"
            "Después te enviaré el OTP automáticamente.",
            reply_markup=keyboard,
        )
        return

async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Recibe el contacto compartido por el usuario.
    Guarda phone->chat_id en SQLite y envía OTP si había pending_pairing_id.
    """
    msg = update.message
    chat = update.effective_chat
    user = update.effective_user

    if not msg or not msg.contact:
        return

    contact = msg.contact
    logger.info(
        "CONTACT | chat_id=%s user_id=%s contact_user_id=%s phone=%s",
        chat.id if chat else None,
        user.id if user else None,
        contact.user_id,
        contact.phone_number,
    )

    # Seguridad: solo aceptar el contacto del propio usuario (evita vincular el teléfono de otro)
    if contact.user_id and user and contact.user_id != user.id:
        await msg.reply_text(
            "❌ Por seguridad, solo acepto tu propio contacto (no el de otra persona).",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    phone_e164 = normalize_phone_e164(contact.phone_number or "")
    if not phone_e164:
        await msg.reply_text(
            "❌ No he podido leer tu número. Inténtalo de nuevo.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Guardar vínculo en SQLite
    upsert_link(
        phone_e164=phone_e164,
        chat_id=chat.id,
        telegram_user_id=user.id if user else 0,
        username=user.username if user else None,
    )

    logger.info("DB UPSERT OK | phone=%s chat_id=%s user_id=%s", phone_e164, chat.id, user.id if user else None)
    
    await msg.reply_text(
        f"✅ Vinculación guardada.\n"
        f"Teléfono: {phone_e164}\n"
        f"chat_id: {chat.id}\n\n"
        "A partir de ahora el servidor podrá enviarte OTP por Telegram usando tu número.",
        reply_markup=ReplyKeyboardRemove(),
    )

    # Si venía con LINK_<pairingId>, enviamos OTP automáticamente
    pending_pairing_id = context.user_data.pop("pending_pairing_id", None)
    if pending_pairing_id:
        try:
            otp, ttl = get_otp_from_server(pending_pairing_id)
            await msg.reply_text(
                f"✅ Tu OTP es: {otp}\n"
                f"⏳ Caduca en {ttl} segundos.\n\n"
                "Vuelve a la app Videovigilancia Mobile y confirma."
            )
        except Exception as e:
            logger.exception("Error enviando OTP tras LINK: %s", e)
            await msg.reply_text(f"❌ No puedo obtener el OTP.\n{e}")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("CMD /ping")
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

    # Handler contacto (vinculación) 
    app.add_handler(MessageHandler(filters.CONTACT, on_contact))

    logger.info("🤖 Bot listo. Ctrl+C para parar.")
    app.run_polling()

if __name__ == "__main__":
    main()