import re

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text)


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
