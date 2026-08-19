"""
Rebuild every existing report's HTML from the data already inside it.

    python rerender.py                 # all reports
    python rerender.py laliga champ    # only ones whose name contains these

Every report carries its own dataset embedded in the page, so when report.py
changes there is no need to refetch anything from SofaScore. The payload is
read straight back out of the built file and re-rendered through the current
report.py. It takes about a second per report instead of twenty minutes, and
it touches the network zero times.

This exists because of a real problem: a report built last week is frozen with
last week's page code. New tabs, new controls, the back button and the deep
link from the index all live in report.py, so an old file silently ignores
them. That is what makes a link to one fixture open on a different one.

Run this after any change to report.py, then rebuild the index:

    python rerender.py && python make_index.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import report

# Note this file imports report, not hitrates. Re-rendering a saved page is a
# pure formatting job: the data is already in the file. Keeping the API stack
# out of this path means it still works on a machine that has never installed
# curl_cffi, which is exactly the situation it is most useful in.

ROOT = Path(__file__).parent
REPORTS = ROOT / "reports"

PAYLOAD = re.compile(r"const ALL = (\{.*?\});\n", re.S)


def payload_of(path: Path) -> dict | None:
    """The dataset embedded in a built report, or None if it cannot be read."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"  {path.name}: cannot read ({exc})")
        return None

    match = PAYLOAD.search(text)
    if not match:
        print(f"  {path.name}: no payload found, skipping")
        return None

    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        print(f"  {path.name}: payload will not parse ({exc}), skipping")
        return None


def main() -> None:
    if not REPORTS.exists():
        raise SystemExit("No reports/ folder yet.")

    wanted = [a.lower() for a in sys.argv[1:]]
    files = sorted(REPORTS.glob("*.html"))
    if wanted:
        files = [p for p in files if any(w in p.name.lower() for w in wanted)]

    if not files:
        raise SystemExit("Nothing matched.")

    done = failed = 0
    for path in files:
        data = payload_of(path)
        if data is None:
            failed += 1
            continue

        fixtures = data.get("fixtures", [])
        if not fixtures:
            print(f"  {path.name}: no fixtures in payload, skipping")
            failed += 1
            continue

        # Older payloads predate the periods map. Fall back rather than
        # crashing, since the whole point of this script is rescuing them.
        data.setdefault("periods", {"ALL": "Full match",
                                    "1ST": "First half", "2ND": "Second half"})

        report.write_report(data, path)
        print(f"  {path.name}: {len(fixtures)} fixture(s) re-rendered")
        done += 1

    print(f"\nRe-rendered {done} report(s)" + (f", {failed} skipped" if failed else ""))
    if done:
        print("Now run: python make_index.py")


if __name__ == "__main__":
    main()
