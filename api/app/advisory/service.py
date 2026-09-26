"""Advisory generation and the approval queue (contracts.md §4.5, §5).

Generate: engine facts -> Gemini (one call per block and timestep, en + bn + hi) -> number check
-> placeholders filled -> a draft. In DEMO_MODE a cached Gemini response
(advisory__gemini-<census_code>__<ts>) is used when there is one; otherwise the live key if it is
set, else 503. A draft failing the number check is retried once, then refused (502); each
failure is written to the audit log.

Rules: only drafts can be edited, approved or rejected (else 409). Edits are checked like
Gemini's drafts, and can't remove a placeholder. Approval needs "Name (Designation)"; rejection
needs a reason. "New draft from this" copies a finished advisory into a new draft. Every action
is audited.
"""

import re
import uuid
from collections.abc import Callable

from pydantic import ValidationError

from app.advisory import gemini, render, store
from app.advisory.facts import Facts, UnknownBlock, build_facts
from app.advisory.prompt import SYSTEM_PROMPT, user_message
from app.core.config import get_settings
from app.core.demo import load_fixture
from app.impact.fixtures import compact_timestep
from app.risk import service as risk
from app.schemas import (
    LIVE,
    Advisory,
    AdvisoryProperties,
    AdvisorySuggestion,
    AdvisorySuggestions,
    AdvisoryTexts,
)

SUGGEST_MIN_SCORE = 0.25  # blocks at or above this risk score are suggested for an advisory
MAX_ATTEMPTS = 2  # one retry after a failed number check
DESIGNATIONS = ("BDO", "SDO", "ADM (Disaster Management)", "District Magistrate")
_APPROVER_RE = re.compile(
    r"^(?P<name>\S.*?)\s+\((?P<designation>"
    + "|".join(map(re.escape, DESIGNATIONS))
    + r"|Other: *(?P<role>[^()]*?\S[^()]*?))\)$"
)

__all__ = ["UnknownBlock"]


class NotFound(LookupError):
    pass


class Locked(RuntimeError):
    """The advisory is not a draft (409)."""


class Invalid(ValueError):
    """Bad input: approver format, empty reason, or an edit failing the checks (422)."""

    def __init__(self, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.problems = problems or []


class GeminiUnavailable(RuntimeError):
    """No cached response and no key (503)."""


class DraftRejected(RuntimeError):
    """Gemini's drafts failed the checks on every attempt, or the call failed (502)."""

    def __init__(self, message: str, problems: list[str] | None = None, calls: int = 0):
        super().__init__(message)
        self.problems = problems or []
        self.calls = calls  # Gemini calls made before giving up


def fixture_key(block_id: str, timestep: str) -> str:
    return f"advisory__gemini-{block_id}__{compact_timestep(timestep)}"


# --- Suggestions -------------------------------------------------------------------------------


def suggestions(timestep: str) -> AdvisorySuggestions:
    if timestep == LIVE:
        raise NotImplementedError("timestep=live is not implemented yet")
    scores = [f.properties for f in risk.get_scores(timestep).features]
    picked = sorted((p for p in scores if p.score >= SUGGEST_MIN_SCORE), key=lambda p: -p.score)
    return AdvisorySuggestions(
        timestep=timestep,
        threshold=SUGGEST_MIN_SCORE,
        blocks=[
            AdvisorySuggestion(block_id=p.block_id, block_name=p.block_name, score=p.score)
            for p in picked
        ],
    )


# --- Generation --------------------------------------------------------------------------------


def evaluate(raw: dict, keys: set[str]) -> tuple[AdvisoryTexts | None, str | None, dict]:
    """(templates, None, {}) if the draft passes; else (None, audit action, details)."""
    try:
        draft = gemini.GeminiDraft.model_validate(raw)
        templates = AdvisoryTexts.model_validate(draft.model_dump())
    except ValidationError as e:
        return None, "invalid_response", {"errors": [err["msg"] for err in e.errors()][:5]}
    problems = render.check(templates, keys)
    if not problems:
        return templates, None, {}
    kind = (
        "number_check_failed"
        if any(p.kind in ("digit", "number_word") for p in problems)
        else "invalid_response"
    )
    offending = {}
    for p in problems:
        t = getattr(templates, p.language)
        text = (
            t.headline
            if p.field == "headline"
            else t.body
            if p.field == "body"
            else t.actions[int(p.field[8:-1])]
        )
        offending[f"{p.language}.{p.field}"] = text
    return None, kind, {"problems": [str(p) for p in problems], "text": offending}


def _retry_note(details: dict) -> str:
    return (
        "\n\nYour previous draft was rejected: "
        + "; ".join(details.get("problems") or details.get("errors") or [])
        + ". Rewrite it following the rules exactly: no digits or number words, and only "
        "placeholders from the list."
    )


def generate_live(
    facts: Facts,
    actor: str | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    before_call: Callable[[], None] | None = None,
) -> tuple[AdvisoryTexts, dict, int]:
    """Call Gemini until a draft passes (at most `max_attempts`). Returns (templates, raw,
    calls). Failures are audited (advisory_id null) and raise DraftRejected. `before_call` runs
    before every call (the fixture script paces calls with it)."""
    settings = get_settings()
    if not settings.is_configured("GEMINI_API_KEY"):
        raise GeminiUnavailable(
            f"No cached Gemini response for {facts.block_name} ({facts.block_id}) at "
            f"{facts.timestep}, and GEMINI_API_KEY is not set"
        )
    keys = {c.key for c in facts.citations}
    message = user_message(facts)
    last: dict = {}
    for attempt in range(1, max_attempts + 1):
        if before_call is not None:
            before_call()
        try:
            raw = gemini.generate(SYSTEM_PROMPT, message, settings.GEMINI_API_KEY)
        except gemini.GeminiError as e:
            raise DraftRejected(str(e), calls=attempt) from e
        templates, action, details = evaluate(raw, keys)
        if templates is not None:
            return templates, raw, attempt
        last = details
        with store.transaction() as conn:
            store.audit(
                conn,
                None,
                action,
                actor,
                {
                    "block_id": facts.block_id,
                    "timestep": facts.timestep,
                    "attempt": attempt,
                    **details,
                },
            )
        message = user_message(facts) + _retry_note(details)
    raise DraftRejected(
        f"Gemini's draft for {facts.block_name} at {facts.timestep} failed the checks "
        f"{max_attempts} times",
        last.get("problems") or last.get("errors"),
        calls=max_attempts,
    )


def _templates_for(facts: Facts, actor: str | None) -> tuple[AdvisoryTexts, str, int]:
    """(templates, source, attempts): the cached response in DEMO_MODE if present and valid,
    else a live call."""
    try:
        cached = load_fixture(fixture_key(facts.block_id, facts.timestep))
    except FileNotFoundError:
        cached = None
    if cached is not None:
        templates, action, details = evaluate(cached, {c.key for c in facts.citations})
        if templates is not None:
            return templates, "fixture", 0
        with store.transaction() as conn:
            store.audit(
                conn,
                None,
                action,
                actor,
                {
                    "block_id": facts.block_id,
                    "timestep": facts.timestep,
                    "attempt": "fixture",
                    **details,
                },
            )
    templates, _, attempts = generate_live(facts, actor)
    return templates, "gemini", attempts


def create(block_id: str, timestep: str, actor: str | None = None) -> Advisory:
    if timestep == LIVE:
        raise NotImplementedError("timestep=live is not implemented yet")
    facts = build_facts(block_id, timestep)
    templates, source, attempts = _templates_for(facts, actor)
    props = AdvisoryProperties(
        id=str(uuid.uuid4()),
        block_id=block_id,
        block_name=facts.block_name,
        timestep=timestep,
        texts=render.render(templates, facts.citations),
        templates=templates,
        citations=facts.citations,
        status="draft",
        created_at=store.now(),
    )
    advisory = Advisory(id=props.id, properties=props)
    with store.transaction() as conn:
        store.save(conn, advisory)
        store.audit(conn, props.id, "generated", actor, {"source": source, "attempts": attempts})
    return advisory


# --- Queue -------------------------------------------------------------------------------------


def get(advisory_id: str) -> Advisory:
    advisory = store.get(advisory_id)
    if advisory is None:
        raise NotFound(f"no advisory {advisory_id!r}")
    return advisory


def _load_draft(conn, advisory_id: str) -> Advisory:
    advisory = store.load(conn, advisory_id)
    if advisory is None:
        raise NotFound(f"no advisory {advisory_id!r}")
    if advisory.properties.status != "draft":
        raise Locked(f"advisory is {advisory.properties.status}; only drafts can change")
    return advisory


def _with(advisory: Advisory, **changes) -> Advisory:
    props = AdvisoryProperties.model_validate({**advisory.properties.model_dump(), **changes})
    return Advisory(id=props.id, properties=props)


def edit(advisory_id: str, templates: AdvisoryTexts, actor: str | None = None) -> Advisory:
    problems: list[render.Problem] = []
    with store.transaction() as conn:
        advisory = _load_draft(conn, advisory_id)
        p = advisory.properties
        required = {
            lang: render.placeholder_keys(getattr(p.templates, lang)) for lang in render.LANGUAGES
        }
        problems = render.check(templates, {c.key for c in p.citations}, required)
        if problems:
            numbers = any(x.kind in ("digit", "number_word") for x in problems)
            action = "number_check_failed" if numbers else "invalid_response"
            details = {"problems": [str(x) for x in problems], "source": "edit"}
            store.audit(conn, advisory_id, action, actor, details)
        else:
            changed = [
                lang
                for lang in render.LANGUAGES
                if getattr(templates, lang) != getattr(p.templates, lang)
            ]
            advisory = _with(
                advisory,
                templates=templates.model_dump(),
                texts=render.render(templates, p.citations).model_dump(),
            )
            store.save(conn, advisory)
            store.audit(conn, advisory_id, "edited", actor, {"languages": changed})
    if problems:
        raise Invalid("the edit failed the checks", [str(x) for x in problems])
    return advisory


def parse_approver(approved_by: str) -> str:
    text = approved_by.strip()
    if not _APPROVER_RE.match(text):
        raise Invalid(
            'approved_by must be "Name (Designation)", with the designation one of '
            + ", ".join(DESIGNATIONS)
            + ', or "Other: <role>"'
        )
    return text


def approve(advisory_id: str, approved_by: str) -> Advisory:
    approver = parse_approver(approved_by)
    with store.transaction() as conn:
        advisory = _with(
            _load_draft(conn, advisory_id),
            status="approved",
            approved_by=approver,
            approved_at=store.now(),
        )
        store.save(conn, advisory)
        store.audit(conn, advisory_id, "approved", approver)
    return advisory


def reject(advisory_id: str, reason: str, actor: str | None = None) -> Advisory:
    reason = reason.strip()
    if not reason:
        raise Invalid("a reason is required to reject an advisory")
    with store.transaction() as conn:
        advisory = _with(
            _load_draft(conn, advisory_id),
            status="rejected",
            rejection_reason=reason,
            rejected_at=store.now(),
        )
        store.save(conn, advisory)
        store.audit(conn, advisory_id, "rejected", actor, {"reason": reason})
    return advisory


def new_draft(advisory_id: str, actor: str | None = None) -> Advisory:
    with store.transaction() as conn:
        source = store.load(conn, advisory_id)
        if source is None:
            raise NotFound(f"no advisory {advisory_id!r}")
        if source.properties.status == "draft":
            raise Locked("already a draft: edit it instead")
        p = source.properties
        props = AdvisoryProperties(
            id=str(uuid.uuid4()),
            block_id=p.block_id,
            block_name=p.block_name,
            timestep=p.timestep,
            texts=p.texts,
            templates=p.templates,
            citations=p.citations,
            status="draft",
            created_from=p.id,
            created_at=store.now(),
        )
        advisory = Advisory(id=props.id, properties=props)
        store.save(conn, advisory)
        store.audit(conn, props.id, "new_draft", actor, {"from": p.id})
        store.audit(conn, p.id, "copied", actor, {"to": props.id})
    return advisory
