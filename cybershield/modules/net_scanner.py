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

WAITING_SCAN_DATA = 0

# ---------------------------------------------------------------------------
# Security Engineer prompt — bash/config remediation report
# ---------------------------------------------------------------------------
SCANNER_PROMPT = (
    "You are a Security Engineer performing a professional pentest recon analysis on the "
    "scan data provided below. Your output must be a structured, actionable security report.\n\n"
    "Structure your response with EXACTLY these four sections, each headed by a <b> tag:\n\n"
    "<b>Open Port & Service Map</b>\n"
    "List every discovered port in an ASCII table inside <pre><code> tags:\n"
    "| Port | Protocol | Service | Version | Risk Level |\n"
    "Risk Level must be one of: Info, Low, Medium, High, Critical.\n\n"
    "<b>Vulnerability Assessment</b>\n"
    "List concrete vulnerabilities found. Reference CVE IDs in <i> tags where applicable. "
    "For each finding include: affected service, CVE (if known), and a one-line impact summary.\n\n"
    "<b>Attack Surface & Exploitability</b>\n"
    "Describe realistic exploitation paths an attacker could chain from the discovered surface. "
    "Include MITRE ATT&CK technique IDs in <i> tags where relevant.\n\n"
    "<b>Bash / Config Remediation Report</b>\n"
    "For every High or Critical finding, provide the exact shell command or config change that "
    "fixes it. Each command block MUST be wrapped in <pre><code>...</code></pre>. "
    "Prefix each block with a plain-text one-line description of what it does.\n\n"
    "Rules:\n"
    "• Use ONLY HTML tags compatible with Telegram: <b>, <i>, <pre><code>. No Markdown.\n"
    "• Escape literal < or > inside explanatory text as &lt; and &gt;.\n"
    "• Base every finding strictly on the data provided. State clearly if data is insufficient.\n\n"
    "SCAN DATA:\n{data}"
)

_ENTRY_MSG = (
    "🌐 <b>AI Network Scanner — Security Engineer Analysis</b>\n\n"
    "Paste an Nmap scan output, target port list, or asset/service data and I'll produce a "
    "structured security report: port map, vulnerability assessment, exploitability analysis, "
    "and exact bash/config remediation commands.\n\n"
    + NAV_FOOTER
)


async def start_scanner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await safe_reply_html(update.message, _ENTRY_MSG)
    return WAITING_SCAN_DATA


async def start_scanner_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point triggered by the 🌐 Network Scan inline button."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=_ENTRY_MSG,
        parse_mode="HTML",
    )
    return WAITING_SCAN_DATA


async def analyze_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await typing_action(context.bot, update.effective_chat.id)
    data = update.message.text
    status_msg = await update.message.reply_text(
        "🔎 Running Security Engineer pentest analysis, please wait..."
    )

    try:
        response = await generate_with_retry(
            contents=SCANNER_PROMPT.format(data=data)
        )
        result_text = response.text
    except Exception as exc:
        logger.exception("Network scan analysis failed")
        await status_msg.edit_text(
            f"❌ Analysis failed: {exc}\n\n"
            "Paste more scan data to try again, or /cancel to exit."
        )
        return WAITING_SCAN_DATA

    await send_html_report(status_msg, result_text, context.bot, update.effective_chat.id)
    await update.message.reply_text("Paste more scan data to analyze, or /cancel to go back.")
    return WAITING_SCAN_DATA


async def cancel_scanner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Network scanner closed. Use /start to return to the menu.")
    return ConversationHandler.END


def get_network_scanner_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^3 Network Scanner$"), start_scanner),
            CallbackQueryHandler(start_scanner_cb, pattern=r"^menu:scan$"),
        ],
        states={
            WAITING_SCAN_DATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_scan)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_scanner)],
        per_message=False,
    )
