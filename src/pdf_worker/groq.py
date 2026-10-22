"""Chat completions from Groq (the review's model suggestions), through ai-client.

The key is ``GROQ_API_KEY``, from the environment or ai-client's ``.env``. The text sent
goes to api.groq.com. ai-client's Groq client sizes each request to the free tier's
per-request token budget and waits and retries when rate-limited.
"""

import ai_client

from pdf_worker.errors import PdfWorkerError

MODEL = "openai/gpt-oss-120b"


class GroqError(PdfWorkerError):
    pass


def api_key() -> str:
    """The key, or "" when there is none."""
    return ai_client.Groq().key


def generate(system: str, user: str, key: str, model: str = MODEL) -> str:
    options = {"temperature": 0.2, "reasoning_effort": "low", "include_reasoning": False}
    try:
        return ai_client.Groq(model, key).chat(user, system, **options)
    except ai_client.AIClientError as error:
        raise GroqError(str(error)) from error
