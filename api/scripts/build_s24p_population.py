"""Add Census 2011 population to api/data/reference/s24p_blocks.csv, cross-checked.

Run from the repo root:
    api\\.venv\\Scripts\\python api\\scripts\\build_s24p_population.py [--refresh]

Sources (responses cached in api/data/raw/, git-ignored; --refresh re-downloads):
- Wikidata P1082 (population) with point in time 2011, on the items found by P5578 (Census 2011
  code). Each value cites the Census PCA file DDW_PCA1917_2011_MDDS with UI.xlsx.
- census2011.co.in: the district's block list page, then each block's page (villages with their
  populations), fetched at least 1 s apart. A block counts as cross-checked only when the sum
  of its listed villages is within MAX_DIFF of the Wikidata figure. Many block pages list only
  part of their villages (e.g. Basanti: 1 row), so a lower sum means "not verifiable here", not a
  disagreement; those blocks are named as unverified in the CSV header.

The official PCA file (censusindia.gov.in) was not reachable on 2026-09-25 (http: connection
timeout; https: certificate verification failed), so it is not used.
"""

import argparse
import html
import json
import re
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
WIKIDATA_JSON = RAW / "wikidata-s24p-population.json"
BLOCK_LIST_HTML = RAW / "census2011coin-s24p-blocks.html"
BLOCK_PAGES = RAW / "census2011coin"
SITE = "https://www.census2011.co.in"
BLOCK_LIST_URL = f"{SITE}/data/district/17-south-twenty-four-parganas-west-bengal.html"
USER_AGENT = "Tempest/0.1 risk-population (+https://github.com/Soumya-Vinod/Tempest)"
MIN_INTERVAL_S = 1.2
MAX_DIFF = 0.005  # 0.5 %

POPULATION_NOTE = """\
# population_2011: Census of India 2011 total population of the CD block (rural + census towns;
#   statutory towns are not part of CD blocks). Source: Wikidata P1082 (point in time 2011), which
#   cites the Census PCA file DDW_PCA1917_2011_MDDS with UI.xlsx (the file itself was unreachable).
#   Cross-check (census2011.co.in, sum of the villages on each block page, retrieved {date}):
{summary}"""


def _text(cell: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", cell))).strip()


def _get(url: str) -> httpx.Response:
    r = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return r


def wikidata_population(codes: list[str], refresh: bool) -> dict[str, int]:
    if refresh or not WIKIDATA_JSON.exists():
        values = " ".join(f'"{c}"' for c in codes)
        query = (
            "SELECT ?code ?pop ?time WHERE { VALUES ?code { " + values + " } "
            "?item wdt:P5578 ?code . ?item p:P1082 ?st . ?st ps:P1082 ?pop . "
            "OPTIONAL { ?st pq:P585 ?time } }"
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
    out = {}
    for b in rows:
        if b.get("time", {}).get("value", "").startswith("2011"):
            out[b["code"]["value"]] = int(float(b["pop"]["value"]))
    return out


def census2011coin_population(codes: list[str], refresh: bool) -> dict[str, int]:
    if refresh or not BLOCK_LIST_HTML.exists():
        BLOCK_LIST_HTML.write_text(_get(BLOCK_LIST_URL).text, "utf-8")
    links = dict(
        (code.zfill(5), path)
        for path, code in re.findall(
            r'href="(/data/subdistrict/(\d+)-[^"]+\.html)"', BLOCK_LIST_HTML.read_text("utf-8")
        )
    )
    BLOCK_PAGES.mkdir(parents=True, exist_ok=True)
    out, last = {}, 0.0
    for code in codes:
        page = BLOCK_PAGES / f"{code}.html"
        if refresh or not page.exists():
            if code not in links:
                raise ValueError(f"no census2011.co.in page linked for block {code}")
            time.sleep(max(0.0, MIN_INTERVAL_S - (time.monotonic() - last)))
            page.write_text(_get(SITE + links[code]).text, "utf-8")
            last = time.monotonic()
        table = re.findall(r"<table.*?</table>", page.read_text("utf-8"), re.S)[0]
        cells = [
            re.findall(r"<td.*?</td>", row, re.S) for row in re.findall(r"<tr.*?</tr>", table, re.S)
        ]
        out[code] = sum(int(_text(c[3]).replace(",", "")) for c in cells if len(c) == 4)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="re-download cached sources")
    args = parser.parse_args()

    lines = LOOKUP_CSV.read_text("utf-8").splitlines()
    lookup = pd.read_csv(LOOKUP_CSV, comment="#", dtype=str)
    codes = lookup["census2011_code"].tolist()

    wd = wikidata_population(codes, args.refresh)
    c2 = census2011coin_population(codes, args.refresh)
    missing = [c for c in codes if c not in wd]
    if missing:
        raise SystemExit(f"no Wikidata 2011 population for {missing}")

    verified, unverified = [], []
    for code, name in zip(codes, lookup["block_name"], strict=True):
        diff = (c2[code] - wd[code]) / wd[code]
        ok = abs(diff) <= MAX_DIFF
        (verified if ok else unverified).append(name)
        status = "verified" if ok else "UNVERIFIED (village list on the page is partial)"
        print(f"{code} {name:<22} wikidata {wd[code]:>9,}  village sum {c2[code]:>9,}  {status}")

    summary = "\n".join(
        textwrap.wrap(
            f"verified (within 0.5 %): {len(verified)} of {len(codes)}: {', '.join(verified)}. "
            f"UNVERIFIED, the site's block page lists only part of the villages: "
            f"{len(unverified)}: {', '.join(unverified) or 'none'}.",
            width=96,
            initial_indent="#   ",
            subsequent_indent="#   ",
            break_on_hyphens=False,
        )
    )
    note = POPULATION_NOTE.format(date=time.strftime("%Y-%m-%d"), summary=summary)
    # Drop a previous population note (its continuation lines follow the first line).
    kept, skipping = [], False
    for h in [line for line in lines if line.startswith("#")]:
        if h.startswith("# population_2011"):
            skipping = True
            continue
        if skipping and h.startswith("#   "):
            continue
        skipping = False
        kept.append(h)
    lookup["population_2011"] = [str(wd[c]) for c in codes]
    body = lookup.to_csv(index=False, lineterminator="\n")
    text = "\n".join([*kept, *note.splitlines()]) + "\n" + body
    LOOKUP_CSV.write_text(text, encoding="utf-8", newline="\n")  # LF, as committed
    print(f"\nwrote {LOOKUP_CSV.name}: population_2011 from Wikidata; "
          f"{len(verified)} verified, {len(unverified)} unverified")  # fmt: skip


if __name__ == "__main__":
    main()
