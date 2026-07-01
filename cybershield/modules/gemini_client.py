import os

from google import genai

MODEL = "gemini-2.5-flash"

_client = None


def get_client() -> genai.Client:
    """Lazily create a shared google-genai client for all Gemini-powered modules."""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it as a Replit secret to enable AI features."
            )
        _client = genai.Client(api_key=api_key)
    return _client
