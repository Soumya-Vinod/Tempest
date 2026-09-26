"""Advisory generation and the approval queue (contracts.md §4.5, §5).

Generate: engine facts -> Gemini (one call per block and timestep, en + bn + hi) -> number check
-> placeholders filled -> a draft. In DEMO_MODE a cached Gemini response
(advisory__gemini-<census_code>__<ts>) is used when there is one; otherwise the live key if it is
set, else 503. A cached response is stale when the engines have changed its meaning since it was
generated: it refers to a {{key}} the current facts don't have, or a text value it refers to (a
name, cause or route, stored with it under CITED_TEXT_KEY) differs now, or it has no stored
values. A stale response is audited and the live / 503 path is used. Numbers may change: they
are filled at render time.
A draft failing the number check is retried once, then refused (502); each failure is written to
the audit log. If Gemini answers 429 (quota) or, after one retry ~2 s later, 503 (overloaded),
the draft comes from the Groq fallback instead (providers.py; only with GROQ_API_KEY), under the
same checks; every draft records generated_by, and the fallback's reason is audited. The fixture
script never falls back: demo fixtures are Gemini's only.

Rules: only drafts can be edited, approved or rejected (else 409). Edits are checked like
Gemini's drafts, and can't remove a placeholder. Approval needs "Name (Designation)"; rejection
needs a reason. "New draft from this" copies a finished advisory into a new draft. Every action
is audited.
"""

import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from app.advisory import gemini, providers, render, store
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
    GeneratedBy,
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
    """The model's drafts failed the checks on every attempt, or the call failed (502)."""

    def __init__(
        self,
        message: str,
        problems: list[str] | None = None,
        calls: int = 0,
        statuses: list[int | None] | None = None,
    ):
        super().__init__(message)
        self.problems = problems or []
        self.calls = calls  # model calls made before giving up
        self.statuses = statuses or []  # HTTP statuses of the failed calls (e.g. [503, 503])


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


FALLBACK_STATUS = {429, 503}
RETRY_503_AFTER_S = 2.0
sleep = time.sleep  # tests replace this


@dataclass(frozen=True)
class Generated:
    templates: AdvisoryTexts
    raw: dict  # the structured response that passed
    calls: int  # model calls made, all providers
    generated_by: GeneratedBy
    fallback_reason: str | None = None  # e.g. "gemini 429", "gemini 503 x2"


def _status(e: BaseException | None) -> int | None:
    return getattr(e, "status", None)


def _draft(
    provider: providers.Provider,
    facts: Facts,
    actor: str | None,
    max_attempts: int,
    before_call: Callable[[], None] | None,
    retry_503: bool = False,
) -> tuple[AdvisoryTexts, dict, int]:
    """Call one provider until a draft passes the checks (at most `max_attempts` drafts). With
    `retry_503`, a 503 is retried once after RETRY_503_AFTER_S (that call counts too). A failed
    call raises DraftRejected from the provider's error (its .status); `calls` counts every
    call. Drafts failing the checks are audited (advisory_id null)."""
    settings = get_settings()
    name = provider.generated_by.provider.capitalize()
    keys = {c.key for c in facts.citations}
    message = user_message(facts)
    last: dict = {}
    calls = 0
    retried_503 = False
    attempt = 1
    while attempt <= max_attempts:
        if before_call is not None:
            before_call()
        calls += 1
        try:
            raw = providers.call(provider, SYSTEM_PROMPT, message, settings)
        except provider.error as e:
            if retry_503 and _status(e) == 503 and not retried_503:
                retried_503 = True
                sleep(RETRY_503_AFTER_S)
                continue
            statuses = [503] * retried_503 + [_status(e)]
            raise DraftRejected(str(e), calls=calls, statuses=statuses) from e
        templates, action, details = evaluate(raw, keys)
        if templates is not None:
            return templates, raw, calls
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
                    "generated_by": provider.generated_by.model_dump(),
                    **details,
                },
            )
        message = user_message(facts) + _retry_note(details)
        attempt += 1
    raise DraftRejected(
        f"{name}'s draft for {facts.block_name} at {facts.timestep} failed the checks "
        f"{max_attempts} times",
        last.get("problems") or last.get("errors"),
        calls=calls,
    )


def _fallback_reason(e: DraftRejected) -> str | None:
    """ "gemini 429" / "gemini 503 x2" when Gemini's failure allows the fallback, else None."""
    statuses = getattr(e, "statuses", [])
    if not statuses or statuses[-1] not in FALLBACK_STATUS:
        return None
    if statuses == [503, 503]:
        return "gemini 503 x2"
    return "gemini " + ", ".join(str(s) for s in statuses)


def generate_live(
    facts: Facts,
    actor: str | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    before_call: Callable[[], None] | None = None,
    fallback: bool = True,
) -> Generated:
    """Gemini, until a draft passes (at most `max_attempts` drafts). With `fallback` (the app,
    not the fixture script): a 503 is retried once after ~2 s, and if Gemini still answers 503,
    or answers 429, Groq writes the draft instead under the same checks (if GROQ_API_KEY is
    set; else the Gemini error stands). Failures raise DraftRejected (502). `before_call` runs
    before every Gemini call (the fixture script paces calls with it)."""
    settings = get_settings()
    if not settings.is_configured("GEMINI_API_KEY"):
        raise GeminiUnavailable(
            f"No cached Gemini response for {facts.block_name} ({facts.block_id}) at "
            f"{facts.timestep}, and GEMINI_API_KEY is not set"
        )
    try:
        templates, raw, calls = _draft(
            providers.GEMINI_PROVIDER, facts, actor, max_attempts, before_call, retry_503=fallback
        )
        return Generated(templates, raw, calls, providers.GEMINI)
    except DraftRejected as e:
        reason = _fallback_reason(e)
        if not fallback or reason is None or not settings.is_configured("GROQ_API_KEY"):
            raise
        gemini_calls = e.calls
    groq = providers.groq(settings)
    try:
        templates, raw, calls = _draft(groq, facts, actor, max_attempts, None)
    except DraftRejected as e:
        e.calls += gemini_calls
        raise DraftRejected(f"{e} (Groq fallback after {reason})", e.problems, calls=e.calls) from e
    return Generated(templates, raw, gemini_calls + calls, groq.generated_by, reason)


CITED_TEXT_KEY = "_cited_text"  # in a Gemini fixture: {key: text value} its templates used


def _used_keys(raw: dict) -> set[str] | None:
    """Placeholders in a Gemini response, or None if it is not a valid draft."""
    try:
        templates = AdvisoryTexts.model_validate(
            gemini.GeminiDraft.model_validate(raw).model_dump()
        )
    except ValidationError:
        return None
    return set().union(
        *(render.placeholder_keys(getattr(templates, lang)) for lang in render.LANGUAGES)
    )


def fixture_payload(raw: dict, facts: Facts) -> dict:
    """What the fixture script writes: Gemini's response plus the text values it refers to."""
    used = _used_keys(raw) or set()
    cited = {c.key: c.value for c in facts.citations if c.key in used and isinstance(c.value, str)}
    return {**raw, CITED_TEXT_KEY: dict(sorted(cited.items()))}


def staleness(cached: dict, facts: Facts) -> dict | None:
    """Why a cached response no longer fits the facts (audit details), or None if it does. An
    invalid response is not called stale here; evaluate() reports it."""
    used = _used_keys(cached)
    if used is None:
        return None
    current = {c.key: c.value for c in facts.citations}
    if missing := sorted(used - current.keys()):
        return {"missing_keys": missing}
    stored = cached.get(CITED_TEXT_KEY)
    if not isinstance(stored, dict):
        return {"cited_text": "not stored"}
    changed = {
        k: {"cached": stored.get(k), "current": v}
        for k, v in sorted(current.items())
        if k in used and isinstance(v, str) and stored.get(k) != v
    }
    return {"changed_text": changed} if changed else None


def _templates_for(facts: Facts, actor: str | None) -> tuple[Generated, str]:
    """(templates, source, attempts): the cached response in DEMO_MODE if present, valid and not
    stale, else a live call (503 without a key)."""
    try:
        cached = load_fixture(fixture_key(facts.block_id, facts.timestep))
    except FileNotFoundError:
        cached = None
    keys = {c.key for c in facts.citations}
    if cached is not None and (why := staleness(cached, facts)):
        # AuditAction is a contract enum, so staleness is a reason under invalid_response.
        with store.transaction() as conn:
            store.audit(
                conn,
                None,
                "invalid_response",
                actor,
                {
                    "block_id": facts.block_id,
                    "timestep": facts.timestep,
                    "attempt": "fixture",
                    "reason": "stale_fixture",
                    **why,
                },
            )
        cached = None
    if cached is not None:
        templates, action, details = evaluate(cached, keys)
        if templates is not None:
            return Generated(templates, cached, 0, providers.GEMINI), "fixture"
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
    generated = generate_live(facts, actor)
    return generated, generated.generated_by.provider


def create(block_id: str, timestep: str, actor: str | None = None) -> Advisory:
    if timestep == LIVE:
        raise NotImplementedError("timestep=live is not implemented yet")
    facts = build_facts(block_id, timestep)
    generated, source = _templates_for(facts, actor)
    templates = generated.templates
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
        generated_by=generated.generated_by,
    )
    advisory = Advisory(id=props.id, properties=props)
    details = {
        "source": source,
        "attempts": generated.calls,
        "generated_by": generated.generated_by.model_dump(),
    }
    if generated.fallback_reason:
        details["fallback_reason"] = generated.fallback_reason
    with store.transaction() as conn:
        store.save(conn, advisory)
        store.audit(conn, props.id, "generated", actor, details)
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
            generated_by=p.generated_by,
            created_at=store.now(),
        )
        advisory = Advisory(id=props.id, properties=props)
        store.save(conn, advisory)
        store.audit(conn, props.id, "new_draft", actor, {"from": p.id})
        store.audit(conn, p.id, "copied", actor, {"to": props.id})
    return advisory
