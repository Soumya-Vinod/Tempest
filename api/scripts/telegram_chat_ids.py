"""Print the Telegram chats the dispatch bot can see, to fill in TELEGRAM_CHAT_ID.

Run from the repo root:  api\\.venv\\Scripts\\python api\\scripts\\telegram_chat_ids.py

Reads TELEGRAM_BOT_TOKEN from api/.env (via settings) and calls the Bot API's getUpdates. First
send the bot a message (or add it to the group / channel and post there), then run this. The
token is never printed, including in error messages. Read-only: it sends nothing.
"""

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.dispatch.channels import TELEGRAM_API, scrub  # noqa: E402


def chats(updates: list[dict]) -> dict[int, dict]:
    """chat id -> the chat object, from every update type that carries one."""
    out: dict[int, dict] = {}
    for update in updates:
        for key in ("message", "edited_message", "channel_post", "my_chat_member", "chat_member"):
            chat = (update.get(key) or {}).get("chat")
            if chat and "id" in chat:
                out[chat["id"]] = chat
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    settings = get_settings()
    if not settings.is_configured("TELEGRAM_BOT_TOKEN"):
        sys.exit("TELEGRAM_BOT_TOKEN is not set in api/.env")
    url = f"{TELEGRAM_API}/bot{settings.TELEGRAM_BOT_TOKEN}/getUpdates"
    try:
        body = httpx.get(url, timeout=30).json()
    except (httpx.HTTPError, ValueError) as e:
        sys.exit(scrub(f"getUpdates failed: {type(e).__name__}: {e}", settings))
    if not body.get("ok"):
        sys.exit(scrub(f"getUpdates failed: {body.get('description', body)}", settings))
    found = chats(body.get("result", []))
    if not found:
        print("No chats yet. Send the bot a message (or post in its group), then run this again.")
        return
    print(f"{'chat id':>16}  {'type':<11} name")
    for chat_id, chat in found.items():
        name = chat.get("title") or " ".join(
            filter(None, [chat.get("first_name"), chat.get("last_name")])
        )
        if chat.get("username"):
            name = f"{name} (@{chat['username']})".strip()
        print(f"{chat_id:>16}  {chat.get('type', '?'):<11} {name}")
    print("\nPut the chosen id in api/.env as TELEGRAM_CHAT_ID=<id>.")


if __name__ == "__main__":
    main()
