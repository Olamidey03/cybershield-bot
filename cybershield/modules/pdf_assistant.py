import datetime
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
    PollAnswerHandler,
    filters,
)

from modules.gemini_client import generate_with_retry
from modules.html_utils import send_html_report, typing_action, NAV_FOOTER

logger = logging.getLogger(__name__)

# Only INTERVIEW_ANSWER is still needed — quiz flow ends via PollAnswer, not text reply.
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

# ---------------------------------------------------------------------------
# Difficulty helpers
# ---------------------------------------------------------------------------

_DIFFICULTY_ORDER = ["beginner", "intermediate", "advanced"]

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


def _apply_difficulty_adjust(current: str, adjust: str) -> str:
    """Shift difficulty up or down by one step; clamp to valid range."""
    idx = _DIFFICULTY_ORDER.index(current) if current in _DIFFICULTY_ORDER else 1
    if adjust == "easier":
        return _DIFFICULTY_ORDER[max(0, idx - 1)]
    if adjust == "harder":
        return _DIFFICULTY_ORDER[min(2, idx + 1)]
    return current  # "same"


# ---------------------------------------------------------------------------
# XP & streak helpers  (Step 6)
# ---------------------------------------------------------------------------

def _update_xp_and_streak(user_data: dict, correct: bool) -> None:
    """Award XP for a correct answer and maintain the daily streak counter."""
    today = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    last = user_data.get("quiz_last_date", "")

    if last == today:
        pass  # streak already updated today
    elif last == yesterday:
        user_data["quiz_streak"] = user_data.get("quiz_streak", 0) + 1
    else:
        user_data["quiz_streak"] = 1  # streak reset

    user_data["quiz_last_date"] = today

    if correct:
        user_data["quiz_xp"] = user_data.get("quiz_xp", 0) + 10


# ---------------------------------------------------------------------------
# Action keyboard builder  (Step 7)
# ---------------------------------------------------------------------------

def _build_action_keyboard(user_data: dict) -> InlineKeyboardMarkup:
    """Build the post-Coach-Report inline keyboard with current selections highlighted."""
    focus = user_data.get("quiz_focus", "all")
    pool = user_data.get("quiz_pool_size", 5)
    adjust = user_data.get("quiz_difficulty_adjust", "same")

    def fmark(val):
        return " ✓" if focus == val else ""

    def pmark(n):
        return " ✓" if pool == n else ""

    def amark(val):
        return " ✓" if adjust == val else ""

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎯 All Topics" + fmark("all"), callback_data="quiz:focus:all"
            ),
            InlineKeyboardButton(
                "🌱 Growth Areas" + fmark("growth"), callback_data="quiz:focus:growth"
            ),
        ],
        [
            InlineKeyboardButton(f"5{pmark(5)}", callback_data="quiz:pool:5"),
            InlineKeyboardButton(f"10{pmark(10)}", callback_data="quiz:pool:10"),
            InlineKeyboardButton(f"20{pmark(20)}", callback_data="quiz:pool:20"),
        ],
        [
            InlineKeyboardButton(
                "🟢 Easier" + amark("easier"), callback_data="quiz:adjust:easier"
            ),
            InlineKeyboardButton(
                "🟡 Same" + amark("same"), callback_data="quiz:adjust:same"
            ),
            InlineKeyboardButton(
                "🔴 Harder" + amark("harder"), callback_data="quiz:adjust:harder"
            ),
        ],
        [InlineKeyboardButton("📚 Generate Study Guide", callback_data="quiz:studyguide")],
        [InlineKeyboardButton("▶️ Start New Round", callback_data="quiz:newround")],
    ])


# ---------------------------------------------------------------------------
# Hint inline keyboard
# ---------------------------------------------------------------------------

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


def _init_session(user_data: dict) -> None:
    """Initialise a fresh quiz session in user_data, preserving lifetime XP and streak."""
    pool_size = user_data.get("quiz_pool_size", 5)
    user_data["quiz_session"] = {
        "question_num": 0,   # incremented to 1 before the first question is sent
        "total": pool_size,
        "score": 0,
        "topics_correct": [],
        "topics_wrong": [],
        "active": True,
    }


# ---------------------------------------------------------------------------
# Quiz prompt templates  (Step 6 — adds `topic` field + focus_instruction)
# ---------------------------------------------------------------------------

# Character budget enforced in the prompt so output fits Telegram's poll limits:
#   question  < 250 chars  (Telegram hard limit: 300)
#   each option < 90 chars  (Telegram hard limit: 100)
#   explanation < 180 chars  (Telegram hard limit: 200)
#   hint < 150 chars  (fits comfortably in a show_alert popup)
#   topic < 60 chars  (short label used for Strengths/Weaknesses breakdown)
QUIZ_PROMPT_TEMPLATE = (
    "You are a cybersecurity instructor. Based EXCLUSIVELY on the document content provided "
    "below, generate ONE multiple-choice cybersecurity quiz question.\n\n"
    "{difficulty_instruction}\n\n"
    "{focus_instruction}"
    "STRICT CHARACTER LIMITS — you MUST respect these or your output will be rejected:\n"
    "  • question    < 250 characters (plain text, no HTML/Markdown)\n"
    "  • each option  < 90 characters (plain text, no HTML/Markdown)\n"
    "  • explanation < 180 characters (plain text only — this appears as a Telegram popup)\n"
    "  • hint        < 150 characters (plain text — shown on demand, must NOT reveal the answer)\n"
    "  • topic        < 60 characters (plain text — a short subject label, e.g. 'Encryption' "
    "or 'Firewall Rules' or 'MITRE ATT&CK')\n\n"
    "Respond ONLY with valid JSON in this exact shape — no extra keys, no markdown fences:\n"
    '{{"question":"...","options":{{"A":"...","B":"...","C":"...","D":"..."}},'
    '"correct_option":"A","explanation":"...","hint":"...","topic":"..."}}\n\n'
    "Document content:\n\n{text}"
)

STUDY_GUIDE_PROMPT_TEMPLATE = (
    "You are a cybersecurity instructor. The student struggled with the following topics "
    "in their recent quiz:\n\n{topics}\n\n"
    "Using EXCLUSIVELY the document content below as your knowledge source, generate a "
    "concise, high-yield revision study guide covering each weak area. For each topic provide:\n"
    "  1. <b>Key Concept</b> — a 2–3 sentence explanation grounded in the document\n"
    "  2. <b>Why It Matters</b> — practical security relevance\n"
    "  3. <b>Quick Memory Aid</b> — a memorable example, analogy, or mnemonic\n\n"
    "Use a clear <b>section header</b> for each topic. Keep total output under 800 words.\n\n"
    "Format using clean HTML tags for Telegram: <b> for headers/emphasis, <i> for italics, "
    "<pre><code> for technical snippets. No Markdown (no **, no *, no backtick fences).\n\n"
    "Document content:\n\n{text}"
)


# ---------------------------------------------------------------------------
# Core question generator  (Step 6)
# ---------------------------------------------------------------------------

async def _generate_and_send_question(
    bot,
    chat_id: int,
    user_data: dict,
    bot_data: dict,
) -> None:
    """Generate one quiz question via Gemini and send it as a native Telegram quiz poll.

    Updates ``user_data["quiz_session"]["question_num"]`` before generation so
    each question knows its position.  Registers the sent poll in
    ``bot_data["poll_registry"]`` so ``handle_poll_answer`` can grade it.
    """
    session = user_data.get("quiz_session", {})
    session["question_num"] = session.get("question_num", 0) + 1
    q_num = session["question_num"]
    total = session["total"]

    difficulty = user_data.get("quiz_difficulty", "intermediate")
    difficulty_label = _DIFFICULTY_LABELS.get(difficulty, "Intermediate 🟡")
    difficulty_instr = _DIFFICULTY_INSTRUCTIONS.get(
        difficulty, _DIFFICULTY_INSTRUCTIONS["intermediate"]
    )
    parsed_text = user_data.get("parsed_text", "")

    # Build optional focus instruction for Growth Areas mode
    focus = user_data.get("quiz_focus", "all")
    if focus == "growth":
        # Use topics_wrong accumulated from the PREVIOUS session
        weak_topics = user_data.get("quiz_last_topics_wrong", [])
        if weak_topics:
            topics_str = ", ".join(list(dict.fromkeys(weak_topics))[:10])  # dedupe, cap at 10
            focus_instr = (
                f"PRIORITY FOCUS: The student has previously struggled with these topics: "
                f"{topics_str}. Generate a question specifically targeting one of these weak areas.\n\n"
            )
        else:
            focus_instr = ""
    else:
        focus_instr = ""

    # Status message
    status_msg = await bot.send_message(
        chat_id=chat_id,
        text=(
            f"🧠 Generating question <b>{q_num}</b> of <b>{total}</b> "
            f"[{difficulty_label}]..."
        ),
        parse_mode="HTML",
    )

    try:
        prompt = QUIZ_PROMPT_TEMPLATE.format(
            difficulty_instruction=difficulty_instr,
            focus_instruction=focus_instr,
            text=parsed_text,
        )
        response = await generate_with_retry(
            contents=[prompt],
            response_mime_type="application/json",
        )
        data = json.loads(response.text)
    except Exception as exc:
        logger.exception("Quiz generation failed at Q%d/%d", q_num, total)
        session["active"] = False
        try:
            await status_msg.edit_text(
                f"❌ Couldn't generate question {q_num}: {exc}\n\n{NAV_FOOTER}",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    # --- Safety truncation (Telegram hard limits) ---
    question_raw = str(data.get("question", ""))[:250]
    options_raw = data.get("options", {})
    options_list = [
        str(options_raw.get("A", "Option A"))[:90],
        str(options_raw.get("B", "Option B"))[:90],
        str(options_raw.get("C", "Option C"))[:90],
        str(options_raw.get("D", "Option D"))[:90],
    ]
    correct_letter = str(data.get("correct_option", "A")).strip().upper()[:1]
    correct_idx = {"A": 0, "B": 1, "C": 2, "D": 3}.get(correct_letter, 0)
    explanation = str(data.get("explanation", ""))[:200]
    hint = str(data.get("hint", "No hint available for this question."))[:200]
    topic = str(data.get("topic", "General Cybersecurity"))[:60]

    # Store hint for the hint button callback
    user_data["quiz_hint"] = hint

    # Question prefix: [Q1/5 · Beginner 🟢] stays under 300 chars
    poll_question = f"[Q{q_num}/{total} · {difficulty_label}] {question_raw}"[:300]

    # Delete status message, then send the poll
    try:
        await status_msg.delete()
    except Exception:
        pass

    poll_msg = await bot.send_poll(
        chat_id=chat_id,
        question=poll_question,
        options=options_list,
        type="quiz",
        correct_option_id=correct_idx,
        explanation=explanation,
        is_anonymous=False,
    )

    # Register poll so PollAnswerHandler can grade it
    if "poll_registry" not in bot_data:
        bot_data["poll_registry"] = {}
    bot_data["poll_registry"][poll_msg.poll.id] = {
        "correct_option_id": correct_idx,
        "topic": topic,
        "chat_id": chat_id,
    }

    # Hint button beneath the poll
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"<i>Q{q_num}/{total} · Tap 💡 for a hint</i>"
            + NAV_FOOTER
        ),
        parse_mode="HTML",
        reply_markup=_HINT_KB,
    )


# ---------------------------------------------------------------------------
# Coach Report  (Step 6)
# ---------------------------------------------------------------------------

async def _send_coach_report(
    bot, chat_id: int, user_data: dict, session: dict
) -> None:
    """Send the end-of-session Coach Report followed by the Action Keyboard."""
    total = session["total"]
    score = session["score"]
    accuracy = int((score / total) * 100) if total > 0 else 0
    xp = user_data.get("quiz_xp", 0)
    streak = user_data.get("quiz_streak", 0)
    difficulty = user_data.get("quiz_difficulty", "intermediate")
    difficulty_label = _DIFFICULTY_LABELS.get(difficulty, "Intermediate 🟡")

    topics_correct = list(dict.fromkeys(session.get("topics_correct", [])))  # dedupe, order-preserving
    topics_wrong = list(dict.fromkeys(session.get("topics_wrong", [])))

    streak_str = f"{streak} 🔥" if streak > 1 else f"{streak} day"

    if topics_correct:
        strengths_html = "".join(f"  • {t}\n" for t in topics_correct)
    else:
        strengths_html = "  <i>No mastered topics this round.</i>\n"

    if topics_wrong:
        weaknesses_html = "".join(f"  • {t}\n" for t in topics_wrong)
    else:
        weaknesses_html = "  <i>All topics mastered this round! 🏆</i>\n"

    report = (
        "🎓 <b>Coach Report — Round Complete!</b>\n\n"
        "<b>📊 Statistics</b>\n"
        f"  Score:      <b>{score} / {total}</b>\n"
        f"  Accuracy:   <b>{accuracy}%</b>\n"
        f"  Total XP:   <b>{xp} XP ⚡</b>\n"
        f"  Streak:     <b>{streak_str}</b>\n"
        f"  Difficulty: <b>{difficulty_label}</b>\n\n"
        "<b>💪 Strengths</b>\n"
        f"{strengths_html}\n"
        "<b>📈 Growth Areas</b>\n"
        f"{weaknesses_html}\n"
        "<i>Customise your next round below, then tap ▶️ Start New Round.</i>"
    )

    await bot.send_message(
        chat_id=chat_id,
        text=report,
        parse_mode="HTML",
        reply_markup=_build_action_keyboard(user_data),
    )


# ---------------------------------------------------------------------------
# PollAnswer handler  (Step 6 — grades native quiz polls)
# ---------------------------------------------------------------------------

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Grade a native Telegram quiz poll answer, update stats, and advance the session."""
    poll_answer = update.poll_answer

    # Ignore retractions
    if not poll_answer.option_ids:
        return

    poll_id = poll_answer.poll_id
    registry: dict = context.bot_data.get("poll_registry", {})
    if poll_id not in registry:
        return  # Not one of our tracked quiz polls

    poll_info = registry.pop(poll_id)  # Consume so it cannot be graded twice
    correct_idx: int = poll_info["correct_option_id"]
    topic: str = poll_info["topic"]
    chat_id: int = poll_info["chat_id"]

    is_correct = poll_answer.option_ids[0] == correct_idx

    session: dict | None = context.user_data.get("quiz_session")
    if not session or not session.get("active"):
        return  # Session was cancelled or already finished

    # Update score and topic lists
    if is_correct:
        session["score"] += 1
        session["topics_correct"].append(topic)
    else:
        session["topics_wrong"].append(topic)

    # Update XP and daily streak
    _update_xp_and_streak(context.user_data, is_correct)

    q_num = session["question_num"]
    total = session["total"]

    if q_num >= total:
        # All questions answered — close session and send Coach Report
        session["active"] = False
        # Preserve this session's weak topics for the next round's Growth Areas mode
        context.user_data["quiz_last_topics_wrong"] = list(
            dict.fromkeys(session.get("topics_wrong", []))
        )
        await _send_coach_report(context.bot, chat_id, context.user_data, session)
    else:
        # More questions remain — generate the next one
        await _generate_and_send_question(
            context.bot, chat_id, context.user_data, context.bot_data
        )


# ---------------------------------------------------------------------------
# /quiz entry points
# ---------------------------------------------------------------------------

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry via /quiz command or '📚 Generate Quiz' keyboard button."""
    if not await _require_parsed_text(update, context):
        return ConversationHandler.END

    context.user_data.setdefault("quiz_difficulty", "intermediate")
    _init_session(context.user_data)

    pool_size = context.user_data["quiz_session"]["total"]
    diff_label = _DIFFICULTY_LABELS.get(
        context.user_data["quiz_difficulty"], "Intermediate 🟡"
    )

    await update.message.reply_text(
        f"🧠 Starting a <b>{diff_label}</b> quiz "
        f"(<b>{pool_size} questions</b>)...",
        parse_mode="HTML",
    )
    await _generate_and_send_question(
        context.bot,
        update.effective_chat.id,
        context.user_data,
        context.bot_data,
    )
    return ConversationHandler.END


async def quiz_difficulty_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry via Beginner / Intermediate / Advanced inline buttons."""
    query = update.callback_query
    difficulty = query.data.split(":")[1]
    context.user_data["quiz_difficulty"] = difficulty
    # Reset difficulty adjustment when starting fresh from the difficulty menu
    context.user_data["quiz_difficulty_adjust"] = "same"

    if not await _require_parsed_text(update, context):
        return ConversationHandler.END

    await query.answer(f"Difficulty set to {_DIFFICULTY_LABELS.get(difficulty, difficulty)}")

    _init_session(context.user_data)
    pool_size = context.user_data["quiz_session"]["total"]

    await query.edit_message_text(
        f"🧠 Starting a <b>{_DIFFICULTY_LABELS[difficulty]}</b> quiz "
        f"(<b>{pool_size} questions</b>)...",
        parse_mode="HTML",
    )
    await _generate_and_send_question(
        context.bot,
        update.effective_chat.id,
        context.user_data,
        context.bot_data,
    )
    return ConversationHandler.END


async def quiz_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = context.user_data.get("quiz_session")
    if session:
        session["active"] = False
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
        states={},  # Quiz flow ends immediately; grading happens via PollAnswerHandler
        fallbacks=[CommandHandler("cancel", quiz_cancel)],
        per_message=False,
    )


# ---------------------------------------------------------------------------
# Step 7 — Action Keyboard callback handlers
# ---------------------------------------------------------------------------

async def handle_quiz_settings_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle focus / pool / adjust setting buttons — store preference and refresh keyboard."""
    query = update.callback_query
    parts = query.data.split(":")  # e.g. ["quiz", "pool", "10"]
    setting_type = parts[1]
    value = parts[2]

    if setting_type == "focus":
        context.user_data["quiz_focus"] = value
        labels = {"all": "🎯 All Topics", "growth": "🌱 Growth Areas"}
        await query.answer(f"Focus: {labels.get(value, value)}")
    elif setting_type == "pool":
        context.user_data["quiz_pool_size"] = int(value)
        await query.answer(f"Pool length: {value} questions")
    elif setting_type == "adjust":
        context.user_data["quiz_difficulty_adjust"] = value
        labels = {"easier": "🟢 Easier", "same": "🟡 Same", "harder": "🔴 Harder"}
        await query.answer(f"Difficulty adjustment: {labels.get(value, value)}")

    # Redraw the keyboard in place to show the updated ✓ checkmark
    try:
        await query.edit_message_reply_markup(
            reply_markup=_build_action_keyboard(context.user_data)
        )
    except Exception:
        pass


async def handle_quiz_study_guide_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Generate a personalised study guide from the user's accumulated weak topics."""
    query = update.callback_query
    await query.answer("📚 Generating your study guide…")

    topics_wrong = context.user_data.get("quiz_last_topics_wrong", [])
    parsed_text = context.user_data.get("parsed_text", "")

    if not topics_wrong:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "✅ <b>No growth areas recorded!</b>\n\n"
                "You answered all topics correctly in your last round. Keep it up! 🏆\n\n"
                "Complete a quiz round first to track weak topics, then tap "
                "<b>📚 Generate Study Guide</b> for a personalised revision block."
                + NAV_FOOTER
            ),
            parse_mode="HTML",
        )
        return

    if not parsed_text:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "📎 No document is currently loaded. Upload a document first so I can "
                "build a study guide grounded in its content."
                + NAV_FOOTER
            ),
            parse_mode="HTML",
        )
        return

    status_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="📚 Generating your personalised study guide…",
        parse_mode="HTML",
    )

    topics_list = ", ".join(topics_wrong)
    prompt = STUDY_GUIDE_PROMPT_TEMPLATE.format(topics=topics_list, text=parsed_text)

    try:
        response = await generate_with_retry(contents=[prompt])
        guide_text = (
            f"📚 <b>Personalised Study Guide</b>\n"
            f"<i>Targeted weak areas: {topics_list}</i>\n\n"
            f"{response.text}"
        )
        await send_html_report(
            status_msg, guide_text, context.bot, update.effective_chat.id
        )
    except Exception as exc:
        logger.exception("Study guide generation failed")
        await status_msg.edit_text(f"❌ Couldn't generate study guide: {exc}")


async def handle_quiz_new_round_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Start a fresh quiz session using the settings selected in the Action Keyboard."""
    query = update.callback_query

    if not context.user_data.get("parsed_text"):
        await query.answer("Upload a document first!", show_alert=True)
        return

    await query.answer("▶️ Starting new round…")

    # Apply difficulty adjustment for this new round
    current = context.user_data.get("quiz_difficulty", "intermediate")
    adjust = context.user_data.get("quiz_difficulty_adjust", "same")
    context.user_data["quiz_difficulty"] = _apply_difficulty_adjust(current, adjust)
    # Reset the adjust knob so it doesn't stack on future rounds unless re-selected
    context.user_data["quiz_difficulty_adjust"] = "same"

    _init_session(context.user_data)

    # Remove the action keyboard from the Coach Report to prevent double-taps
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    pool_size = context.user_data["quiz_session"]["total"]
    diff_label = _DIFFICULTY_LABELS.get(
        context.user_data["quiz_difficulty"], "Intermediate 🟡"
    )
    focus = context.user_data.get("quiz_focus", "all")
    focus_label = "🌱 Growth Areas" if focus == "growth" else "🎯 All Topics"

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            f"🔄 <b>New Round Starting!</b>\n"
            f"  Difficulty: <b>{diff_label}</b>\n"
            f"  Questions:  <b>{pool_size}</b>\n"
            f"  Focus:      <b>{focus_label}</b>"
        ),
        parse_mode="HTML",
    )

    await _generate_and_send_question(
        context.bot,
        update.effective_chat.id,
        context.user_data,
        context.bot_data,
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
        await status_msg.edit_text(f"❌ Couldn't generate a scenario: {exc}")
