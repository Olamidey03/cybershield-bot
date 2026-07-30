import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from modules.gemini_client import generate_with_retry
from modules.html_utils import safe_reply_html, send_html_report, typing_action, NAV_FOOTER

logger = logging.getLogger(__name__)

WAITING_LOG_DATA = 0

# ---------------------------------------------------------------------------
# Tier 2 SOC Analyst prompt — table output inside <pre><code> blocks
# ---------------------------------------------------------------------------
LOG_ANALYZER_PROMPT = (
    "You are a Tier 2 SOC Analyst performing a deep-dive threat hunt on the raw log data "
    "provided below. Specifically scan for: brute-force login attempts, unauthorized SSH "
    "access, and privilege escalation events.\n\n"
    "Structure your response with EXACTLY these four sections, each headed by a <b> tag:\n\n"
    "<b>Findings Table</b>\n"
    "Output an ASCII table inside <pre><code> tags with these columns:\n"
    "| Finding Type | Source IP / User | Count / Details | Severity | Recommended Action |\n"
    "Use --- as the column separator row. List every distinct finding as its own row. "
    "If no findings exist for a category write 'None detected'.\n\n"
    "<b>Threat Actor Intent & MITRE ATT&CK Mapping</b>\n"
    "Describe likely intent and map each observed behavior to a MITRE ATT&CK technique ID "
    "and name (e.g. T1110.001 — Password Spraying). Use <i> for technique IDs.\n\n"
    "<b>Severity Rating</b>\n"
    "State exactly one of: Low, Medium, High, or Critical — wrapped in <b> — followed by a "
    "one-sentence justification.\n\n"
    "<b>Immediate Incident Response Actions</b>\n"
    "Give 3–5 concrete, numbered containment steps. Put any shell or config commands inside "
    "<pre><code>...</code></pre> blocks.\n\n"
    "Rules:\n"
    "• Use ONLY HTML tags compatible with Telegram: <b>, <i>, <pre><code>. No Markdown.\n"
    "• Escape literal < or > inside explanatory text as &lt; and &gt;.\n"
    "• Base every finding strictly on the data provided. Do NOT invent findings.\n\n"
    "LOG DATA:\n{data}"
)

_ENTRY_MSG = (
    "🧾 <b>AI Log Analyzer — Tier 2 SOC Threat Hunt</b>\n\n"
    "Paste raw log lines (SIEM, Apache, Linux auth, or firewall events) and I'll analyze them "
    "as a Tier 2 SOC Analyst, scanning for brute-force, unauthorized SSH, and privilege "
    "escalation — with a structured findings table and MITRE ATT&amp;CK mapping.\n\n"
    + NAV_FOOTER
)


async def start_log_analyzer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await safe_reply_html(update.message, _ENTRY_MSG)
    return WAITING_LOG_DATA


async def start_log_analyzer_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point triggered by the 📜 Log Analysis inline button."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=_ENTRY_MSG,
        parse_mode="HTML",
    )
    return WAITING_LOG_DATA


async def analyze_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await typing_action(context.bot, update.effective_chat.id)
    data = update.message.text
    status_msg = await update.message.reply_text(
        "🕵️ Running Tier 2 SOC threat hunt on the log data, please wait..."
    )

    try:
        response = await generate_with_retry(
            contents=LOG_ANALYZER_PROMPT.format(data=data)
        )
        result_text = response.text
    except Exception as exc:
        logger.exception("Log analysis failed")
        await status_msg.edit_text(
            f"❌ Analysis failed: {exc}\n\n"
            "Paste more log data to try again, or /cancel to exit."
        )
        return WAITING_LOG_DATA

    await send_html_report(status_msg, result_text, context.bot, update.effective_chat.id)
    await update.message.reply_text("Paste more log data to analyze, or /cancel to go back.")
    return WAITING_LOG_DATA


async def cancel_log_analyzer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Log analyzer closed. Use /start to return to the menu.")
    return ConversationHandler.END


def get_log_analyzer_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^4 Log Analyzer$"), start_log_analyzer),
            CallbackQueryHandler(start_log_analyzer_cb, pattern=r"^menu:log$"),
        ],
        states={
            WAITING_LOG_DATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_logs)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_log_analyzer)],
        per_message=False,
    )
