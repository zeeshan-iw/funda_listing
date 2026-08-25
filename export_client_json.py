#!/usr/bin/env python3
"""Turn a crawl's JSONL output into a client-facing JSON deliverable.

    python3 export_client_json.py results/immoweb_<timestamp>.jsonl

Writes three files next to the input, keeping the region/scope from the
crawl's filename and spelling out what each one is:

    <name>_pretty.json      indented JSON array — readable, but large
    <name>_compact.json.gz  same data, minified + gzipped (~10x smaller);
                            this is the one to send
    <name>_report.txt       per-field fill rate, so the client can see which
                            fields immoweb genuinely leaves empty rather than
                            assuming the scraper dropped them

The `raw` key is stripped if present — it duplicates the whole payload and
is only useful for debugging the mapping.

Every empty value (null/""/[]/{}) is written as the string "unspecified" in
the deliverables: immoweb's own detail pages render exactly these fields as
"Not specified", and a file full of nulls reads as data the scraper lost.
The crawler's JSONL keeps raw nulls — that is the source-faithful artifact
this script transforms.
"""

import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

EMPTY = (None, "", [], {})
UNSPECIFIED = "unspecified"


def to_unspecified(value):
    """Recursively replace empty leaves with "unspecified"."""
    if isinstance(value, dict):
        return {k: to_unspecified(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_unspecified(v) for v in value]
    if value in EMPTY:
        return UNSPECIFIED
    return value


def load(path: Path):
    rows = []
    for lineno, line in enumerate(path.open(encoding="utf8"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"  ! skipping malformed line {lineno}: {e}", file=sys.stderr)
    return rows


def fill_rates(rows):
    seen, filled = set(), defaultdict(int)
    for r in rows:
        for k, v in r.items():
            if k == "raw":
                continue
            if k == "feature" and isinstance(v, dict):
                for fk, fv in v.items():
                    name = f"feature.{fk}"
                    seen.add(name)
                    if fv not in EMPTY:
                        filled[name] += 1
                continue
            seen.add(k)
            if v not in EMPTY:
                filled[k] += 1
    return seen, filled


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"no such file: {src}", file=sys.stderr)
        return 1

    rows = load(src)
    if not rows:
        print("no rows loaded", file=sys.stderr)
        return 1

    # De-duplicate on listing id, keeping the last occurrence. Price-band
    # slices can overlap at the boundaries on large crawls.
    by_id, order = {}, []
    for r in rows:
        rid = r.get("id")
        if rid is None:
            continue
        if rid not in by_id:
            order.append(rid)
        by_id[rid] = {k: v for k, v in r.items() if k != "raw"}
    listings = [by_id[i] for i in order]
    # Deliverables say "unspecified" where immoweb publishes no value; the
    # fill-rate report still counts those fields as not filled.
    out_rows = [to_unspecified(r) for r in listings]

    # Drop the crawler's "_raw" marker so the deliverables read as
    # <region>_<scope>_<time>_pretty.json rather than "..._raw_pretty.json".
    stem = src.stem[:-4] if src.stem.endswith("_raw") else src.stem

    out = src.with_name(f"{stem}_pretty.json")
    with out.open("w", encoding="utf8") as fh:
        json.dump(out_rows, fh, indent=2, ensure_ascii=False)

    gz = src.with_name(f"{stem}_compact.json.gz")
    with gzip.open(gz, "wt", encoding="utf8") as fh:
        json.dump(out_rows, fh, separators=(",", ":"), ensure_ascii=False)

    seen, filled = fill_rates(listings)
    n = len(listings)
    report = src.with_name(f"{stem}_report.txt")
    with report.open("w", encoding="utf8") as fh:
        fh.write(f"immoweb export — {n} unique listings\n")
        fh.write(f"source: {src.name}\n")
        fh.write(f"fields per listing: {len(seen)}\n\n")
        fh.write("field fill rates (share of listings where the field has a value;\n")
        fh.write("a low rate means immoweb itself has no value, not a scraping gap;\n")
        fh.write('fields immoweb leaves empty appear as "unspecified" in the JSON)\n\n')
        for key in sorted(seen, key=lambda k: (-filled[k], k)):
            fh.write(f"  {key:<50} {100.0 * filled[key] / n:6.1f}%  ({filled[key]})\n")

    dupes = len(rows) - n
    print(f"listings written  : {n}" + (f"  ({dupes} duplicate rows merged)" if dupes else ""))
    print(f"fields per listing: {len(seen)}")
    print(f"pretty (readable) : {out.name}  ({out.stat().st_size / 1e6:.1f} MB)")
    print(f"compact (to send) : {gz.name}  ({gz.stat().st_size / 1e6:.1f} MB)")
    print(f"fill-rate report  : {report.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
