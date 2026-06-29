import re
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters

WAITING_PASSWORD = 0

def analyze_password(password: str) -> dict:
    score = 0
    feedback = []
    strength = ""

    length = len(password)
    has_upper = bool(re.search(r"[A-Z]", password))
    has_lower = bool(re.search(r"[a-z]", password))
    has_digit = bool(re.search(r"\d", password))
    has_special = bool(re.search(r"[!@#$%^&*(),.?\":{}|<>\-_=+\[\]\\;'/`~]", password))
    has_space = " " in password

    # Length scoring
    if length >= 16:
        score += 30
    elif length >= 12:
        score += 20
    elif length >= 8:
        score += 10
    else:
        feedback.append("❌ Too short — use at least 8 characters (12+ recommended)")

    # Composition scoring
    if has_upper:
        score += 15
    else:
        feedback.append("❌ Add uppercase letters (A-Z)")

    if has_lower:
        score += 15
    else:
        feedback.append("❌ Add lowercase letters (a-z)")

    if has_digit:
        score += 15
    else:
        feedback.append("❌ Add numbers (0-9)")

    if has_special:
        score += 20
    else:
        feedback.append("❌ Add special characters (!, @, #, $, etc.)")

    if has_space:
        feedback.append("⚠️ Spaces detected — some systems may not accept them")

    # Bonus checks
    common_patterns = [
        r"123", r"abc", r"qwerty", r"password", r"admin", r"letmein",
        r"welcome", r"monkey", r"iloveyou", r"sunshine"
    ]
    for pattern in common_patterns:
        if re.search(pattern, password, re.IGNORECASE):
            score = max(0, score - 20)
            feedback.append("⚠️ Avoid common words or sequences (e.g. 'password', '123', 'qwerty')")
            break

    # Determine strength label
    if score >= 80:
        strength = "💚 Very Strong"
    elif score >= 60:
        strength = "🟢 Strong"
    elif score >= 40:
        strength = "🟡 Medium"
    elif score >= 20:
        strength = "🟠 Weak"
    else:
        strength = "🔴 Very Weak"

    return {
        "score": min(score, 100),
        "strength": strength,
        "feedback": feedback,
        "length": length,
        "has_upper": has_upper,
        "has_lower": has_lower,
        "has_digit": has_digit,
        "has_special": has_special,
    }

async def start_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🔑 *Password Strength Analyzer*\n\n"
        "Send me a password and I will analyze its strength.\n\n"
        "⚠️ _For testing only — never share real passwords in chats._\n\n"
        "Type /cancel to go back.",
        parse_mode="Markdown"
    )
    return WAITING_PASSWORD

async def check_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    password = update.message.text

    result = analyze_password(password)
    score = result["score"]
    strength = result["strength"]
    length = result["length"]
    feedback = result["feedback"]

    bar_filled = int(score / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)

    composition = (
        f"{'✅' if result['has_upper'] else '❌'} Uppercase  "
        f"{'✅' if result['has_lower'] else '❌'} Lowercase\n"
        f"{'✅' if result['has_digit'] else '❌'} Numbers   "
        f"{'✅' if result['has_special'] else '❌'} Special chars"
    )

    feedback_text = "\n".join(feedback) if feedback else "✅ No major issues found!"

    report = (
        f"🔍 *Password Analysis Report*\n\n"
        f"*Strength:* {strength}\n"
        f"*Score:* {score}/100\n"
        f"`[{bar}]`\n\n"
        f"*Length:* {length} characters\n\n"
        f"*Composition:*\n{composition}\n\n"
        f"*Feedback:*\n{feedback_text}\n\n"
        f"Send another password to test, or use /cancel to go back."
    )

    await update.message.reply_text(report, parse_mode="Markdown")
    return WAITING_PASSWORD

async def cancel_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Password checker closed. Use /start to return to the menu."
    )
    return ConversationHandler.END

def get_password_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^2️⃣ Password Analyzer$"), start_password)],
        states={
            WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel_password)],
    )
