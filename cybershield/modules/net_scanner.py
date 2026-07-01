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
from modules.html_utils import safe_reply_html, send_html_report

logger = logging.getLogger(__name__)

WAITING_SCAN_DATA = 0

SCANNER_PROMPT = (
    "You are an expert Penetration Tester performing recon analysis. Analyze the following "
    "Nmap scan output, target port list, or asset/service data.\n\n"
    "Format your ENTIRE response using clean HTML tags compatible with Telegram's HTML parse "
    "mode. Use ONLY these tags: <b> for section headers and emphasis, <i> for italics, and "
    "<pre><code>...</code></pre> for any raw commands, ports, or technical output. Do NOT use "
    "Markdown syntax at all (no **, no *, no backtick fences). Escape any literal '<' or '>' "
    "characters that appear inside your own explanatory text (not part of a tag) as '&lt;' and "
    "'&gt;' so the HTML stays valid.\n\n"
    "Structure the response with EXACTLY these four section headers, each wrapped in <b> tags, "
    "in this order:\n\n"
    "<b>Vulnerability Assessment</b> — list concrete vulnerabilities found, referencing CVE IDs where applicable.\n"
    "<b>Attack Surface Exposure</b> — summarize exposed services, ports, and versions that widen the attack surface.\n"
    "<b>Exploitability Vectors</b> — describe realistic exploitation paths an attacker could use.\n"
    "<b>Technical Remediation &amp; Patching Guide</b> — give concrete, actionable remediation and patching steps.\n\n"
    "Base every finding strictly on the data provided below. If the data is insufficient for a "
    "section, say so explicitly rather than inventing findings.\n\n"
    "DATA:\n{data}"
)


async def start_scanner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await safe_reply_html(
        update.message,
        "🌐 <b>AI Network Scanner — Pentest Analysis</b>\n\n"
        "Paste an Nmap scan output, target port list, or asset/service data and I'll analyze it "
        "as an expert penetration tester.\n\n"
        "Type /cancel to go back.",
    )
    return WAITING_SCAN_DATA


async def analyze_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = update.message.text
    status_msg = await update.message.reply_text("🔎 Analyzing scan data as a pentester, please wait...")

    try:
        client = get_client()
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL,
            contents=SCANNER_PROMPT.format(data=data),
        )
        result_text = response.text
    except Exception as exc:
        logger.exception("Network scan analysis failed")
        await status_msg.edit_text(f"❌ Analysis failed: {exc}")
        return WAITING_SCAN_DATA

    await send_html_report(status_msg, result_text, context.bot, update.effective_chat.id)

    await update.message.reply_text("Paste more scan data to analyze, or /cancel to go back.")
    return WAITING_SCAN_DATA


async def cancel_scanner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Network scanner closed. Use /start to return to the menu.")
    return ConversationHandler.END


def get_network_scanner_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^3 Network Scanner$"), start_scanner)],
        states={
            WAITING_SCAN_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_scan)],
        },
        fallbacks=[CommandHandler("cancel", cancel_scanner)],
    )
