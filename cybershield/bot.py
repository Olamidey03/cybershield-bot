import os
import logging
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from modules.risk_assessment import get_risk_handler
from modules.password_checker import get_password_handler
from modules.locked import network_scanner_locked, log_analysis_locked
from keep_alive import keep_alive

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("1️⃣ Risk Assessment"), KeyboardButton("2️⃣ Password Analyzer")],
        [KeyboardButton("3️⃣ Network Scanner 🔒"), KeyboardButton("4️⃣ Log Analyzer 🔒")],
        [KeyboardButton("ℹ️ About")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

WELCOME_MESSAGE = (
    "🛡️ *Welcome to CyberShield Assistant Bot!*\n\n"
    "Your personal cybersecurity toolkit on Telegram.\n\n"
    "*Available Modules:*\n"
    "1️⃣ *Risk Assessment* — Evaluate your security posture\n"
    "2️⃣ *Password Analyzer* — Test password strength\n"
    "3️⃣ *Network Scanner* 🔒 — Port scanning _(coming soon)_\n"
    "4️⃣ *Log Analyzer* 🔒 — Log threat detection _(coming soon)_\n\n"
    "Select an option from the menu below to get started."
)

ABOUT_MESSAGE = (
    "ℹ️ *About CyberShield*\n\n"
    "CyberShield is a cybersecurity learning and assessment bot "
    "built to help you understand and apply security principles.\n\n"
    "*Modules:*\n"
    "• *Risk Assessment* — Based on industry-standard security controls\n"
    "• *Password Analyzer* — Evaluates complexity, length, and patterns\n"
    "• *Network Scanner* — Socket-based port scanning _(locked)_\n"
    "• *Log Analyzer* — SIEM-style log pattern matching _(locked)_\n\n"
    "*Stack:* Python + python-telegram-bot\n\n"
    "Stay safe out there. 🔐"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        WELCOME_MESSAGE,
        parse_mode="Markdown",
        reply_markup=MAIN_MENU_KEYBOARD,
    )

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(ABOUT_MESSAGE, parse_mode="Markdown")

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "BOT_TOKEN is not set.\n"
            "Add it to your .env file or set it as a Replit secret named BOT_TOKEN."
        )

    app = Application.builder().token(token).build()

    # Conversation handlers (must be registered before catch-all handlers)
    app.add_handler(get_risk_handler())
    app.add_handler(get_password_handler())

    # Simple command + menu button handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^ℹ️ About$"), about))
    app.add_handler(MessageHandler(filters.Regex("^3️⃣ Network Scanner"), network_scanner_locked))
    app.add_handler(MessageHandler(filters.Regex("^4️⃣ Log Analyzer"), log_analysis_locked))

    logger.info("CyberShield bot is running...")
    keep_alive()
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
