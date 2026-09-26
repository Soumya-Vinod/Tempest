"""Add Bengali and Hindi block names to api/data/reference/s24p_blocks.csv from Wikidata.

Run from the repo root:
    api\\.venv\\Scripts\\python api\\scripts\\build_s24p_block_names.py [--refresh]

One SPARQL query: the bn and hi labels (rdfs:label) of the items found by P5578 (Census 2011
code), the same 29 items the population comes from. The response is cached in api/data/raw/
(git-ignored); --refresh re-downloads it. A block without a label gets an empty cell and is
named in the CSV header; advisories then fall back to the English name.
"""

import argparse
import json
import sys
import textwrap
import time
from pathlib import Path

import httpx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import API_DIR  # noqa: E402

RAW = API_DIR / "data" / "raw"
LOOKUP_CSV = API_DIR / "data" / "reference" / "s24p_blocks.csv"
WIKIDATA_JSON = RAW / "wikidata-s24p-labels.json"
USER_AGENT = "Tempest/0.1 risk-block-names (+https://github.com/Soumya-Vinod/Tempest)"
LANGUAGES = ("bn", "hi")
# Wikidata's labels carry the kind of unit ("… community development block"); advisory templates
# add their own word for "block" after the name, so the suffix is dropped.
LABEL_SUFFIXES = {"bn": " সমষ্টি উন্নয়ন ব্লক", "hi": " सामुदायिक विकास खंड"}

NAMES_NOTE = """\
# name_bn, name_hi: Bengali and Hindi labels (rdfs:label) of each block's Wikidata item (found by
#   P5578 = census2011_code), retrieved {date}, with the suffix "community development block"
#   (bn সমষ্টি উন্নয়ন ব্লক) removed. Used to fill the block name in advisories.
{summary}"""


def wikidata_labels(codes: list[str], refresh: bool) -> dict[str, dict[str, str]]:
    """census code -> {language: label}."""
    if refresh or not WIKIDATA_JSON.exists():
        values = " ".join(f'"{c}"' for c in codes)
        langs = ", ".join(f'"{lang}"' for lang in LANGUAGES)
        query = (
            "SELECT ?code ?label WHERE { VALUES ?code { " + values + " } "
            "?item wdt:P5578 ?code ; rdfs:label ?label . "
            f"FILTER(LANG(?label) IN ({langs})) }}"
        )
        r = httpx.get(
            "https://query.wikidata.org/sparql",
            params={"query": query, "format": "json"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
            timeout=120,
        )
        r.raise_for_status()
        WIKIDATA_JSON.write_text(json.dumps({"query": query, "response": r.json()}), "utf-8")
    rows = json.loads(WIKIDATA_JSON.read_text("utf-8"))["response"]["results"]["bindings"]
    out: dict[str, dict[str, str]] = {}
    for b in rows:
        label = b["label"]
        out.setdefault(b["code"]["value"], {})[label["xml:lang"]] = label["value"]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="re-download the cached query")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # Bengali / Hindi on a cp1252 Windows console

    lines = LOOKUP_CSV.read_text("utf-8").splitlines()
    lookup = pd.read_csv(LOOKUP_CSV, comment="#", dtype=str, keep_default_na=False)
    codes = lookup["census2011_code"].tolist()
    labels = wikidata_labels(codes, args.refresh)

    missing: dict[str, list[str]] = {lang: [] for lang in LANGUAGES}
    for lang in LANGUAGES:
        column = []
        for code, name in zip(codes, lookup["block_name"], strict=True):
            label = labels.get(code, {}).get(lang, "").removesuffix(LABEL_SUFFIXES[lang])
            if not label:
                missing[lang].append(name)
            column.append(label)
        lookup[f"name_{lang}"] = column
    columns = ["census2011_code", "block_name", "name_bn", "name_hi"]
    for code, name, bn, hi in lookup[columns].values:
        print(f"{code} {name:<22} {bn or '-':<24} {hi or '-'}")

    gaps = "; ".join(f"{lang}: {', '.join(m)}" for lang, m in missing.items() if m)
    summary = "\n".join(
        textwrap.wrap(
            f"MISSING (empty; English is used): {gaps}." if gaps else "No label missing.",
            width=96,
            initial_indent="#   ",
            subsequent_indent="#   ",
            break_on_hyphens=False,
        )
    )
    note = NAMES_NOTE.format(date=time.strftime("%Y-%m-%d"), summary=summary)
    # Drop a previous names note (its continuation lines follow the first line).
    kept, skipping = [], False
    for h in [line for line in lines if line.startswith("#")]:
        if h.startswith("# name_bn"):
            skipping = True
            continue
        if skipping and h.startswith("#   "):
            continue
        skipping = False
        kept.append(h)
    body = lookup.to_csv(index=False, lineterminator="\n")
    text = "\n".join([*kept, *note.splitlines()]) + "\n" + body
    LOOKUP_CSV.write_text(text, encoding="utf-8", newline="\n")  # LF, as committed
    print(f"\nwrote {LOOKUP_CSV.name}: {gaps or 'no label missing'}")


if __name__ == "__main__":
    main()
