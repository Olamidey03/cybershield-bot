import io
import logging

from pypdf import PdfReader
from docx import Document

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 4000

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", ".csv")


def parse_pdf_bytes(data: bytes) -> str:
    """Extract text from PDF bytes entirely in memory using pypdf."""
    reader = PdfReader(io.BytesIO(data))
    pages_text = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages_text).strip()


def parse_docx_bytes(data: bytes) -> str:
    """Extract text from DOCX bytes entirely in memory using python-docx."""
    document = Document(io.BytesIO(data))
    paragraphs = [p.text for p in document.paragraphs]
    return "\n".join(paragraphs).strip()


def parse_plain_text_bytes(data: bytes) -> str:
    """Decode raw .txt/.csv bytes as UTF-8."""
    return data.decode("utf-8").strip()


def route_and_parse(filename: str, data: bytes) -> str:
    """Route file bytes to the correct parser based on its extension.

    Everything happens in memory (io.BytesIO) — nothing is ever written to disk.
    Raises ValueError for unsupported extensions so callers can report a clean error.
    """
    lower_name = (filename or "").lower()

    if lower_name.endswith(".pdf"):
        return parse_pdf_bytes(data)
    if lower_name.endswith(".docx"):
        return parse_docx_bytes(data)
    if lower_name.endswith(".txt") or lower_name.endswith(".csv"):
        return parse_plain_text_bytes(data)

    raise ValueError(
        f"Unsupported file type. Supported extensions: {', '.join(SUPPORTED_EXTENSIONS)}"
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def handle_raw_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Capture pasted security data sent as plain text (not a command)."""
    try:
        text = update.message.text or ""

        if len(text) > MAX_TEXT_LENGTH:
            await update.message.reply_text(
                f"⚠️ That's too much text ({len(text)} characters). "
                f"Please paste data under {MAX_TEXT_LENGTH} characters, or upload it as a "
                f".txt/.csv/.pdf/.docx file instead."
            )
            return

        await update.message.reply_text(
            f"✅ Received pasted data — {len(text)} characters captured successfully."
        )
    except Exception as exc:
        logger.exception("Raw text handling failed")
        await update.message.reply_text(f"❌ Couldn't process that text: {exc}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Securely download a document fully in memory and parse it by extension."""
    document = update.message.document
    if not document:
        return

    filename = document.file_name or ""

    try:
        tg_file = await context.bot.get_file(document.file_id)

        # Download entirely into RAM — never touches local disk.
        buffer = io.BytesIO()
        await tg_file.download_to_memory(out=buffer)
        file_bytes = buffer.getvalue()

        extracted_text = route_and_parse(filename, file_bytes)

        await update.message.reply_text(
            f"✅ Successfully parsed \"{filename}\" — extracted {len(extracted_text)} characters."
        )
    except ValueError as exc:
        await update.message.reply_text(f"⚠️ {exc}")
    except UnicodeDecodeError:
        await update.message.reply_text(
            f"❌ Couldn't decode \"{filename}\" as UTF-8 text. Is it actually a .txt/.csv file?"
        )
    except Exception as exc:
        logger.exception("Document parsing failed")
        await update.message.reply_text(f"❌ Couldn't parse \"{filename}\": {exc}")
