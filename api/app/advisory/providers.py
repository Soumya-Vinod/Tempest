"""The advisory models: Gemini (primary, unchanged: gemini.py) and Groq (fallback, used only when
Gemini answers 429 or 503; see service.generate_live).

Both get the same system prompt and user message (prompt.py) and must return the same structure
(gemini.GeminiDraft); service.evaluate() then runs the same schema, placeholder and number checks
on either. Groq is called over its OpenAI-compatible REST API with strict JSON-schema output
(GROQ_MODEL, default openai/gpt-oss-120b: a production model with strict structured outputs and
multilingual support, incl. Bengali). The strict schema can't express the 3-5 actions bound, so
it is left to GeminiDraft's validation, like every other rule.
"""

import json
from dataclasses import dataclass

import httpx

from app.advisory import gemini
from app.core.config import Settings
from app.schemas import GeneratedBy

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TIMEOUT_S = 90
GROQ_REASONING_EFFORT = "low"  # the model reasons briefly; the checks do the rest

# Labels for the UI and the audit log.
GEMINI = GeneratedBy(provider="gemini", model=gemini.MODEL)


class GroqError(RuntimeError):
    """The Groq API call failed; `status` is the HTTP status when there was one. The message
    never contains the API key."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Provider:
    generated_by: GeneratedBy
    error: type[Exception]  # what a failed call raises (with .status)


def _text_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "body": {"type": "string"},
            "actions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["headline", "body", "actions"],
        "additionalProperties": False,
    }


# gemini.GeminiDraft for strict mode: every field required, no additional properties, no $refs.
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {lang: _text_schema() for lang in gemini.GeminiDraft.model_fields},
    "required": list(gemini.GeminiDraft.model_fields),
    "additionalProperties": False,
}


def groq_request(system_prompt: str, message: str, model: str) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "advisory_draft", "strict": True, "schema": DRAFT_SCHEMA},
        },
        "reasoning_effort": GROQ_REASONING_EFFORT,
    }


def http_client() -> httpx.Client:
    """Tests replace this with a mock transport."""
    return httpx.Client(timeout=GROQ_TIMEOUT_S)


def groq_generate(system_prompt: str, message: str, settings: Settings) -> dict:
    """One Groq call; returns the parsed structured response (not yet validated)."""
    key = settings.GROQ_API_KEY or ""

    def fail(text: str, status: int | None = None) -> GroqError:
        message = f"Groq call failed: {text}"
        return GroqError(message.replace(key, "***") if key else message, status)

    try:
        with http_client() as client:
            r = client.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {key}"},
                json=groq_request(system_prompt, message, settings.GROQ_MODEL),
            )
    except httpx.HTTPError as e:
        raise fail(f"{type(e).__name__}: {e}") from None
    if r.status_code != 200:
        try:
            detail = r.json().get("error", {}).get("message") or r.text[:300]
        except ValueError:
            detail = r.text[:300]
        raise fail(f"HTTP {r.status_code}: {detail}", r.status_code)
    try:
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise fail(f"unusable response: {type(e).__name__}: {e}", r.status_code) from None


def groq(settings: Settings) -> Provider:
    return Provider(GeneratedBy(provider="groq", model=settings.GROQ_MODEL), GroqError)


def call(provider: Provider, system_prompt: str, message: str, settings: Settings) -> dict:
    if provider.generated_by.provider == "gemini":
        return gemini.generate(system_prompt, message, settings.GEMINI_API_KEY)
    return groq_generate(system_prompt, message, settings)


GEMINI_PROVIDER = Provider(GEMINI, gemini.GeminiError)
