"""Pregenerate Gemini advisory drafts for the DEMO_MODE fixtures. LIVE API CALLS.

Run from the repo root:  api\\.venv\\Scripts\\python api\\scripts\\build_advisory_fixtures.py

For every block suggested (risk score >= service.SUGGEST_MIN_SCORE) at T-6, T-3 and T-0, calls
Gemini once (plus one retry if the draft fails the number check), paced at GEMINI_RPM calls a
minute and capped by --max-calls, and writes the raw structured response that passed, with the
text values it refers to (service.fixture_payload; the staleness check compares them), to
api/data/demo/advisory__gemini-<census_code>__<ts>.json. Facts come from the DEMO_MODE data, so
the fixtures match what the demo serves. Failures are written to the audit log
(api/data/state/tempest.db) and printed. Pairs that already have a fixture are skipped unless
--all. When Gemini answers 503 (overloaded), the script waits BACKOFF_503_S and tries the same
pair again; every attempt, failed or not, counts towards --max-calls. A 429 (quota exhausted)
stops the run at once and lists the pairs still to generate.
"""

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

os.environ["DEMO_MODE"] = "true"  # facts from the demo fixtures; Gemini is still called live
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.advisory import gemini, service, store  # noqa: E402
from app.advisory.facts import build_facts  # noqa: E402
from app.core.demo import DEMO_DIR  # noqa: E402
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


@dataclass
class Run:
    calls: int = 0
    written: list[tuple[str, str, int]] = field(default_factory=list)  # (name, ts, calls)
    failed: list[tuple[str, str, str]] = field(default_factory=list)  # (name, ts, reason)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # budget used up
    # Set when a 429 stopped the run: the pair that got it and every pair after it.
    remaining: list[tuple[str, str]] = field(default_factory=list)


def _status(e: service.DraftRejected) -> int | None:
    return e.__cause__.status if isinstance(e.__cause__, gemini.GeminiError) else None


def run(
    todo: list[tuple[str, str, str]],
    max_calls: int,
    write: Callable[[str, str, dict], None],
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Run:
    """Generate each (block_id, name, timestep) pair within max_calls Gemini calls."""
    result = Run()
    last_call: float | None = None

    def pace() -> None:  # at most GEMINI_RPM calls a minute
        nonlocal last_call
        if last_call is not None:
            wait = last_call + 60 / GEMINI_RPM - clock()
            if wait > 0:
                sleep(wait)
        last_call = clock()

    for i, (block_id, name, ts) in enumerate(todo):
        while True:
            budget = min(service.MAX_ATTEMPTS, max_calls - result.calls)
            if budget <= 0:
                result.skipped.append((name, ts))
                print(f"  SKIPPED {name} {ts}: call budget used up")
                break
            facts = build_facts(block_id, ts)
            try:
                _, raw, used = service.generate_live(
                    facts, actor="build_advisory_fixtures", max_attempts=budget, before_call=pace
                )
            except service.DraftRejected as e:
                result.calls += e.calls
                if _status(e) == 429:  # quota exhausted: every further call would fail too
                    result.remaining = [(n, t) for _, n, t in todo[i:]]
                    print(f"  429 for {name} {ts} (call {result.calls}): quota exhausted, stopping")
                    return result
                if _status(e) == 503:
                    print(
                        f"  503 for {name} {ts} (call {result.calls}); wait {BACKOFF_503_S:.0f} s"
                    )
                    sleep(BACKOFF_503_S)
                    continue
                result.failed.append((name, ts, f"{str(e)[:160]} {e.problems}"))
                print(f"  FAILED {name} {ts} after {e.calls} call(s): {str(e)[:160]} {e.problems}")
                break
            result.calls += used
            write(block_id, ts, service.fixture_payload(raw, facts))
            result.written.append((name, ts, used))
            print(f"  {name:<14} {ts}  calls {used}")
            break
    return result


def write_fixture(block_id: str, ts: str, raw: dict) -> None:
    path = DEMO_DIR / f"{service.fixture_key(block_id, ts)}.json"
    text = json.dumps(raw, ensure_ascii=False, indent=1)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-calls", type=int, default=16, help="hard cap on Gemini calls")
    parser.add_argument("--all", action="store_true", help="redo pairs that have a fixture")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    todo = [
        (block_id, name, ts)
        for block_id, name, ts in pairs()
        if args.all or not (DEMO_DIR / f"{service.fixture_key(block_id, ts)}.json").is_file()
    ]
    print(f"{len(todo)} block-timestep pairs to generate; at most {args.max_calls} Gemini calls")
    first_event = max((e.id for e in store.events()), default=0)
    result = run(todo, args.max_calls, write_fixture)
    print(f"Gemini calls made: {result.calls}")
    print(f"Written: {len(result.written)}, failed: {len(result.failed)}, "
          f"skipped: {len(result.skipped)}")  # fmt: skip
    if result.remaining:
        print(f"Stopped by a 429; {len(result.remaining)} pair(s) left:")
        for name, ts in result.remaining:
            print(f"  {name} {ts}")
    failures = [e for e in store.events() if e.id > first_event and e.advisory_id is None]
    print(f"Drafts refused by the checks: {len(failures)}")
    for e in failures:
        print(f"  {e.action}: {e.details}")


if __name__ == "__main__":
    main()
