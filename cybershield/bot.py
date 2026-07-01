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
from modules.net_scanner import get_network_scanner_handler
from modules.log_analyzer import get_log_analyzer_handler
from modules.pdf_assistant import (
    handle_pdf_upload,
    get_quiz_handler,
    get_interview_handler,
    scenario_command,
)
from keep_alive import keep_alive

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("1 Risk Assessment"), KeyboardButton("2 Password Analyzer")],
        [KeyboardButton("3 Network Scanner"), KeyboardButton("4 Log Analyzer")],
        [KeyboardButton("About")],
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
    "3️⃣ *Network Scanner* — AI pentest analysis of scan data\n"
    "4️⃣ *Log Analyzer* — AI SOC threat hunting on raw logs\n\n"
    "📄 *Document Assistant:*\n"
    "Send me a PDF, then use the buttons that appear to:\n"
    "📚 Generate Quiz — cybersecurity quiz question\n"
    "💼 Mock Interview — mock interview question\n"
    "🚨 Run Incident Scenario — incident response lab scenario\n\n"
    "Select an option from the menu below to get started."
)

ABOUT_MESSAGE = (
    "ℹ️ *About CyberShield*\n\n"
    "CyberShield is a cybersecurity learning and assessment bot "
    "built to help you understand and apply security principles.\n\n"
    "*Modules:*\n"
    "• *Risk Assessment* — Based on industry-standard security controls\n"
    "• *Password Analyzer* — Evaluates complexity, length, and patterns\n"
    "• *Network Scanner* — Gemini-powered pentest analysis of Nmap/scan data "
    "(vulnerabilities, CVEs, attack surface, exploitability, remediation)\n"
    "• *Log Analyzer* — Gemini-powered SOC threat hunting on raw logs "
    "(IoCs, MITRE ATT&CK mapping, severity, containment actions)\n"
    "• *Document Assistant* — Upload a PDF, then quiz yourself, practice "
    "mock interviews, or run incident response scenarios based on it\n\n"
    "*Stack:* Python + python-telegram-bot + Gemini (google-genai, gemini-2.5-flash)\n\n"
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
    app.add_handler(get_network_scanner_handler())
    app.add_handler(get_log_analyzer_handler())
    app.add_handler(get_quiz_handler())
    app.add_handler(get_interview_handler())

    # PDF document assistant
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf_upload))
    app.add_handler(CommandHandler("scenario", scenario_command))
    app.add_handler(MessageHandler(filters.Regex("^🚨 Run Incident Scenario$"), scenario_command))

    # Simple command + menu button handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^About$"), about))

    logger.info("CyberShield bot is running...")
    keep_alive()
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
