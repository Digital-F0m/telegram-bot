# ==============================
# IMPORTS
# ==============================
import os
import json
import re
import random
import logging
from pathlib import Path
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ==============================
# CONFIG / ENV
# ==============================
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")
OWNER_ID = int(OWNER_ID) if OWNER_ID and OWNER_ID.isdigit() else None
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
AUTO_FORWARD = os.getenv("AUTO_FORWARD", "1").lower() in ("1", "true", "yes")

if not TOKEN:
    raise RuntimeError("❌ BOT_TOKEN missing in .env")

BOT_STATS = {"photos": 0, "documents": 0}

# ==============================
# PATHS
# ==============================
BASE_DIR = Path("downloads")
PHOTOS_DIR = BASE_DIR / "photos"
FILES_DIR = BASE_DIR / "files"

PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)

# ==============================
# LOGGING
# ==============================
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==============================
# KEYWORDS LOADER
# ==============================
KEYWORDS = {}
KEYWORDS_PATH = Path("keywords.json")

if KEYWORDS_PATH.exists():
    try:
        with KEYWORDS_PATH.open(encoding="utf-8") as f:
            KEYWORDS = json.load(f)
    except Exception:
        logger.exception("Failed to load keywords.json")

# ==============================
# UTILITIES
# ==============================
def sanitize_filename(name: str) -> str:
    """Sanitize filename to remove illegal characters and limit length."""
    name = re.sub(r"[\\/]", "_", name)
    name = re.sub(r"[^A-Za-z0-9_.\-() ]+", "", name)
    return name[:200]

def is_admin(user_id: int) -> bool:
    return OWNER_ID is not None and user_id == OWNER_ID

def admin_only(func):
    """Decorator to restrict commands to admin only."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only command.")
            return
        await func(update, context)
    return wrapper

# ==============================
# BASIC COMMANDS
# ==============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Bot is running!\nType /help to see available commands."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Start bot\n"
        "/help - Show help\n"
        "/menu - Open menu\n"
        "/getmyid - Show your user ID\n\n"
        "Admin only:\n"
        "/toggleforward - Toggle auto-forward\n"
        "/getstats - Show bot stats"
    )

async def getmyid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 Your ID: `{update.effective_user.id}`", parse_mode="Markdown"
    )

# ==============================
# ADMIN COMMANDS
# ==============================
@admin_only
async def toggleforward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTO_FORWARD
    AUTO_FORWARD = not AUTO_FORWARD
    await update.message.reply_text(
        f"Auto-forward {'✅ ON' if AUTO_FORWARD else '❌ OFF'}"
    )

@admin_only
async def getstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 Stats\nPhotos: {BOT_STATS['photos']}\nFiles: {BOT_STATS['documents']}"
    )

# ==============================
# MENU / CALLBACKS
# ==============================
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("ℹ About", callback_data="about")],
        [InlineKeyboardButton("📞 Contact", callback_data="contact")]
    ]
    await update.message.reply_text(
        "📋 Menu",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "about":
        await query.edit_message_text("🤖 Telegram Automation Bot\nDeveloped by Efren")
    elif query.data == "contact":
        await query.edit_message_text("📞 Contact: @your_username")

# ==============================
# FILE HANDLERS
# ==============================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    photo = update.message.photo[-1]
    file = await photo.get_file()

    filename = sanitize_filename(f"photo_{user.id}_{file.file_id}.jpg")
    await file.download_to_drive(PHOTOS_DIR / filename)

    BOT_STATS["photos"] += 1
    logger.info(f"Photo received from {user.username} ({user.id}): {filename}")

    if OWNER_ID and AUTO_FORWARD:
        await context.bot.send_photo(
            chat_id=OWNER_ID,
            photo=photo.file_id,
            caption=f"📸 Photo from {user.id}"
        )

    await update.message.reply_text(f"📸 Saved as `{filename}`", parse_mode="Markdown")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    user = update.message.from_user

    if doc.file_size > MAX_FILE_SIZE:
        await update.message.reply_text("⚠️ File too large.")
        return

    file = await doc.get_file()
    filename = sanitize_filename(f"{user.id}_{doc.file_name}")
    await file.download_to_drive(FILES_DIR / filename)

    BOT_STATS["documents"] += 1
    logger.info(f"Document received from {user.username} ({user.id}): {filename}")

    if OWNER_ID and AUTO_FORWARD:
        await context.bot.send_document(
            chat_id=OWNER_ID,
            document=doc.file_id,
            caption=f"📄 File from {user.id}"
        )

    await update.message.reply_text(f"📄 Saved `{filename}`", parse_mode="Markdown")

# ==============================
# KEYWORD REPLIES
# ==============================
async def keyword_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").lower()
    for pattern, replies in KEYWORDS.items():
        if re.search(pattern, text):
            await update.message.reply_text(random.choice(replies))
            logger.info(f"Keyword matched from {update.effective_user.username}: {text}")
            return

# ==============================
# ERROR HANDLER
# ==============================
async def error_handler(update, context):
    logger.exception("Bot error:", exc_info=context.error)

# ==============================
# MAIN MESSAGE HANDLER (LOGGING EXAMPLE)
# ==============================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"Message from {update.effective_user.username}: {update.message.text}")
    await update.message.reply_text("Got your message!")

# ==============================
# MAIN
# ==============================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("getmyid", getmyid))
    app.add_handler(CommandHandler("toggleforward", toggleforward))
    app.add_handler(CommandHandler("getstats", getstats))

    # Callbacks
    app.add_handler(CallbackQueryHandler(handle_buttons))

    # Messages
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, keyword_reply))

    # Error handler
    app.add_error_handler(error_handler)

    logger.info("✅ Bot running and ready to receive messages!")
    app.run_polling()

if __name__ == "__main__":
    main()
