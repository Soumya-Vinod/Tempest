"""The Gemini call for advisory drafts: gemini-3.7-flash via google-genai, thinking level low,
structured output with no numeric fields. Tests replace `generate`; nothing else calls Gemini."""

from pydantic import BaseModel, Field

MODEL = "gemini-3.7-flash"


class GeminiError(RuntimeError):
    """The Gemini API call failed. `status` is the HTTP status code when the API returned one
    (e.g. 503 when the model is overloaded), else None."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


# Response schema: text only. Figures are {{key}} placeholders inside the strings.
class DraftText(BaseModel):
    headline: str
    body: str
    actions: list[str] = Field(min_length=3, max_length=5)


class GeminiDraft(BaseModel):
    en: DraftText
    bn: DraftText
    hi: DraftText


def generate(system_prompt: str, message: str, api_key: str) -> dict:
    """One call; returns the raw structured response (parsed JSON, not yet validated)."""
    import json

    from google import genai
    from google.genai import types

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL,
            contents=message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=GeminiDraft,
                thinking_config=types.ThinkingConfig(thinking_level="low"),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        return json.loads(response.text)
    except Exception as e:  # SDK, network and JSON errors alike
        status = getattr(e, "code", None)  # google.genai.errors.APIError carries the HTTP code
        raise GeminiError(
            f"Gemini call failed: {type(e).__name__}: {e}",
            status if isinstance(status, int) else None,
        ) from e
