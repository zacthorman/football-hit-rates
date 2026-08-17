"""
Build an index page listing every report, for GitHub Pages.

    python make_index.py

Writes index.html at the project root, linking to everything in reports/.
GitHub Pages serves that as the site's front page, so you send your mate one
URL and he picks the fixture himself rather than you sending files.

Run it after building reports, then commit and push.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
REPORTS = ROOT / "reports"


def read_report(path: Path) -> tuple[str, int, list[str]]:
    """Title, fixture count and fixture names, read off a built report.

    The whole file is read in one go rather than just the start: the inlined
    CSS runs to several thousand characters, so the heading is nowhere near
    the top. That was a real bug here, and the symptom was every report being
    listed under its filename.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return path.stem, 1, []

    match = re.search(r'<h1 id="title">(.*?)</h1>', text)
    title = html.unescape(match.group(1)) if match else path.stem

    names: list[str] = []
    payload = re.search(r"const ALL = (\{.*?\});\n", text, re.S)
    if payload:
        try:
            fixtures = json.loads(payload.group(1)).get("fixtures", [])
            names = [
                f"{f['fixture']['home']} v {f['fixture']['away']}" for f in fixtures
            ]
        except (json.JSONDecodeError, ValueError, KeyError):
            names = []

    return title, max(1, len(names)), names


def main() -> None:
    if not REPORTS.exists():
        raise SystemExit("No reports/ folder yet. Build a report first.")

    files = sorted(
        REPORTS.glob("*.html"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise SystemExit("No reports found in reports/.")

    rows = []
    for path in files:
        built = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        title, count, names = read_report(path)

        if count > 1:
            heading = f"{count} fixtures"
            detail = ", ".join(names[:4]) + (" and more" if len(names) > 4 else "")
        else:
            heading = title
            detail = ""

        meta = f'built {built.strftime("%d %b %Y, %H:%M")} UTC'
        if detail:
            meta = f"{html.escape(detail)} &middot; {meta}"

        rows.append(
            f'<li><a href="reports/{html.escape(path.name)}">'
            f"{html.escape(heading)}</a>"
            f'<span class="meta">{meta}</span></li>'
        )

    generated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Football hit rates</title>
<style>
:root {{
  color-scheme: light;
  --surface: #fcfcfb; --page: #f9f9f7;
  --text: #0b0b0b; --muted: #898781;
  --border: rgba(11,11,11,0.10); --grid: #e1e0d9;
  --link: #2a78d6;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    color-scheme: dark;
    --surface: #1a1a19; --page: #0d0d0d;
    --text: #ffffff; --muted: #898781;
    --border: rgba(255,255,255,0.10); --grid: #2c2c2a;
    --link: #3987e5;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 48px 20px;
  background: var(--page); color: var(--text);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 15px; line-height: 1.5;
}}
.wrap {{ max-width: 680px; margin: 0 auto; }}
h1 {{ font-size: 26px; font-weight: 650; margin: 0 0 6px; letter-spacing: -0.01em; }}
.sub {{ color: var(--muted); font-size: 14px; margin: 0 0 28px; }}
ul {{ list-style: none; margin: 0; padding: 0;
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 10px; overflow: hidden; }}
li {{ border-bottom: 1px solid var(--grid); }}
li:last-child {{ border-bottom: 0; }}
li a {{ display: block; padding: 14px 18px 6px; color: var(--link);
        text-decoration: none; font-weight: 600; }}
li a:hover {{ text-decoration: underline; }}
.meta {{ display: block; padding: 0 18px 14px; color: var(--muted); font-size: 13px; }}
footer {{ margin-top: 24px; color: var(--muted); font-size: 13px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Football hit rates</h1>
  <p class="sub">Team and player hit rates by fixture, from SofaScore data.</p>
  <ul>
    {chr(10).join("    " + row for row in rows)}
  </ul>
  <footer>
    Index built {generated}. Each report is a snapshot: the numbers are frozen
    at the moment it was generated.
  </footer>
</div>
</body>
</html>
"""

    out = ROOT / "index.html"
    out.write_text(page, encoding="utf-8")
    print(f"Indexed {len(files)} report(s) into {out}")


if __name__ == "__main__":
    main()
