from telegram import Update
from telegram.ext import ContextTypes

async def network_scanner_locked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔒 *Module 3: Network Port Scanner — LOCKED*\n\n"
        "This module will allow you to scan IP addresses and check for open ports.\n\n"
        "📚 *Unlock requirements:*\n"
        "• Complete the *Networking Fundamentals* module\n"
        "• Learn Python socket programming\n"
        "• Study the Nmap tool basics\n\n"
        "Come back when you've completed those topics — you'll write the scanner yourself!\n\n"
        "Use /start to return to the main menu.",
        parse_mode="Markdown"
    )

async def log_analysis_locked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔒 *Module 4: Log Analysis Tool — LOCKED*\n\n"
        "This module will parse system and application logs to detect suspicious activity "
        "such as failed logins, port scans, and unusual traffic patterns.\n\n"
        "📚 *Unlock requirements:*\n"
        "• Complete the *SIEM & Log Management* module\n"
        "• Learn regex-based pattern matching in Python\n"
        "• Study common log formats (syslog, Apache, Windows Event)\n\n"
        "Come back when you're ready — log analysis is a core skill for any SOC analyst!\n\n"
        "Use /start to return to the main menu.",
        parse_mode="Markdown"
    )
