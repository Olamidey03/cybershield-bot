"""
menu.py — Inline keyboard definitions and top-level menu callback handler.

Keyboards
---------
MAIN_MENU_KB  : shown after /start — three primary action buttons.
DIFFICULTY_KB : shown when the user taps 🧠 Take Quiz — three difficulty tiers.

Callback data contract
----------------------
  menu:quiz        → edit message to show DIFFICULTY_KB
  menu:log         → entry point for log analyzer ConversationHandler
  menu:scan        → entry point for network scanner ConversationHandler
  quiz:beginner    → entry point for quiz ConversationHandler (beginner)
  quiz:intermediate→ entry point for quiz ConversationHandler (intermediate)
  quiz:advanced    → entry point for quiz ConversationHandler (advanced)
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyboard layouts
# ---------------------------------------------------------------------------

MAIN_MENU_KB = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("🧠 Take Quiz", callback_data="menu:quiz"),
            InlineKeyboardButton("📜 Log Analysis", callback_data="menu:log"),
            InlineKeyboardButton("🌐 Network Scan", callback_data="menu:scan"),
        ]
    ]
)

DIFFICULTY_KB = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("Beginner 🟢", callback_data="quiz:beginner"),
            InlineKeyboardButton("Intermediate 🟡", callback_data="quiz:intermediate"),
            InlineKeyboardButton("Advanced 🔴", callback_data="quiz:advanced"),
        ]
    ]
)


# ---------------------------------------------------------------------------
# menu:quiz callback — swaps main menu for difficulty sub-menu
# ---------------------------------------------------------------------------

async def handle_quiz_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 🧠 Take Quiz button: replaces the main menu with the difficulty picker."""
    query = update.callback_query
    await query.answer()

    if not context.user_data.get("parsed_text"):
        await query.edit_message_text(
            "📎 Please upload a document (.pdf, .docx, .txt, or .csv) or paste your text "
            "first, then choose a difficulty.\n\n"
            "💡 <i>Type /start to return to the main menu.</i>",
            parse_mode="HTML",
        )
        return

    await query.edit_message_text(
        "🧠 <b>Take Quiz</b>\n\nSelect a difficulty level:",
        parse_mode="HTML",
        reply_markup=DIFFICULTY_KB,
    )


def get_quiz_menu_callback_handler() -> CallbackQueryHandler:
    return CallbackQueryHandler(handle_quiz_menu_callback, pattern=r"^menu:quiz$")
