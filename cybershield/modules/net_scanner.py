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

logger = logging.getLogger(__name__)

WAITING_SCAN_DATA = 0

SCANNER_PROMPT = (
    "You are an expert Penetration Tester performing recon analysis. Analyze the following "
    "Nmap scan output, target port list, or asset/service data. Respond using EXACTLY these "
    "four section headers, in this order, formatted in Markdown bold:\n\n"
    "*Vulnerability Assessment* — list concrete vulnerabilities found, referencing CVE IDs where applicable.\n"
    "*Attack Surface Exposure* — summarize exposed services, ports, and versions that widen the attack surface.\n"
    "*Exploitability Vectors* — describe realistic exploitation paths an attacker could use.\n"
    "*Technical Remediation & Patching Guide* — give concrete, actionable remediation and patching steps.\n\n"
    "Base every finding strictly on the data provided below. If the data is insufficient for a "
    "section, say so explicitly rather than inventing findings.\n\n"
    "DATA:\n{data}"
)


async def start_scanner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🌐 *AI Network Scanner — Pentest Analysis*\n\n"
        "Paste an Nmap scan output, target port list, or asset/service data and I'll analyze it "
        "as an expert penetration tester.\n\n"
        "Type /cancel to go back.",
        parse_mode="Markdown",
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

    try:
        await status_msg.edit_text(result_text, parse_mode="Markdown")
    except Exception:
        await status_msg.edit_text(result_text)

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
