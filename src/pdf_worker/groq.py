"""Chat completions from Groq's OpenAI-compatible API (the review's model suggestions).

The key is ``GROQ_API_KEY``, from the environment or a ``.env`` file in the current
folder. The text sent goes to api.groq.com. Groq's free tier counts a request's prompt
plus its ``max_completion_tokens`` against a per-minute budget, so each request asks for
what the prompt leaves of it, and a rate-limited request waits as Groq says and retries.
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from pdf_worker.errors import PdfWorkerError

MODEL = "openai/gpt-oss-120b"
API_URL = "https://api.groq.com/openai/v1"
TOKENS_PER_REQUEST = 8000  # free tier, gpt-oss-120b
CHARS_PER_TOKEN = 3  # Spanish is ~4 per token; 3 overestimates on purpose
MIN_COMPLETION_TOKENS = 1500
RATE_LIMIT_RETRIES = 5
MAX_WAIT_SECONDS = 120  # a longer wait means the daily quota is used up


class GroqError(PdfWorkerError):
    pass


def api_key(env_file: Path = Path(".env"), variable: str = "GROQ_API_KEY") -> str:
    """The key, or "" when there is none."""
    key = os.environ.get(variable, "")
    if not key and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip().removeprefix("export ") == variable:
                key = value.strip().strip("'\"")
    return key


def generate(system: str, user: str, key: str, model: str = MODEL) -> str:
    prompt_tokens = (len(system) + len(user)) // CHARS_PER_TOKEN + 100
    max_tokens = TOKENS_PER_REQUEST - prompt_tokens
    if max_tokens < MIN_COMPLETION_TOKENS:
        raise GroqError(f"The prompt (~{prompt_tokens} tokens) leaves too little for the answer.")
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_completion_tokens": max_tokens,
        "reasoning_effort": "low",
        "include_reasoning": False,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        # urllib's default User-Agent is blocked by Groq's CDN.
        "User-Agent": "pdf-worker",
    }
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        request = urllib.request.Request(f"{API_URL}/chat/completions", data, headers)
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                answer = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as error:
            wait = float(error.headers.get("retry-after") or 20)
            if error.code == 429 and attempt < RATE_LIMIT_RETRIES and wait <= MAX_WAIT_SECONDS:
                time.sleep(wait + 1)
                continue
            body = error.read().decode("utf-8", "replace")[:300]
            raise GroqError(f"Groq API error {error.code}: {body}") from error
        except OSError as error:
            raise GroqError(f"Cannot reach Groq: {error}") from error
    choice = answer["choices"][0]
    content = choice["message"].get("content") or ""
    if choice.get("finish_reason") == "length" or not content.strip():
        raise GroqError("Groq's answer was cut short or empty.")
    return content
