import asyncio
import logging

from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from modules.gemini_client import get_client, MODEL
from modules.html_utils import safe_reply_html, safe_edit_html

logger = logging.getLogger(__name__)

WAITING_LOG_DATA = 0

LOG_ANALYZER_PROMPT = (
    "You are a senior SOC Threat Hunter analyzing raw log data (SIEM, Apache, Linux auth, or "
    "firewall events).\n\n"
    "Format your ENTIRE response using clean HTML tags compatible with Telegram's HTML parse "
    "mode. Use ONLY these tags: <b> for section headers and emphasis, <i> for italics, and "
    "<pre><code>...</code></pre> for any raw log lines or technical output. Do NOT use Markdown "
    "syntax at all (no **, no *, no backtick fences). Escape any literal '<' or '>' characters "
    "that appear inside your own explanatory text (not part of a tag) as '&lt;' and '&gt;' so "
    "the HTML stays valid.\n\n"
    "Structure the response with EXACTLY these four section headers, each wrapped in <b> tags, "
    "in this order:\n\n"
    "<b>Identified Indicators of Compromise (IoCs)</b> — list specific IPs, accounts, URIs, or patterns of concern.\n"
    "<b>Threat Actor Intent/Tactics</b> — describe likely intent and map observed behavior to MITRE ATT&amp;CK "
    "technique IDs and names (e.g. T1110 Brute Force).\n"
    "<b>Severity Rating</b> — state exactly one of: Low, Medium, High, or Critical, with a one-line justification.\n"
    "<b>Immediate Incident Response Actions</b> — give concrete, actionable containment steps to take right now.\n\n"
    "Base every finding strictly on the data provided below. If the data is insufficient for a "
    "section, say so explicitly rather than inventing findings.\n\n"
    "LOG DATA:\n{data}"
)


async def start_log_analyzer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await safe_reply_html(
        update.message,
        "🧾 <b>AI Log Analyzer — SOC Threat Hunt</b>\n\n"
        "Paste raw log lines (SIEM, Apache, Linux auth, or firewall events) and I'll analyze them "
        "as a senior SOC threat hunter.\n\n"
        "Type /cancel to go back.",
    )
    return WAITING_LOG_DATA


async def analyze_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = update.message.text
    status_msg = await update.message.reply_text("🕵️ Hunting for threats in the log data, please wait...")

    try:
        client = get_client()
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL,
            contents=LOG_ANALYZER_PROMPT.format(data=data),
        )
        result_text = response.text
    except Exception as exc:
        logger.exception("Log analysis failed")
        await status_msg.edit_text(f"❌ Analysis failed: {exc}")
        return WAITING_LOG_DATA

    await safe_edit_html(status_msg, result_text)

    await update.message.reply_text("Paste more log data to analyze, or /cancel to go back.")
    return WAITING_LOG_DATA


async def cancel_log_analyzer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Log analyzer closed. Use /start to return to the menu.")
    return ConversationHandler.END


def get_log_analyzer_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^4 Log Analyzer$"), start_log_analyzer)],
        states={
            WAITING_LOG_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_logs)],
        },
        fallbacks=[CommandHandler("cancel", cancel_log_analyzer)],
    )
