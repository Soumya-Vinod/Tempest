"""The two dispatch channels. Each send returns (provider message id) or raises ChannelError with
a message that never contains a credential: the bot token (it is part of the Telegram URL, so
httpx errors include it) and the Gmail app password are scrubbed from every error text.

- Telegram: Bot API sendMessage to TELEGRAM_CHAT_ID, plain text, one message per language (bn
  first, then en), each split at line breaks to stay within Telegram's 4096-character limit.
- E-mail: Gmail SMTP (smtp.gmail.com:587, STARTTLS) as GMAIL_ADDRESS with GMAIL_APP_PASSWORD,
  to DISPATCH_EMAIL_TO (comma-separated). Subject starts with [EXERCISE]; the body holds en then
  bn; the CAP XML is attached.

Recipients come only from settings (api/.env); nothing here takes an address from a request.
"""

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

import httpx

from app.advisory import render
from app.core.config import Settings
from app.schemas import Advisory, AdvisoryText

TELEGRAM_API = "https://api.telegram.org"
TELEGRAM_MAX_CHARS = 4096
TELEGRAM_LANGUAGES = ("bn", "en")
EMAIL_LANGUAGES = ("en", "bn")
SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 587
TIMEOUT_S = 30
SMTP = smtplib.SMTP  # tests replace this


def http_client() -> httpx.Client:
    """The HTTP client for the Bot API (tests replace this with a mock transport)."""
    return httpx.Client(timeout=TIMEOUT_S)


class ChannelError(RuntimeError):
    """A channel failed; the message is safe to store and show."""


def scrub(text: str, settings: Settings) -> str:
    for secret in (settings.TELEGRAM_BOT_TOKEN, settings.GMAIL_APP_PASSWORD, settings.DISPATCH_PIN):
        if secret:
            text = text.replace(secret, "***")
    return text


def email_recipients(settings: Settings) -> list[str]:
    return [a.strip() for a in (settings.DISPATCH_EMAIL_TO or "").split(",") if a.strip()]


def telegram_configured(settings: Settings) -> bool:
    return settings.is_configured("TELEGRAM_BOT_TOKEN") and settings.is_configured(
        "TELEGRAM_CHAT_ID"
    )


def email_configured(settings: Settings) -> bool:
    return (
        settings.is_configured("GMAIL_ADDRESS")
        and settings.is_configured("GMAIL_APP_PASSWORD")
        and settings.is_configured("DISPATCH_EMAIL_TO")
        and bool(email_recipients(settings))
    )


def exercise_label(language: str) -> str:
    """First line of every dispatched message, so a notification preview shows it first."""
    return f"⚠️ {render.EXERCISE_PREFIX[language]}"


def _content(t: AdvisoryText) -> str:
    actions = "\n".join(f"{i}. {a}" for i, a in enumerate(t.actions, 1))
    return f"{t.headline}\n\n{t.body}\n\n{actions}"


def plain_text(t: AdvisoryText, language: str) -> str:
    """The exercise label, a blank line, then headline, body (which keeps its own prefix) and
    the numbered actions."""
    return f"{exercise_label(language)}\n\n{_content(t)}"


def split_message(text: str, limit: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """Parts of at most `limit` characters, split at line breaks where possible."""
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:  # a single overlong line: hard split
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def telegram_messages(advisory: Advisory) -> list[str]:
    """bn then en; a text over the limit is split, and every part starts with the label."""
    texts = advisory.properties.texts
    messages = []
    for lang in TELEGRAM_LANGUAGES:
        label = f"{exercise_label(lang)}\n\n"
        parts = split_message(_content(getattr(texts, lang)), TELEGRAM_MAX_CHARS - len(label))
        messages += [label + part for part in parts]
    return messages


def send_telegram(
    settings: Settings, messages: list[str], client: httpx.Client | None = None
) -> str:
    """Send each message in order; returns the Telegram message ids, comma-separated."""
    if not telegram_configured(settings):
        raise ChannelError("Telegram is not configured (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)")
    url = f"{TELEGRAM_API}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    ids: list[str] = []
    own = client is None
    http = client or http_client()
    try:
        for i, text in enumerate(messages, 1):
            try:
                r = http.post(url, json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": text})
                body = r.json()
            except (httpx.HTTPError, ValueError) as e:
                raise ChannelError(
                    scrub(f"message {i}/{len(messages)}: {type(e).__name__}: {e}", settings)
                ) from None
            if not body.get("ok"):
                detail = body.get("description") or f"HTTP {r.status_code}"
                sent = f" (sent before failing: {','.join(ids)})" if ids else ""
                raise ChannelError(scrub(f"message {i}/{len(messages)}: {detail}{sent}", settings))
            ids.append(str(body["result"]["message_id"]))
    finally:
        if own:
            http.close()
    return ",".join(ids)


def email_message(settings: Settings, advisory: Advisory, cap_xml: str) -> EmailMessage:
    p = advisory.properties
    msg = EmailMessage()
    msg["Subject"] = f"[EXERCISE] {p.texts.en.headline} ({p.block_name})"
    msg["From"] = settings.GMAIL_ADDRESS
    msg["To"] = ", ".join(email_recipients(settings))
    msg["Message-ID"] = make_msgid(domain="tempest.invalid")
    body = "\n\n----------\n\n".join(
        plain_text(getattr(p.texts, lang), lang) for lang in EMAIL_LANGUAGES
    )
    msg.set_content(body, charset="utf-8")
    compact = p.timestep.replace("-", "").replace(":", "")
    msg.add_attachment(
        cap_xml.encode("utf-8"),
        maintype="application",
        subtype="xml",
        filename=f"tempest-cap-{p.block_id}-{compact}.xml",
    )
    return msg


def send_email(settings: Settings, message: EmailMessage) -> str:
    """Send over Gmail SMTP with STARTTLS; returns the Message-ID."""
    if not email_configured(settings):
        raise ChannelError(
            "E-mail is not configured (GMAIL_ADDRESS, GMAIL_APP_PASSWORD, DISPATCH_EMAIL_TO)"
        )
    try:
        with SMTP(SMTP_HOST, SMTP_PORT, timeout=TIMEOUT_S) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(settings.GMAIL_ADDRESS, settings.GMAIL_APP_PASSWORD)
            refused = smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as e:
        raise ChannelError(scrub(f"{type(e).__name__}: {e}", settings)) from None
    if refused:
        raise ChannelError(scrub(f"refused recipients: {', '.join(refused)}", settings))
    return str(message["Message-ID"])
