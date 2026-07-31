import os
import logging
import warnings
from telegram.warnings import PTBUserWarning
# CallbackQueryHandler inside ConversationHandler (entry_points only) is
# intentional — suppress the cosmetic per_message advisory.
warnings.filterwarnings("ignore", category=PTBUserWarning)
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    PollAnswerHandler,
    filters,
    ContextTypes,
)
from modules.risk_assessment import get_risk_handler
from modules.password_checker import get_password_handler
from modules.net_scanner import get_network_scanner_handler
from modules.log_analyzer import get_log_analyzer_handler
from modules.pdf_assistant import (
    get_quiz_handler,
    get_interview_handler,
    scenario_command,
    handle_poll_answer,
    handle_quiz_settings_cb,
    handle_quiz_study_guide_cb,
    handle_quiz_new_round_cb,
)
from modules.input_parser import handle_raw_text, handle_document
from modules.menu import MAIN_MENU_KB, get_quiz_menu_callback_handler
from keep_alive import keep_alive


async def handle_hint_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the stored quiz hint as a Telegram alert popup (show_alert=True)."""
    query = update.callback_query
    hint = context.user_data.get(
        "quiz_hint", "No hint available — try generating a new quiz question."
    )
    await query.answer(text=hint[:200], show_alert=True)

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
    "🛡️ <b>Welcome to CyberShield Assistant Bot!</b>\n\n"
    "Your personal cybersecurity toolkit on Telegram.\n\n"
    "<b>Available Modules:</b>\n"
    "1️⃣ <b>Risk Assessment</b> — Evaluate your security posture\n"
    "2️⃣ <b>Password Analyzer</b> — Test password strength\n"
    "3️⃣ <b>Network Scanner</b> — AI pentest analysis of scan data\n"
    "4️⃣ <b>Log Analyzer</b> — AI SOC threat hunting on raw logs\n\n"
    "📄 <b>Document Assistant:</b>\n"
    "Upload a PDF, DOCX, TXT, or CSV — then tap the inline buttons below "
    "or use /quiz, /interview, /scenario.\n\n"
    "Select an option from the menu below to get started."
)

ABOUT_MESSAGE = (
    "ℹ️ <b>About CyberShield</b>\n\n"
    "CyberShield is a cybersecurity learning and assessment bot "
    "built to help you understand and apply security principles.\n\n"
    "<b>Modules:</b>\n"
    "• <b>Risk Assessment</b> — Based on industry-standard security controls\n"
    "• <b>Password Analyzer</b> — Evaluates complexity, length, and patterns\n"
    "• <b>Network Scanner</b> — Gemini-powered pentest analysis of Nmap/scan data "
    "(vulnerabilities, CVEs, attack surface, exploitability, remediation)\n"
    "• <b>Log Analyzer</b> — Gemini-powered SOC threat hunting on raw logs "
    "(IoCs, MITRE ATT&amp;CK mapping, severity, containment actions)\n"
    "• <b>Document Assistant</b> — Upload a PDF/DOCX/TXT/CSV, then quiz yourself, practice "
    "mock interviews, or run incident response scenarios based on it\n\n"
    "<b>Gamification:</b>\n"
    "• Earn <b>+10 XP ⚡</b> per correct quiz answer\n"
    "• Maintain a <b>daily streak 🔥</b> by quizzing every day\n"
    "• Get a <b>Coach Report</b> after every round with Strengths / Growth Areas\n"
    "• Customise pool size, focus, and difficulty — then tap ▶️ Start New Round\n\n"
    "<b>Stack:</b> Python + python-telegram-bot + Gemini (google-genai, gemini-2.5-flash)\n\n"
    "Stay safe out there. 🔐"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        WELCOME_MESSAGE,
        parse_mode="HTML",
        reply_markup=MAIN_MENU_KEYBOARD,
    )
    # Show the inline quick-action buttons as a separate message so they
    # stay visible and tappable without cluttering the welcome text.
    await update.message.reply_text(
        "⚡ <b>Quick actions:</b>",
        parse_mode="HTML",
        reply_markup=MAIN_MENU_KB,
    )

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(ABOUT_MESSAGE, parse_mode="HTML")

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "BOT_TOKEN is not set.\n"
            "Add it to your .env file or set it as a Replit secret named BOT_TOKEN."
        )

    app = Application.builder().token(token).build()

    # --- Conversation handlers (must come before catch-all handlers) ---
    app.add_handler(get_risk_handler())
    app.add_handler(get_password_handler())
    app.add_handler(get_network_scanner_handler())   # includes menu:scan callback entry
    app.add_handler(get_log_analyzer_handler())       # includes menu:log callback entry
    app.add_handler(get_quiz_handler())               # includes quiz:* difficulty callbacks

    # --- Inline callback handlers (non-conversation) ---
    app.add_handler(get_quiz_menu_callback_handler())  # menu:quiz → show difficulty sub-menu
    app.add_handler(CallbackQueryHandler(handle_hint_callback, pattern=r"^quiz:hint$"))

    # --- Step 7: Action Keyboard callbacks ---
    # Settings (focus / pool / adjust) — pattern matches all three with one handler
    app.add_handler(
        CallbackQueryHandler(
            handle_quiz_settings_cb,
            pattern=r"^quiz:(focus|pool|adjust):",
        )
    )
    app.add_handler(
        CallbackQueryHandler(handle_quiz_study_guide_cb, pattern=r"^quiz:studyguide$")
    )
    app.add_handler(
        CallbackQueryHandler(handle_quiz_new_round_cb, pattern=r"^quiz:newround$")
    )

    # --- Step 6: Native poll answer grading ---
    app.add_handler(PollAnswerHandler(handle_poll_answer))

    # --- Simple command & menu button handlers ---
    app.add_handler(CommandHandler("scenario", scenario_command))
    app.add_handler(MessageHandler(filters.Regex("^🚨 Run Incident Scenario$"), scenario_command))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^About$"), about))

    # --- Interview handler (registered after quiz to avoid catching quiz keyboard) ---
    app.add_handler(get_interview_handler())

    # --- Input Parsing Engine (catch-all — must stay last) ---
    # Handles all document uploads (.pdf, .docx, .txt, .csv) and plain-text
    # pastes not claimed by any active conversation above.
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_raw_text))

    logger.info("CyberShield bot is running...")
    keep_alive()
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
