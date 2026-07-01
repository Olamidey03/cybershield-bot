import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters

logger = logging.getLogger(__name__)

QUESTION_INDEX = 0
SCORE = 1

QUESTIONS = [
    ("Is a firewall enabled on all systems?", 15),
    ("Are operating systems and software regularly patched/updated?", 15),
    ("Is Multi-Factor Authentication (MFA) enforced?", 15),
    ("Are user access privileges limited to least-privilege?", 10),
    ("Is sensitive data encrypted at rest and in transit?", 10),
    ("Are regular data backups performed and tested?", 10),
    ("Is there an incident response plan in place?", 10),
    ("Are employees trained on cybersecurity awareness?", 10),
    ("Is network traffic monitored for anomalies?", 5),
]

RISK_INTRO = (
    "🛡️ *Risk Assessment Tool*\n\n"
    "I will ask you {total} questions based on cybersecurity best practices.\n"
    "Answer *yes* or *no* to each.\n\n"
    "Type /cancel at any time to stop.\n\n"
    "Let's begin!\n\n"
)

async def start_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["risk_score"] = 0
    context.user_data["risk_index"] = 0
    total = len(QUESTIONS)
    await update.message.reply_text(
        RISK_INTRO.format(total=total),
        parse_mode="Markdown"
    )
    await _ask_question(update, context)
    return QUESTION_INDEX

async def _ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data["risk_index"]
    question, _ = QUESTIONS[idx]
    total = len(QUESTIONS)
    await update.message.reply_text(
        f"*Q{idx + 1}/{total}:* {question}",
        parse_mode="Markdown"
    )

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        answer = update.message.text.strip().lower()
        if answer not in ("yes", "no"):
            await update.message.reply_text("Please reply with *yes* or *no*.", parse_mode="Markdown")
            return QUESTION_INDEX

        idx = context.user_data["risk_index"]
        _, points = QUESTIONS[idx]

        if answer == "no":
            context.user_data["risk_score"] += points

        context.user_data["risk_index"] += 1

        if context.user_data["risk_index"] >= len(QUESTIONS):
            return await _show_result(update, context)

        await _ask_question(update, context)
        return QUESTION_INDEX
    except Exception:
        logger.exception("Risk assessment handler failed")
        context.user_data.pop("risk_score", None)
        context.user_data.pop("risk_index", None)
        await update.message.reply_text(
            "❌ Something went wrong with the assessment. It's been reset — use /start to try again."
        )
        return ConversationHandler.END

async def _show_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    score = context.user_data["risk_score"]
    max_score = sum(p for _, p in QUESTIONS)

    if score >= 60:
        level = "🔴 HIGH RISK"
        advice = (
            "Your environment has significant security gaps.\n"
            "Priority actions:\n"
            "• Enable firewalls and MFA immediately\n"
            "• Apply all pending patches\n"
            "• Review user access privileges\n"
            "• Establish an incident response plan"
        )
    elif score >= 30:
        level = "🟡 MEDIUM RISK"
        advice = (
            "Some controls are in place but gaps remain.\n"
            "Recommended actions:\n"
            "• Address the 'no' answers from this assessment\n"
            "• Strengthen employee training\n"
            "• Review backup and recovery procedures"
        )
    else:
        level = "🟢 LOW RISK"
        advice = (
            "Your security posture is strong. Keep it up!\n"
            "Ongoing recommendations:\n"
            "• Continue regular patching and monitoring\n"
            "• Review your incident response plan periodically\n"
            "• Stay current on emerging threats"
        )

    result_text = (
        f"✅ *Assessment Complete!*\n\n"
        f"*Risk Score:* {score}/{max_score}\n"
        f"*Status:* {level}\n\n"
        f"{advice}\n\n"
        f"Use /start to return to the main menu."
    )
    await update.message.reply_text(result_text, parse_mode="Markdown")
    return ConversationHandler.END

async def cancel_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Risk assessment cancelled. Use /start to return to the menu.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

def get_risk_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^1 Risk Assessment$"), start_risk)],
        states={
            QUESTION_INDEX: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer)],
        },
        fallbacks=[CommandHandler("cancel", cancel_risk)],
    )
