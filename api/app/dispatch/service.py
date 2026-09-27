"""Dispatch an approved advisory by Telegram and e-mail, with a CAP 1.2 attachment
(contracts.md §4.7, §5; added in v1.2).

Rules:
- Only approved advisories (409). A sent one needs resend=true (409 otherwise); resends are
  audited as such.
- A live dispatch needs `pin`, compared in constant time with DISPATCH_PIN (403 if wrong or
  unset). Dry runs need no PIN. At most LIVE_PER_HOUR live dispatches in any rolling hour (429).
- Recipients come only from settings, never from the request.
- Each channel is attempted on its own; one failing doesn't stop the other. Each gets a result
  (status, provider message id, error, time), stored with the receipt in SQLite and audited as
  "dispatched". The advisory becomes sent if at least one channel succeeded ("sent" audit).
- dry_run builds the messages and the CAP and validates the CAP, sends nothing and changes
  nothing: its receipt (status dry_run per channel) is returned and audited, not stored.

Dispatch sends for real in DEMO_MODE too: it is a human-approved action, not a data fetch.
"""

import hmac
import json
from datetime import timedelta

from app.advisory import store
from app.core.config import Settings, get_settings
from app.dispatch import cap, channels
from app.schemas import (
    Advisory,
    AdvisoryProperties,
    ChannelResult,
    DispatchReceipt,
    DispatchRecipients,
    DispatchRequest,
    EmailRecipients,
    TelegramRecipient,
)

LIVE_PER_HOUR = 10


class NotFound(LookupError):
    pass


class Locked(RuntimeError):
    """Not approved, or already sent without resend (409)."""


class Forbidden(PermissionError):
    """Wrong or unset PIN (403)."""


class RateLimited(RuntimeError):
    """Too many live dispatches in the last hour (429)."""


# --- Masking -----------------------------------------------------------------------------------


def mask_email(address: str) -> str:
    local, _, domain = address.partition("@")
    keep = local[:2] if len(local) > 2 else local[:1]
    return f"{keep}{'*' * max(len(local) - len(keep), 3)}@{domain}"


def mask_chat_id(chat_id: str) -> str:
    return f"{'*' * max(len(chat_id) - 4, 3)}{chat_id[-4:]}" if len(chat_id) > 4 else "****"


def recipients(settings: Settings | None = None) -> DispatchRecipients:
    s = settings or get_settings()
    telegram_ok = channels.telegram_configured(s)
    email_ok = channels.email_configured(s)
    return DispatchRecipients(
        telegram=TelegramRecipient(
            configured=telegram_ok,
            chat_id=mask_chat_id(s.TELEGRAM_CHAT_ID) if telegram_ok else None,
        ),
        email=EmailRecipients(
            configured=email_ok,
            to=[mask_email(a) for a in channels.email_recipients(s)] if email_ok else [],
        ),
        pin_configured=s.is_configured("DISPATCH_PIN"),
    )


# --- Receipts ----------------------------------------------------------------------------------


def receipts(advisory_id: str) -> list[DispatchReceipt]:
    with store.transaction() as conn:
        if store.load(conn, advisory_id) is None:
            raise NotFound(f"no advisory {advisory_id!r}")
        rows = conn.execute(
            "SELECT data FROM dispatch_receipts WHERE advisory_id = ? ORDER BY id", (advisory_id,)
        ).fetchall()
    return [DispatchReceipt.model_validate_json(r["data"]) for r in rows]


def cap_xml(advisory_id: str) -> str:
    """The CAP of the latest live dispatch; for an approved advisory never sent, a fresh one."""
    with store.transaction() as conn:
        advisory = store.load(conn, advisory_id)
        if advisory is None:
            raise NotFound(f"no advisory {advisory_id!r}")
        row = conn.execute(
            "SELECT cap_xml FROM dispatch_receipts WHERE advisory_id = ? ORDER BY id DESC LIMIT 1",
            (advisory_id,),
        ).fetchone()
    if row is not None:
        return row["cap_xml"]
    if advisory.properties.status not in ("approved", "sent"):
        raise Locked(f"advisory is {advisory.properties.status}; only approved ones have a CAP")
    xml = cap.build(advisory, store.now())
    cap.validate(xml)
    return xml


# --- Dispatch ----------------------------------------------------------------------------------


def _check_pin(pin: str | None, settings: Settings) -> None:
    expected = settings.DISPATCH_PIN if settings.is_configured("DISPATCH_PIN") else None
    if expected is None:
        raise Forbidden("DISPATCH_PIN is not set in api/.env; live dispatch is disabled")
    if pin is None or not hmac.compare_digest(pin.encode("utf-8"), expected.encode("utf-8")):
        raise Forbidden("wrong PIN")


def _check_state(advisory: Advisory | None, advisory_id: str, resend: bool) -> Advisory:
    if advisory is None:
        raise NotFound(f"no advisory {advisory_id!r}")
    status = advisory.properties.status
    if status == "sent" and not resend:
        raise Locked("advisory was already sent; set resend to send it again")
    if status not in ("approved", "sent"):
        raise Locked(f"advisory is {status}; only approved advisories can be dispatched")
    return advisory


def _live_in_last_hour(conn, now) -> int:
    since = (now - timedelta(hours=1)).isoformat()
    return conn.execute(
        "SELECT COUNT(*) FROM dispatch_receipts WHERE dispatched_at > ?", (since,)
    ).fetchone()[0]


def dispatch(
    advisory_id: str, request: DispatchRequest, actor: str | None = None
) -> DispatchReceipt:
    settings = get_settings()
    with store.transaction() as conn:
        advisory = _check_state(store.load(conn, advisory_id), advisory_id, request.resend)
        if not request.dry_run:
            _check_pin(request.pin, settings)
            if _live_in_last_hour(conn, store.now()) >= LIVE_PER_HOUR:
                raise RateLimited(f"at most {LIVE_PER_HOUR} live dispatches per hour")
    resend = advisory.properties.status == "sent"

    dispatched_at = store.now()
    xml = cap.build(advisory, dispatched_at)
    cap.validate(xml)  # a CAP that doesn't validate is never sent (500)
    wanted = list(dict.fromkeys(request.channels))
    results: list[ChannelResult] = []
    for channel in wanted:
        try:
            if channel == "telegram":
                messages = channels.telegram_messages(advisory)
                message_id = None if request.dry_run else channels.send_telegram(settings, messages)
            else:
                message = channels.email_message(settings, advisory, xml)
                message_id = None if request.dry_run else channels.send_email(settings, message)
            status = "dry_run" if request.dry_run else "sent"
            results.append(
                ChannelResult(
                    channel=channel, status=status, provider_message_id=message_id, at=store.now()
                )
            )
        except Exception as e:  # each channel on its own: one failing never stops the other
            error = e if isinstance(e, channels.ChannelError) else f"{type(e).__name__}: {e}"
            results.append(
                ChannelResult(
                    channel=channel,
                    status="failed",
                    error=channels.scrub(str(error), settings),
                    at=store.now(),
                )
            )

    receipt = DispatchReceipt(
        advisory_id=advisory_id,
        dispatched_at=dispatched_at,
        dry_run=request.dry_run,
        resend=resend,
        channels=results,
    )
    with store.transaction() as conn:
        for r in results:
            details = {**r.model_dump(mode="json"), "dry_run": request.dry_run, "resend": resend}
            store.audit(conn, advisory_id, "dispatched", actor, details)
        if request.dry_run:
            return receipt
        conn.execute(
            "INSERT INTO dispatch_receipts (advisory_id, dispatched_at, data, cap_xml) "
            "VALUES (?, ?, ?, ?)",
            (advisory_id, dispatched_at.isoformat(), receipt.model_dump_json(), xml),
        )
        if any(r.status == "sent" for r in results):
            current = store.load(conn, advisory_id)
            if current is not None and current.properties.status == "approved":
                props = AdvisoryProperties.model_validate(
                    {**current.properties.model_dump(), "status": "sent"}
                )
                store.save(conn, Advisory(id=props.id, properties=props))
            sent = [r.channel for r in results if r.status == "sent"]
            store.audit(
                conn, advisory_id, "sent", actor, json.dumps({"channels": sent, "resend": resend})
            )
    return receipt
