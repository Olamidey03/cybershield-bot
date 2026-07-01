import re

MAX_MESSAGE_LENGTH = 4000

_TAG_RE = re.compile(r"<[^>]+>")
_ANY_TAG_RE = re.compile(r"</?(\w+)(?:\s[^>]*)?>")
_VOID_TAG_SUFFIX = "/>"


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text)


def _track_open_tags(line: str, open_tags: list):
    """Update the running stack of open HTML tags as we scan a line."""
    for match in _ANY_TAG_RE.finditer(line):
        full, name = match.group(0), match.group(1)
        if full.startswith("</"):
            if name in open_tags:
                # remove the most recent matching open tag (should normally be the last one)
                for i in range(len(open_tags) - 1, -1, -1):
                    if open_tags[i] == name:
                        open_tags.pop(i)
                        break
        elif not full.endswith(_VOID_TAG_SUFFIX):
            open_tags.append(name)


def split_message(text: str, limit: int = MAX_MESSAGE_LENGTH) -> list:
    """Split `text` into chunks no longer than `limit` characters.

    Breaks are only made on line boundaries (never mid-line), and any HTML tags
    (<b>, <i>, <pre>, <code>, etc.) still open at a chunk boundary are closed at
    the end of that chunk and re-opened at the start of the next one, so tags
    are never left unbalanced across chunks.
    """
    if len(text) <= limit:
        return [text]

    lines = text.split("\n")
    chunks = []
    current_lines = []
    current_len = 0
    open_tags = []

    def flush():
        nonlocal current_lines, current_len
        if not current_lines:
            return
        chunk_text = "\n".join(current_lines)
        closers = "".join(f"</{t}>" for t in reversed(open_tags))
        chunks.append(chunk_text + closers)
        openers = "".join(f"<{t}>" for t in open_tags)
        current_lines = [openers] if openers else []
        current_len = len(openers)

    for line in lines:
        # Hard-slice any single line that alone exceeds the limit.
        while len(line) > limit:
            head, line = line[:limit], line[limit:]
            current_lines.append(head)
            flush()

        line_len = len(line) + 1  # account for the joining "\n"
        if current_lines and current_len + line_len > limit:
            flush()

        current_lines.append(line)
        current_len += line_len
        _track_open_tags(line, open_tags)

    if current_lines:
        chunks.append("\n".join(current_lines))

    return [c for c in chunks if c.strip()]


async def safe_reply_html(message, text: str):
    """Send a new message as HTML, falling back to plain text if the AI-generated
    HTML is malformed and Telegram rejects it with a 400 formatting error."""
    try:
        return await message.reply_text(text, parse_mode="HTML")
    except Exception:
        return await message.reply_text(_strip_tags(text))


async def safe_edit_html(status_msg, text: str):
    """Edit an existing message as HTML, falling back to plain text if the AI-generated
    HTML is malformed and Telegram rejects it with a 400 formatting error."""
    try:
        return await status_msg.edit_text(text, parse_mode="HTML")
    except Exception:
        return await status_msg.edit_text(_strip_tags(text))


async def send_html_report(status_msg, text: str, bot, chat_id: int):
    """Deliver a (possibly long) AI-generated HTML report safely.

    If the report fits in a single Telegram message, the status message is
    simply edited in place. If it's too long (Telegram's ~4096 char limit),
    it is split into chunks: the status message is edited with the first
    chunk, and every remaining chunk is sent as a brand-new message via
    `bot.send_message` so nothing gets dropped or crashes with
    `Message_too_long`.
    """
    chunks = split_message(text)
    if not chunks:
        return

    await safe_edit_html(status_msg, chunks[0])

    for chunk in chunks[1:]:
        try:
            await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML")
        except Exception:
            await bot.send_message(chat_id=chat_id, text=_strip_tags(chunk))
