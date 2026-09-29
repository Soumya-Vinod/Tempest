"""Pregenerate advisory drafts for the DEMO_MODE fixtures. LIVE API CALLS.

Run from the repo root:
    api\\.venv\\Scripts\\python api\\scripts\\build_advisory_fixtures.py
        [--pairs "Namkhana:T-33,Gosaba:T-27"] [--allow-groq-fallback] [--max-calls N] [--all]

Which pairs: with --pairs, exactly those (block name or Census code, then a T-label such as
T-33 or an ISO replay timestep), regenerated even if a fixture exists. Without it, every block
suggested (horizon-24 risk >= service.SUGGEST_MIN_SCORE) at T-6, T-3 and T-0, skipping pairs
that already have a fixture unless --all.

Each pair: the model is called once (plus one retry if the draft fails the number check), paced
at GEMINI_RPM calls a minute, all calls capped by --max-calls. The facts are the DEMO_MODE ones,
combining what is cut off now with what is expected within 24 h (app/advisory/facts.py), so a
pre-landfall pair describes expected isolations with preparatory actions. The response that
passed is written to api/data/demo/advisory__gemini-<census_code>__<ts>.json with the text
values it refers to (service.fixture_payload; the staleness check compares them) and the model
that wrote it (`_generated_by`, shown in the UI).

Gemini: a 503 (overloaded) waits BACKOFF_503_S and tries the pair again. A 429 (quota
exhausted) stops the run and lists the pairs left.
--allow-groq-fallback: a pair that still gets 503 after the back-off, or a 429, is generated
with Groq instead (same prompt and checks; the fixture says "Fallback: Groq"), and after a 429
every remaining pair goes to Groq instead of stopping the run. Without it: Gemini only.
Every call, failed or not, counts towards --max-calls. A summary lists each pair, its provider
and pass / fail with the reason.
"""

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

os.environ["DEMO_MODE"] = "true"  # facts from the demo fixtures; Gemini is still called live
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.advisory import gemini, providers, service, store  # noqa: E402
from app.advisory.facts import build_facts  # noqa: E402
from app.core.demo import DEMO_DIR  # noqa: E402
from app.risk.blocks import load_blocks  # noqa: E402
from app.schemas import LANDFALL_TIMESTEP, REPLAY_TIMESTEPS  # noqa: E402

HOURS_BEFORE_LANDFALL = (6, 3, 0)
GEMINI_RPM = 3  # calls per minute, under the free tier's 5
BACKOFF_503_S = 60.0  # wait after a 503 before the next attempt


def timesteps() -> list[str]:
    i = REPLAY_TIMESTEPS.index(LANDFALL_TIMESTEP)
    return [REPLAY_TIMESTEPS[i - h // 3] for h in HOURS_BEFORE_LANDFALL]


def pairs() -> list[tuple[str, str, str]]:
    """(block_id, block_name, timestep) for every suggested block."""
    return [
        (b.block_id, b.block_name, ts) for ts in timesteps() for b in service.suggestions(ts).blocks
    ]


@dataclass(frozen=True)
class PairResult:
    name: str
    timestep: str
    provider: str | None  # "gemini", "groq", or None when not attempted
    ok: bool
    reason: str


@dataclass
class Run:
    calls: int = 0
    written: list[tuple[str, str, int]] = field(default_factory=list)  # (name, ts, calls)
    failed: list[tuple[str, str, str]] = field(default_factory=list)  # (name, ts, reason)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # budget used up
    # Set when a 429 stopped the run: the pair that got it and every pair after it.
    remaining: list[tuple[str, str]] = field(default_factory=list)
    summary: list[PairResult] = field(default_factory=list)


def _status(e: service.DraftRejected) -> int | None:
    cause = e.__cause__
    return cause.status if isinstance(cause, gemini.GeminiError | providers.GroqError) else None


def run(
    todo: list[tuple[str, str, str]],
    max_calls: int,
    write: Callable[[str, str, dict], None],
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    allow_groq: bool = False,
) -> Run:
    """Generate each (block_id, name, timestep) pair within max_calls model calls."""
    result = Run()
    last_call: float | None = None
    groq_for_all = False  # after a Gemini 429, with allow_groq

    def pace() -> None:  # at most GEMINI_RPM calls a minute
        nonlocal last_call
        if last_call is not None:
            wait = last_call + 60 / GEMINI_RPM - clock()
            if wait > 0:
                sleep(wait)
        last_call = clock()

    def fail(name: str, ts: str, provider: str | None, reason: str) -> None:
        result.failed.append((name, ts, reason))
        result.summary.append(PairResult(name, ts, provider, False, reason))
        print(f"  FAILED {name} {ts} ({provider or '-'}): {reason}")

    for i, (block_id, name, ts) in enumerate(todo):
        facts = build_facts(block_id, ts)
        backed_off = False
        groq_for_pair = False
        while True:
            budget = min(service.MAX_ATTEMPTS, max_calls - result.calls)
            if budget <= 0:
                result.skipped.append((name, ts))
                result.summary.append(PairResult(name, ts, None, False, "call budget used up"))
                print(f"  SKIPPED {name} {ts}: call budget used up")
                break
            provider = "groq" if groq_for_all or groq_for_pair else "gemini"
            try:
                if provider == "groq":
                    generated = service.generate_groq(
                        facts, "build_advisory_fixtures", max_attempts=budget, before_call=pace
                    )
                else:
                    generated = service.generate_live(
                        facts,
                        actor="build_advisory_fixtures",
                        max_attempts=budget,
                        before_call=pace,
                        fallback=False,  # the script decides about Groq itself
                    )
            except service.DraftRejected as e:
                result.calls += e.calls
                status = _status(e)
                if provider == "gemini" and status == 429:
                    if allow_groq:
                        groq_for_all = True
                        print(f"  429 for {name} {ts}: Gemini quota exhausted; Groq from here on")
                        continue
                    result.remaining = [(n, t) for _, n, t in todo[i:]]
                    for n, t in result.remaining:
                        result.summary.append(
                            PairResult(n, t, None, False, "not attempted: Gemini quota (429)")
                        )
                    print(f"  429 for {name} {ts} (call {result.calls}): quota exhausted, stopping")
                    return result
                if provider == "gemini" and status == 503:
                    if allow_groq and backed_off:
                        groq_for_pair = True
                        print(f"  503 again for {name} {ts}: this pair goes to Groq")
                        continue
                    print(
                        f"  503 for {name} {ts} (call {result.calls}); wait {BACKOFF_503_S:.0f} s"
                    )
                    sleep(BACKOFF_503_S)
                    backed_off = True
                    continue
                reason = str(e)[:160] + (f" {e.problems}" if e.problems else "")
                fail(name, ts, provider, reason)
                break
            result.calls += generated.calls
            write(
                block_id, ts, service.fixture_payload(generated.raw, facts, generated.generated_by)
            )
            result.written.append((name, ts, generated.calls))
            result.summary.append(
                PairResult(name, ts, provider, True, f"written ({generated.calls} call(s))")
            )
            print(f"  {name:<14} {ts}  {provider}  calls {generated.calls}")
            break
    return result


# --- --pairs --------------------------------------------------------------------------------------

_T_LABEL = re.compile(r"^T-(\d+)$", re.IGNORECASE)


def _norm(name: str) -> str:
    return re.sub(r"[\s_-]+", "", name).casefold()


def parse_pairs(text: str, codes: list[str], names: list[str]) -> list[tuple[str, str, str]]:
    """ "Namkhana:T-33,02435:2020-05-19T09:00:00Z" -> [(block_id, block_name, timestep)].
    A block is a name (case, spaces and hyphens ignored) or a Census code; a time is a T-label
    (hours before landfall, a multiple of 3 up to 72) or an ISO replay timestep."""
    by_name = {_norm(n): (c, n) for c, n in zip(codes, names, strict=True)}
    by_code = dict(zip(codes, names, strict=True))
    landfall = REPLAY_TIMESTEPS.index(LANDFALL_TIMESTEP)
    out: list[tuple[str, str, str]] = []
    for item in (part.strip() for part in text.split(",")):
        if not item:
            continue
        block, sep, when = item.partition(":")  # ISO times contain ":" too: split at the first
        block, when = block.strip(), when.strip()
        if not sep or not block or not when:
            raise ValueError(f"{item!r}: expected <block>:<time>, e.g. Namkhana:T-33")
        if block in by_code:
            code, name = block, by_code[block]
        elif _norm(block) in by_name:
            code, name = by_name[_norm(block)]
        else:
            raise ValueError(f"{item!r}: unknown block {block!r} (a CD block name or Census code)")
        if m := _T_LABEL.match(when):
            hours = int(m.group(1))
            if hours % 3 or hours > 3 * landfall:
                raise ValueError(f"{item!r}: {when} is not a replay step (T-0 to T-72, every 3 h)")
            ts = REPLAY_TIMESTEPS[landfall - hours // 3]
        elif when in REPLAY_TIMESTEPS:
            ts = when
        else:
            raise ValueError(f"{item!r}: {when!r} is not a T-label or a replay timestep")
        if (code, name, ts) not in out:
            out.append((code, name, ts))
    if not out:
        raise ValueError("--pairs is empty")
    return out


def write_fixture(block_id: str, ts: str, raw: dict) -> None:
    path = DEMO_DIR / f"{service.fixture_key(block_id, ts)}.json"
    text = json.dumps(raw, ensure_ascii=False, indent=1)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def label(ts: str) -> str:
    return f"T-{(REPLAY_TIMESTEPS.index(LANDFALL_TIMESTEP) - REPLAY_TIMESTEPS.index(ts)) * 3}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-calls", type=int, default=20, help="hard cap on model calls")
    parser.add_argument("--all", action="store_true", help="redo pairs that have a fixture")
    parser.add_argument(
        "--pairs", help='explicit pairs, e.g. "Namkhana:T-33,Gosaba:T-27,02438:T-24"'
    )
    parser.add_argument(
        "--allow-groq-fallback",
        action="store_true",
        help="use Groq for a pair when Gemini answers 429, or 503 after the back-off",
    )
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.pairs:
        blocks = load_blocks()
        try:
            todo = parse_pairs(args.pairs, blocks.codes, blocks.names)
        except ValueError as e:
            parser.error(str(e))
    else:
        todo = [
            (block_id, name, ts)
            for block_id, name, ts in pairs()
            if args.all or not (DEMO_DIR / f"{service.fixture_key(block_id, ts)}.json").is_file()
        ]
    fallback = "Gemini, Groq fallback allowed" if args.allow_groq_fallback else "Gemini only"
    print(f"{len(todo)} pair(s); at most {args.max_calls} model calls; {fallback}")
    first_event = max((e.id for e in store.events()), default=0)
    result = run(todo, args.max_calls, write_fixture, allow_groq=args.allow_groq_fallback)

    print(f"\nModel calls made: {result.calls}")
    print("Summary:")
    for r in result.summary:
        provider = {"gemini": "Gemini", "groq": "Groq (fallback)", None: "-"}[r.provider]
        verdict = "PASS" if r.ok else "FAIL"
        print(f"  {r.name:<16} {label(r.timestep):<5} {provider:<16} {verdict}  {r.reason}")
    refused = [e for e in store.events() if e.id > first_event and e.advisory_id is None]
    if refused:
        print(f"Drafts refused by the checks along the way: {len(refused)}")
        for e in refused:
            print(f"  {e.action}: {(e.details or '')[:200]}")


if __name__ == "__main__":
    main()
