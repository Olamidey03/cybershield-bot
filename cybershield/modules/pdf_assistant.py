import os
import json
import asyncio
import tempfile
import logging

from google.genai import types

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from modules.gemini_client import get_client, MODEL

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


def _state_name(state) -> str:
    return getattr(state, "name", str(state))


async def _reply(message, text: str):
    """Send text, falling back to plain text if Markdown parsing fails
    (LLM output can contain characters that break Telegram's Markdown parser)."""
    try:
        await message.reply_text(text, parse_mode="Markdown")
    except Exception:
        await message.reply_text(text)


def _get_active_file_part(context: ContextTypes.DEFAULT_TYPE):
    active = context.user_data.get("active_pdf")
    if not active:
        return None
    return types.Part.from_uri(file_uri=active["uri"], mime_type=active["mime_type"])


async def _require_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not context.user_data.get("active_pdf"):
        await update.message.reply_text(
            "📎 Please upload a PDF document first, then try this command again."
        )
        return False
    return True


# ---------------------------------------------------------------------------
# PDF upload handler
# ---------------------------------------------------------------------------

async def handle_pdf_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document:
        return

    is_pdf = (document.mime_type == "application/pdf") or (
        document.file_name and document.file_name.lower().endswith(".pdf")
    )
    if not is_pdf:
        await update.message.reply_text("📎 I can only process PDF documents right now.")
        return

    status_msg = await update.message.reply_text("📄 Uploading document, please wait...")

    tmp_path = None
    try:
        tg_file = await context.bot.get_file(document.file_id)
        fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        await tg_file.download_to_drive(tmp_path)

        client = get_client()
        display_name = document.file_name or "document.pdf"

        uploaded = await asyncio.to_thread(
            client.files.upload,
            file=tmp_path,
            config={"display_name": display_name, "mime_type": "application/pdf"},
        )

        # Gemini processes uploaded files asynchronously — poll until ACTIVE.
        for _ in range(15):
            if _state_name(uploaded.state) == "ACTIVE":
                break
            if _state_name(uploaded.state) == "FAILED":
                raise RuntimeError("Gemini failed to process the document.")
            await asyncio.sleep(2)
            uploaded = await asyncio.to_thread(client.files.get, name=uploaded.name)

        context.user_data["active_pdf"] = {
            "uri": uploaded.uri,
            "name": uploaded.name,
            "mime_type": uploaded.mime_type or "application/pdf",
            "display_name": display_name,
        }
        # A new document invalidates any pending quiz/interview state.
        context.user_data.pop("quiz_pending", None)
        context.user_data.pop("interview_pending", None)

        await status_msg.edit_text(
            f"✅ \"{display_name}\" uploaded and ready!\n\n"
            "Use the buttons below, or the /quiz, /interview, /scenario commands."
        )
        await update.message.reply_text(
            "Choose what you'd like to do with this document:",
            reply_markup=PDF_TOOLS_KEYBOARD,
        )
    except Exception as exc:
        logger.exception("PDF upload failed")
        await status_msg.edit_text(f"❌ Failed to process document: {exc}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


# ---------------------------------------------------------------------------
# /quiz
# ---------------------------------------------------------------------------

QUIZ_PROMPT = (
    "You are a cybersecurity instructor. Based EXCLUSIVELY on the attached document, "
    "write one challenging multiple-choice technical cybersecurity question that tests "
    "understanding of its content. Respond ONLY with JSON in this exact shape:\n"
    '{"question": "...", "options": {"A": "...", "B": "...", "C": "...", "D": "..."}, '
    '"correct_option": "A", "explanation": "..."}'
)

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _require_pdf(update, context):
        return ConversationHandler.END

    await update.message.reply_text("🧠 Generating a quiz question from your document...")
    file_part = _get_active_file_part(context)

    try:
        client = get_client()
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL,
            contents=[file_part, QUIZ_PROMPT],
            config={"response_mime_type": "application/json"},
        )
        data = json.loads(response.text)
    except Exception as exc:
        logger.exception("Quiz generation failed")
        await update.message.reply_text(f"❌ Couldn't generate a quiz question: {exc}")
        return ConversationHandler.END

    context.user_data["quiz_pending"] = data

    options_text = "\n".join(f"{k}. {v}" for k, v in data["options"].items())
    await _reply(
        update.message,
        f"❓ Quiz Question\n\n{data['question']}\n\n{options_text}\n\n"
        "Reply with the letter of your answer (A, B, C, or D).",
    )
    return QUIZ_ANSWER


async def quiz_evaluate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pending = context.user_data.get("quiz_pending")
    if not pending:
        return ConversationHandler.END

    user_answer = update.message.text.strip().upper()[:1]
    correct = pending["correct_option"].strip().upper()
    is_correct = user_answer == correct

    result_line = "✅ Correct!" if is_correct else f"❌ Not quite — the correct answer was {correct}."
    await _reply(
        update.message,
        f"{result_line}\n\nExplanation:\n{pending['explanation']}\n\nUse /quiz for another question.",
    )
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

INTERVIEW_PROMPT = (
    "You are a senior Security Engineer hiring manager conducting a technical mock interview. "
    "Based EXCLUSIVELY on the attached document, ask ONE realistic technical interview question "
    "that a Security Engineer candidate should be able to answer, grounded in the document's content. "
    "Respond ONLY with JSON in this exact shape:\n"
    '{"question": "...", "key_points": ["...", "..."]}'
)

async def interview_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _require_pdf(update, context):
        return ConversationHandler.END

    await update.message.reply_text("🎤 Preparing a mock interview question from your document...")
    file_part = _get_active_file_part(context)

    try:
        client = get_client()
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL,
            contents=[file_part, INTERVIEW_PROMPT],
            config={"response_mime_type": "application/json"},
        )
        data = json.loads(response.text)
    except Exception as exc:
        logger.exception("Interview generation failed")
        await update.message.reply_text(f"❌ Couldn't generate an interview question: {exc}")
        return ConversationHandler.END

    context.user_data["interview_pending"] = data

    await _reply(
        update.message,
        f"🎤 Mock Interview Question\n\n{data['question']}\n\nReply with your answer when ready.",
    )
    return INTERVIEW_ANSWER


async def interview_evaluate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pending = context.user_data.get("interview_pending")
    if not pending:
        return ConversationHandler.END

    user_answer = update.message.text
    file_part = _get_active_file_part(context)

    eval_prompt = (
        "You are a senior Security Engineer hiring manager. The candidate was asked:\n"
        f"\"{pending['question']}\"\n\n"
        f"Key points a strong answer should cover: {pending['key_points']}\n\n"
        f"Candidate's answer: \"{user_answer}\"\n\n"
        "Using the attached document as ground truth, give constructive feedback: what they got "
        "right, what they missed, and a brief improvement tip. End with a score out of 10. "
        "Keep it concise (under 150 words)."
    )

    try:
        client = get_client()
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL,
            contents=[file_part, eval_prompt],
        )
        feedback = response.text
    except Exception as exc:
        logger.exception("Interview evaluation failed")
        await update.message.reply_text(f"❌ Couldn't evaluate your answer: {exc}")
        return ConversationHandler.END

    await _reply(update.message, f"📝 Feedback\n\n{feedback}\n\nUse /interview for another question.")
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

SCENARIO_PROMPT = (
    "You are a cybersecurity training designer. Based EXCLUSIVELY on the attached document, "
    "create an interactive, hands-on incident response scenario or lab exercise. Include: "
    "a realistic scenario setup, the systems/assets involved, a numbered sequence of "
    "investigation steps the trainee should take, and 2-3 decision points where the trainee "
    "must choose an action. Ground every detail in the document's content. Format clearly "
    "with short section headers."
)

async def scenario_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_pdf(update, context):
        return

    await update.message.reply_text("🧪 Building an incident response scenario from your document...")
    file_part = _get_active_file_part(context)

    try:
        client = get_client()
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL,
            contents=[file_part, SCENARIO_PROMPT],
        )
        scenario_text = response.text
    except Exception as exc:
        logger.exception("Scenario generation failed")
        await update.message.reply_text(f"❌ Couldn't generate a scenario: {exc}")
        return

    await _reply(update.message, f"🧪 Incident Response Scenario\n\n{scenario_text}")
