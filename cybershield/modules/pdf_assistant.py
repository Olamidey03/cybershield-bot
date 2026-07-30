import json
import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from modules.gemini_client import generate_with_retry
from modules.html_utils import send_html_report, typing_action, NAV_FOOTER

logger = logging.getLogger(__name__)

# Only INTERVIEW_ANSWER is still needed — quiz no longer waits for a text reply.
INTERVIEW_ANSWER = 0

PDF_TOOLS_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📚 Generate Quiz")],
        [KeyboardButton("💼 Mock Interview")],
        [KeyboardButton("🚨 Run Incident Scenario")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

HTML_FORMAT_RULES = (
    "Format your response using clean HTML tags compatible with Telegram's HTML parse "
    "mode. Use ONLY these tags: <b> for section headers and emphasis, <i> for italics, and "
    "<pre><code>...</code></pre> for any raw commands, logs, or technical output. Do NOT use "
    "Markdown syntax at all (no **, no *, no backtick fences). Escape any literal '<' or '>' "
    "characters that appear inside explanatory text (not part of a tag) as '&lt;' and '&gt;' "
    "so the HTML stays valid."
)

_DIFFICULTY_LABELS = {
    "beginner": "Beginner 🟢",
    "intermediate": "Intermediate 🟡",
    "advanced": "Advanced 🔴",
}

_DIFFICULTY_INSTRUCTIONS = {
    "beginner": (
        "The question should be suitable for a beginner: use clear language, avoid deep "
        "technical jargon, and test foundational understanding only."
    ),
    "intermediate": (
        "The question should be at an intermediate level: assume working knowledge of "
        "cybersecurity fundamentals and test applied understanding."
    ),
    "advanced": (
        "The question should be advanced and technical: assume expert-level knowledge and "
        "test deep, nuanced understanding or complex scenario analysis."
    ),
}

# Hint inline keyboard — tapping shows the hint as a screen alert popup.
_HINT_KB = InlineKeyboardMarkup(
    [[InlineKeyboardButton("💡 Need a Hint?", callback_data="quiz:hint")]]
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_parsed_text(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    return context.user_data.get("parsed_text")


async def _require_parsed_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Works for both Message and CallbackQuery updates."""
    if not _get_parsed_text(context):
        msg = (
            "📎 Please upload a document (.pdf, .docx, .txt, or .csv) or paste your text "
            "first, then try this command again.\n\n"
            + NAV_FOOTER
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return False
    return True


# ---------------------------------------------------------------------------
# /quiz — native Telegram poll with hint popup (Step 5)
# ---------------------------------------------------------------------------

# Character budget enforced in the prompt so output fits Telegram's poll limits:
#   question  < 250 chars  (Telegram hard limit: 300)
#   each option < 90 chars  (Telegram hard limit: 100)
#   explanation < 180 chars  (Telegram hard limit: 200)
#   hint < 150 chars  (fits comfortably in a show_alert popup)
QUIZ_PROMPT_TEMPLATE = (
    "You are a cybersecurity instructor. Based EXCLUSIVELY on the document content provided "
    "below, generate ONE multiple-choice cybersecurity quiz question.\n\n"
    "{difficulty_instruction}\n\n"
    "STRICT CHARACTER LIMITS — you MUST respect these or your output will be rejected:\n"
    "  • question   < 250 characters (plain text, no HTML/Markdown)\n"
    "  • each option < 90 characters (plain text, no HTML/Markdown)\n"
    "  • explanation < 180 characters (plain text only — this appears as a Telegram popup)\n"
    "  • hint       < 150 characters (plain text — shown on demand, must NOT reveal the answer)\n\n"
    "Respond ONLY with valid JSON in this exact shape — no extra keys, no markdown fences:\n"
    '{{"question":"...","options":{{"A":"...","B":"...","C":"...","D":"..."}},'
    '"correct_option":"A","explanation":"...","hint":"..."}}\n\n'
    "Document content:\n\n{text}"
)


async def _run_quiz(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    status_msg,
) -> int:
    """Core quiz generation shared by message and callback entry points.

    Sends a native Telegram quiz poll (Telegram handles A/B/C/D selection and
    explanation popup automatically) plus a 'Need a Hint?' inline button.
    Returns ConversationHandler.END — no text reply needed from the user.
    """
    if not await _require_parsed_text(update, context):
        return ConversationHandler.END

    parsed_text = _get_parsed_text(context)
    difficulty = context.user_data.get("quiz_difficulty", "intermediate")
    difficulty_label = _DIFFICULTY_LABELS.get(difficulty, "Intermediate 🟡")
    difficulty_instr = _DIFFICULTY_INSTRUCTIONS.get(
        difficulty, _DIFFICULTY_INSTRUCTIONS["intermediate"]
    )

    try:
        prompt = QUIZ_PROMPT_TEMPLATE.format(
            difficulty_instruction=difficulty_instr,
            text=parsed_text,
        )
        response = await generate_with_retry(
            contents=[prompt],
            response_mime_type="application/json",
        )
        data = json.loads(response.text)
    except Exception as exc:
        logger.exception("Quiz generation failed")
        context.user_data.pop("quiz_pending", None)
        try:
            await status_msg.edit_text(
                f"❌ Couldn't generate a quiz question: {exc}\n\n{NAV_FOOTER}",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return ConversationHandler.END

    # --- Safety truncation (Telegram hard limits) ---
    question_raw = str(data.get("question", ""))[:300]
    options_raw = data.get("options", {})
    options_list = [
        str(options_raw.get("A", "Option A"))[:100],
        str(options_raw.get("B", "Option B"))[:100],
        str(options_raw.get("C", "Option C"))[:100],
        str(options_raw.get("D", "Option D"))[:100],
    ]
    correct_letter = str(data.get("correct_option", "A")).strip().upper()[:1]
    correct_idx = {"A": 0, "B": 1, "C": 2, "D": 3}.get(correct_letter, 0)
    explanation = str(data.get("explanation", ""))[:200]
    hint = str(data.get("hint", "No hint available for this question."))[:200]

    # Store hint for the callback handler.
    context.user_data["quiz_hint"] = hint

    # Prefix the question with the difficulty label (stays under 300 chars).
    poll_question = f"[{difficulty_label}] {question_raw}"[:300]

    # Remove the "Generating…" status message before sending the poll.
    try:
        await status_msg.delete()
    except Exception:
        pass

    # --- Send native Telegram quiz poll ---
    await context.bot.send_poll(
        chat_id=chat_id,
        question=poll_question,
        options=options_list,
        type="quiz",
        correct_option_id=correct_idx,
        explanation=explanation,
        is_anonymous=False,
    )

    # --- Send hint button below the poll ---
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "<i>Tap 💡 for a hint · /quiz to generate another question</i>"
            + NAV_FOOTER
        ),
        parse_mode="HTML",
        reply_markup=_HINT_KB,
    )

    return ConversationHandler.END


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry via /quiz text command or keyboard button."""
    if not await _require_parsed_text(update, context):
        return ConversationHandler.END
    await typing_action(context.bot, update.effective_chat.id)
    context.user_data.setdefault("quiz_difficulty", "intermediate")
    status_msg = await update.message.reply_text(
        "🧠 Generating a quiz question from your document..."
    )
    return await _run_quiz(update, context, update.effective_chat.id, status_msg)


async def quiz_difficulty_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry via Beginner / Intermediate / Advanced inline buttons."""
    query = update.callback_query
    difficulty = query.data.split(":")[1]
    context.user_data["quiz_difficulty"] = difficulty

    if not await _require_parsed_text(update, context):
        return ConversationHandler.END

    await query.answer(f"Difficulty set to {_DIFFICULTY_LABELS.get(difficulty, difficulty)}")
    await typing_action(context.bot, update.effective_chat.id)

    status_msg = await query.edit_message_text(
        f"🧠 Generating a <b>{_DIFFICULTY_LABELS[difficulty]}</b> quiz question...",
        parse_mode="HTML",
    )
    return await _run_quiz(update, context, update.effective_chat.id, status_msg)


async def quiz_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("quiz_hint", None)
    await update.message.reply_text("Quiz cancelled. Use /start to return to the menu.")
    return ConversationHandler.END


def get_quiz_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("quiz", quiz_command),
            MessageHandler(filters.Regex("^📚 Generate Quiz$"), quiz_command),
            CallbackQueryHandler(
                quiz_difficulty_cb,
                pattern=r"^quiz:(beginner|intermediate|advanced)$",
            ),
        ],
        states={},  # Poll flow ends immediately; no text-reply state needed.
        fallbacks=[CommandHandler("cancel", quiz_cancel)],
        per_message=False,
    )


# ---------------------------------------------------------------------------
# /interview
# ---------------------------------------------------------------------------

INTERVIEW_PROMPT_TEMPLATE = (
    "You are a senior Security Engineer hiring manager conducting a technical mock interview. "
    "Based EXCLUSIVELY on the document content provided below, ask ONE realistic technical "
    "interview question that a Security Engineer candidate should be able to answer, grounded "
    "in the document's content.\n\n"
    "Respond ONLY with JSON in this exact shape:\n"
    '{{"question": "...", "key_points": ["...", "..."]}}\n\n'
    "All values MUST be plain text only (no HTML tags, no Markdown).\n\n"
    "Document content:\n\n{text}"
)


async def interview_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _require_parsed_text(update, context):
        return ConversationHandler.END
    await typing_action(context.bot, update.effective_chat.id)
    parsed_text = _get_parsed_text(context)
    status_msg = await update.message.reply_text(
        "🎤 Preparing a mock interview question from your document..."
    )

    try:
        prompt = INTERVIEW_PROMPT_TEMPLATE.format(text=parsed_text)
        response = await generate_with_retry(
            contents=[prompt],
            response_mime_type="application/json",
        )
        data = json.loads(response.text)
    except Exception as exc:
        logger.exception("Interview generation failed")
        context.user_data.pop("interview_pending", None)
        await status_msg.edit_text(f"❌ Couldn't generate an interview question: {exc}")
        return ConversationHandler.END

    context.user_data["interview_pending"] = data

    question_text = (
        f"🎤 <b>Mock Interview Question</b>\n\n{data['question']}\n\n"
        "Reply with your answer when ready."
        + NAV_FOOTER
    )
    await send_html_report(status_msg, question_text, context.bot, update.effective_chat.id)
    return INTERVIEW_ANSWER


async def interview_evaluate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pending = context.user_data.get("interview_pending")
    if not pending:
        return ConversationHandler.END

    await typing_action(context.bot, update.effective_chat.id)
    status_msg = await update.message.reply_text("🧠 Evaluating your answer...")

    user_answer = update.message.text
    parsed_text = _get_parsed_text(context)

    eval_prompt = (
        "You are a senior Security Engineer hiring manager. The candidate was asked:\n"
        f"\"{pending['question']}\"\n\n"
        f"Key points a strong answer should cover: {pending['key_points']}\n\n"
        f"Candidate's answer: \"{user_answer}\"\n\n"
        "Using the document content below as ground truth, give constructive feedback: what they "
        "got right, what they missed, and a brief improvement tip. End with a score out of 10. "
        f"Keep it concise (under 150 words).\n\n{HTML_FORMAT_RULES}\n\n"
        f"Document content:\n\n{parsed_text}"
    )

    try:
        response = await generate_with_retry(contents=[eval_prompt])
        feedback_text = (
            f"📝 <b>Feedback</b>\n\n{response.text}\n\nUse /interview for another question."
        )
        await send_html_report(
            status_msg, feedback_text, context.bot, update.effective_chat.id
        )
    except Exception as exc:
        logger.exception("Interview evaluation failed")
        await status_msg.edit_text(f"❌ Couldn't evaluate your answer: {exc}")
    finally:
        context.user_data.pop("interview_pending", None)

    return ConversationHandler.END


async def interview_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("interview_pending", None)
    await update.message.reply_text(
        "Interview practice cancelled. Use /start to return to the menu."
    )
    return ConversationHandler.END


def get_interview_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("interview", interview_command),
            MessageHandler(filters.Regex("^💼 Mock Interview$"), interview_command),
        ],
        states={
            INTERVIEW_ANSWER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, interview_evaluate)
            ]
        },
        fallbacks=[CommandHandler("cancel", interview_cancel)],
        per_message=False,
    )


# ---------------------------------------------------------------------------
# /scenario
# ---------------------------------------------------------------------------

SCENARIO_PROMPT_TEMPLATE = (
    "You are a cybersecurity training designer. Based EXCLUSIVELY on the document content "
    "provided below, create an interactive, hands-on incident response scenario or lab exercise. "
    "Include: a realistic scenario setup, the systems/assets involved, a numbered sequence of "
    "investigation steps the trainee should take, and 2-3 decision points where the trainee "
    "must choose an action. Ground every detail in the document's content. Structure the "
    f"response with clear <b>section headers</b>.\n\n{HTML_FORMAT_RULES}\n\n"
    "Document content:\n\n{text}"
)


async def scenario_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_parsed_text(update, context):
        return
    await typing_action(context.bot, update.effective_chat.id)
    parsed_text = _get_parsed_text(context)
    status_msg = await update.message.reply_text(
        "🧪 Building an incident response scenario from your document..."
    )

    try:
        prompt = SCENARIO_PROMPT_TEMPLATE.format(text=parsed_text)
        response = await generate_with_retry(contents=[prompt])
        scenario_text = f"🧪 <b>Incident Response Scenario</b>\n\n{response.text}"
        await send_html_report(
            status_msg, scenario_text, context.bot, update.effective_chat.id
        )
    except Exception as exc:
        logger.exception("Scenario generation failed")
        context.user_data.pop("quiz_pending", None)
        context.user_data.pop("interview_pending", None)
        await status_msg.edit_text(f"❌ Couldn't generate a scenario: {exc}")
