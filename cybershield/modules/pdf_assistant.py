import asyncio
import json
import logging

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from modules.gemini_client import get_client, MODEL
from modules.html_utils import send_html_report

logger = logging.getLogger(__name__)

QUIZ_ANSWER, INTERVIEW_ANSWER = range(2)

PDF_TOOLS_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📚 Generate Quiz")],
        [KeyboardButton("💼 Mock Interview")],
        [KeyboardButton("🚨 Run Incident Scenario")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

# Appended to every prompt so Gemini returns Telegram-safe HTML, not Markdown.
HTML_FORMAT_RULES = (
    "Format your response using clean HTML tags compatible with Telegram's HTML parse "
    "mode. Use ONLY these tags: <b> for section headers and emphasis, <i> for italics, and "
    "<pre><code>...</code></pre> for any raw commands, logs, or technical output. Do NOT use "
    "Markdown syntax at all (no **, no *, no backtick fences). Escape any literal '<' or '>' "
    "characters that appear inside explanatory text (not part of a tag) as '&lt;' and '&gt;' "
    "so the HTML stays valid."
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_parsed_text(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """Return the text previously extracted by the Input Parsing Engine, or None."""
    return context.user_data.get("parsed_text")


async def _require_parsed_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Reply with a friendly prompt if no document/text has been parsed yet."""
    if not _get_parsed_text(context):
        await update.message.reply_text(
            "📎 Please upload a document (.pdf, .docx, .txt, or .csv) or paste your text "
            "first, then try this command again."
        )
        return False
    return True


# ---------------------------------------------------------------------------
# /quiz
# ---------------------------------------------------------------------------

QUIZ_PROMPT_TEMPLATE = (
    "You are a cybersecurity instructor. Based EXCLUSIVELY on the document content provided "
    "below, write one challenging multiple-choice technical cybersecurity question that tests "
    "understanding of its content.\n\n"
    "Respond ONLY with JSON in this exact shape:\n"
    '{"question": "...", "options": {"A": "...", "B": "...", "C": "...", "D": "..."}, '
    '"correct_option": "A", "explanation": "..."}\n\n'
    "The \"question\" and \"options\" values MUST be plain text only (no HTML tags, no "
    "Markdown). The \"explanation\" value may use simple HTML tags for readability — ONLY "
    "<b>, <i>, and <pre><code>...</code></pre> — never Markdown syntax (no **, no *, no "
    "backtick fences). Escape any literal '<' or '>' inside plain text as '&lt;' and '&gt;'.\n\n"
    "Document content:\n\n{text}"
)


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _require_parsed_text(update, context):
        return ConversationHandler.END

    parsed_text = _get_parsed_text(context)
    status_msg = await update.message.reply_text("🧠 Generating a quiz question from your document...")

    try:
        client = get_client()
        prompt = QUIZ_PROMPT_TEMPLATE.format(text=parsed_text)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL,
            contents=[prompt],
            config={"response_mime_type": "application/json"},
        )
        data = json.loads(response.text)
    except Exception as exc:
        logger.exception("Quiz generation failed")
        context.user_data.pop("quiz_pending", None)
        await status_msg.edit_text(f"❌ Couldn't generate a quiz question: {exc}")
        return ConversationHandler.END

    context.user_data["quiz_pending"] = data

    options_text = "\n".join(f"{k}. {v}" for k, v in data["options"].items())
    quiz_text = (
        f"❓ <b>Quiz Question</b>\n\n{data['question']}\n\n{options_text}\n\n"
        "Reply with the letter of your answer (A, B, C, or D)."
    )
    await send_html_report(status_msg, quiz_text, context.bot, update.effective_chat.id)
    return QUIZ_ANSWER


async def quiz_evaluate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pending = context.user_data.get("quiz_pending")
    if not pending:
        return ConversationHandler.END

    status_msg = await update.message.reply_text("📊 Grading your answer...")

    try:
        user_answer = update.message.text.strip().upper()[:1]
        correct = pending["correct_option"].strip().upper()
        is_correct = user_answer == correct

        result_line = "✅ Correct!" if is_correct else f"❌ Not quite — the correct answer was {correct}."
        result_text = (
            f"{result_line}\n\n<b>Explanation:</b>\n{pending['explanation']}\n\n"
            "Use /quiz for another question."
        )
        await send_html_report(status_msg, result_text, context.bot, update.effective_chat.id)
    except Exception as exc:
        logger.exception("Quiz evaluation failed")
        await status_msg.edit_text(f"❌ Couldn't grade your answer: {exc}")
    finally:
        context.user_data.pop("quiz_pending", None)

    return ConversationHandler.END


async def quiz_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("quiz_pending", None)
    await update.message.reply_text("Quiz cancelled. Use /start to return to the menu.")
    return ConversationHandler.END


def get_quiz_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("quiz", quiz_command),
            MessageHandler(filters.Regex("^📚 Generate Quiz$"), quiz_command),
        ],
        states={QUIZ_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, quiz_evaluate)]},
        fallbacks=[CommandHandler("cancel", quiz_cancel)],
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
    '{"question": "...", "key_points": ["...", "..."]}\n\n'
    "All values MUST be plain text only (no HTML tags, no Markdown).\n\n"
    "Document content:\n\n{text}"
)


async def interview_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _require_parsed_text(update, context):
        return ConversationHandler.END

    parsed_text = _get_parsed_text(context)
    status_msg = await update.message.reply_text("🎤 Preparing a mock interview question from your document...")

    try:
        client = get_client()
        prompt = INTERVIEW_PROMPT_TEMPLATE.format(text=parsed_text)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL,
            contents=[prompt],
            config={"response_mime_type": "application/json"},
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
    )
    await send_html_report(status_msg, question_text, context.bot, update.effective_chat.id)
    return INTERVIEW_ANSWER


async def interview_evaluate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pending = context.user_data.get("interview_pending")
    if not pending:
        return ConversationHandler.END

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
        client = get_client()
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL,
            contents=[eval_prompt],
        )
        feedback_text = f"📝 <b>Feedback</b>\n\n{response.text}\n\nUse /interview for another question."
        await send_html_report(status_msg, feedback_text, context.bot, update.effective_chat.id)
    except Exception as exc:
        logger.exception("Interview evaluation failed")
        await status_msg.edit_text(f"❌ Couldn't evaluate your answer: {exc}")
    finally:
        context.user_data.pop("interview_pending", None)

    return ConversationHandler.END


async def interview_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("interview_pending", None)
    await update.message.reply_text("Interview practice cancelled. Use /start to return to the menu.")
    return ConversationHandler.END


def get_interview_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("interview", interview_command),
            MessageHandler(filters.Regex("^💼 Mock Interview$"), interview_command),
        ],
        states={INTERVIEW_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, interview_evaluate)]},
        fallbacks=[CommandHandler("cancel", interview_cancel)],
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

    parsed_text = _get_parsed_text(context)
    status_msg = await update.message.reply_text("🧪 Building an incident response scenario from your document...")

    try:
        client = get_client()
        prompt = SCENARIO_PROMPT_TEMPLATE.format(text=parsed_text)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL,
            contents=[prompt],
        )
        scenario_text = f"🧪 <b>Incident Response Scenario</b>\n\n{response.text}"
        await send_html_report(status_msg, scenario_text, context.bot, update.effective_chat.id)
    except Exception as exc:
        logger.exception("Scenario generation failed")
        context.user_data.pop("quiz_pending", None)
        context.user_data.pop("interview_pending", None)
        await status_msg.edit_text(f"❌ Couldn't generate a scenario: {exc}")
