"""
Build the front page: every upcoming fixture, soonest first.

    python make_index.py

Writes index.html at the project root. GitHub Pages serves that as the site's
front page, so you send your mate one URL and he picks the game himself.

This lists FIXTURES, not report files. A league round is one file holding ten
matches, and "premier-league-10-fixtures.html" tells you nothing about whether
Arsenal are playing tonight. So the payload of every report is read, each
fixture pulled out with its kick-off time, and the whole lot sorted by when
they actually start and grouped by day. Each one links straight to itself
inside its report, using the event id in the URL hash.

Kick-off times are rendered in the reader's own timezone by the browser, not
baked in here. The page ships unix timestamps and lets the device do it.

Run it after building reports, then commit and push.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
REPORTS = ROOT / "reports"


def read_fixtures(path: Path) -> list[dict]:
    """Every fixture inside one built report.

    The whole file is read rather than the first few thousand characters: the
    inlined CSS runs to several thousand on its own, so the payload is nowhere
    near the top. That was a real bug here once, and the symptom was every
    report being listed under its filename.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    payload = re.search(r"const ALL = (\{.*?\});\n", text, re.S)
    if not payload:
        return []

    try:
        data = json.loads(payload.group(1))
    except json.JSONDecodeError:
        return []

    out = []
    for entry in data.get("fixtures", []):
        fixture = entry.get("fixture", {})
        if not fixture.get("home") or not fixture.get("away"):
            continue
        out.append(
            {
                "id": fixture.get("id"),
                "home": fixture["home"],
                "away": fixture["away"],
                "competition": fixture.get("competition", "Football"),
                "kickoff": fixture.get("kickoff") or 0,
                "report": path.name,
                # Enough to show what the report actually carries, so you know
                # before clicking whether the player tables are in there.
                "players": bool(entry.get("players")),
                "adjusted": bool(entry.get("projection") or entry.get("tierProjection")),
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-played", action="store_true", dest="keep_played",
                        help="keep fixtures that have already kicked off")
    parser.add_argument("--prune", action="store_true",
                        help="delete report files with no upcoming fixtures left")
    args = parser.parse_args()

    if not REPORTS.exists():
        raise SystemExit("No reports/ folder yet. Build a report first.")

    files = sorted(REPORTS.glob("*.html"))
    if not files:
        raise SystemExit("No reports found in reports/.")

    now = datetime.now(tz=timezone.utc).timestamp()

    fixtures: list[dict] = []
    seen: set[tuple] = set()
    live_reports: set[str] = set()

    for path in files:
        for fixture in read_fixtures(path):
            if fixture["kickoff"] > now:
                live_reports.add(path.name)
            elif not args.keep_played:
                continue

            # The same match can appear in two reports, for instance when a
            # league round and a one-off build overlap. Keep the first.
            key = (fixture["home"], fixture["away"], fixture["kickoff"])
            if key in seen:
                continue
            seen.add(key)
            fixtures.append(fixture)

    fixtures.sort(key=lambda f: (f["kickoff"] or 1 << 62, f["home"]))

    competitions = sorted({f["competition"] for f in fixtures})
    generated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

    # A stamp that changes whenever any report changes, used to bust the
    # browser cache on the links below.
    stamp = str(int(max((p.stat().st_mtime for p in files), default=0)))

    payload = json.dumps(
        {"fixtures": fixtures, "competitions": competitions,
         "built": generated, "stamp": stamp},
        separators=(",", ":"),
    )

    page = PAGE.replace("__PAYLOAD__", payload)
    out = ROOT / "index.html"
    out.write_text(page, encoding="utf-8")

    print(f"Indexed {len(fixtures)} fixture(s) across {len(competitions)} "
          f"competition(s) into {out}")
    for competition in competitions:
        count = sum(1 for f in fixtures if f["competition"] == competition)
        print(f"  {competition}: {count}")

    dead = [p for p in files if p.name not in live_reports]
    if dead:
        print(f"\n{len(dead)} report(s) have no upcoming fixtures left:")
        for path in dead:
            print(f"  {path.name}")
        if args.prune:
            for path in dead:
                path.unlink()
            print("Deleted them. They rebuild from the cache in seconds.")
        else:
            print("Add --prune to delete their files too.")


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Football hit rates</title>
<style>
:root {
  color-scheme: light;
  --surface: #fcfcfb; --page: #f9f9f7; --raised: #ffffff;
  --text: #0b0b0b; --muted: #77756f;
  --border: rgba(11,11,11,0.10); --grid: #e8e7e1;
  --link: #2a78d6; --accent: #0b0b0b; --on-accent: #ffffff;
  --today: #c2410c;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --surface: #1a1a19; --page: #0d0d0d; --raised: #232322;
    --text: #ffffff; --muted: #8f8d87;
    --border: rgba(255,255,255,0.12); --grid: #2c2c2a;
    --link: #5ba3f5; --accent: #ffffff; --on-accent: #0b0b0b;
    --today: #fb923c;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 34px 18px 60px;
  background: var(--page); color: var(--text);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 15px; line-height: 1.5;
  -webkit-text-size-adjust: 100%;
}
.wrap { max-width: 760px; margin: 0 auto; }
h1 { font-size: 27px; font-weight: 660; margin: 0 0 5px; letter-spacing: -0.015em; }
.sub { color: var(--muted); font-size: 14px; margin: 0 0 20px; }

/* Filters. Sticky, because on a phone the list is long and the filter is
   the thing you reach for after scrolling, not before. */
.filters {
  position: sticky; top: 0; z-index: 5;
  background: var(--page); padding: 10px 0 12px;
  margin: 0 0 6px; border-bottom: 1px solid var(--border);
  display: flex; gap: 7px; flex-wrap: wrap; align-items: center;
}
.chip {
  appearance: none; cursor: pointer;
  background: var(--raised); color: var(--text);
  border: 1px solid var(--border); border-radius: 999px;
  padding: 7px 13px; font: inherit; font-size: 13.5px; font-weight: 550;
  white-space: nowrap;
}
.chip:hover { border-color: var(--muted); }
.chip[aria-pressed="true"] {
  background: var(--accent); color: var(--on-accent); border-color: var(--accent);
}
.chip .n { opacity: 0.55; margin-left: 5px; font-weight: 500; }
.search {
  flex: 1 1 150px; min-width: 130px;
  background: var(--raised); color: var(--text);
  border: 1px solid var(--border); border-radius: 999px;
  padding: 7px 13px; font: inherit; font-size: 13.5px;
}
.search::placeholder { color: var(--muted); }

.day {
  margin: 22px 0 8px; font-size: 13px; font-weight: 640;
  letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted);
}
.day.soon { color: var(--today); }

ul { list-style: none; margin: 0; padding: 0;
     background: var(--surface); border: 1px solid var(--border);
     border-radius: 11px; overflow: hidden; }
li { border-bottom: 1px solid var(--grid); }
li:last-child { border-bottom: 0; }
li a {
  display: flex; align-items: baseline; gap: 12px;
  padding: 13px 16px; color: inherit; text-decoration: none;
}
li a:hover { background: var(--raised); }
.time {
  flex: 0 0 46px; font-variant-numeric: tabular-nums;
  font-weight: 620; font-size: 14.5px; color: var(--text);
}
.match { flex: 1 1 auto; min-width: 0; }
.teams { font-weight: 560; color: var(--link); }
.meta { display: block; color: var(--muted); font-size: 12.5px; margin-top: 2px; }
.tag {
  display: inline-block; font-size: 11px; font-weight: 600;
  padding: 1px 6px; border-radius: 5px; margin-left: 6px;
  border: 1px solid var(--border); color: var(--muted);
}
li.played { opacity: 0.5; }

.empty { padding: 26px 16px; color: var(--muted); text-align: center; }
footer { margin-top: 26px; color: var(--muted); font-size: 12.5px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Football hit rates</h1>
  <p class="sub">Every upcoming fixture, soonest first. Tap one for team and
     player hit rates.</p>

  <div class="filters" id="filters"></div>
  <div id="list"></div>

  <footer id="footer"></footer>
</div>

<script>
const DATA = __PAYLOAD__;

let competition = "all";
let query = "";

/* Day headings read better as "Today" and "Tomorrow" than as a date, and the
   comparison has to be on calendar days in the reader's own timezone rather
   than on a 24 hour difference: a match at 20:00 tonight and one at 12:00
   tomorrow are 16 hours apart but belong under different headings. */
function dayKey(ts) {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function dayLabel(ts) {
  const d = new Date(ts * 1000);
  const today = new Date();
  const tomorrow = new Date();
  tomorrow.setDate(today.getDate() + 1);

  if (dayKey(ts) === dayKey(today.getTime() / 1000)) return "Today";
  if (dayKey(ts) === dayKey(tomorrow.getTime() / 1000)) return "Tomorrow";
  return d.toLocaleDateString(undefined,
    { weekday: "long", day: "numeric", month: "long" });
}

function timeLabel(ts) {
  if (!ts) return "TBC";
  return new Date(ts * 1000).toLocaleTimeString(undefined,
    { hour: "2-digit", minute: "2-digit", hour12: false });
}

function matches(f) {
  if (competition !== "all" && f.competition !== competition) return false;
  if (!query) return true;
  const hay = `${f.home} ${f.away} ${f.competition}`.toLowerCase();
  return hay.includes(query);
}

function renderFilters() {
  const counts = { all: DATA.fixtures.length };
  DATA.competitions.forEach(c => {
    counts[c] = DATA.fixtures.filter(f => f.competition === c).length;
  });

  const chips = ["all"].concat(DATA.competitions).map(c => {
    const label = c === "all" ? "All" : c;
    return `<button type="button" class="chip" data-comp="${escapeAttr(c)}"
      aria-pressed="${c === competition}">${escapeHtml(label)}<span class="n">${counts[c]}</span></button>`;
  }).join("");

  document.getElementById("filters").innerHTML = chips +
    `<input class="search" id="search" type="search" placeholder="Search team"
      value="${escapeAttr(query)}" aria-label="Search team">`;

  document.querySelectorAll("[data-comp]").forEach(btn => {
    btn.addEventListener("click", () => {
      competition = btn.dataset.comp;
      renderFilters();
      renderList();
    });
  });

  const search = document.getElementById("search");
  search.addEventListener("input", () => {
    query = search.value.trim().toLowerCase();
    renderList();
  });
  if (query) {
    search.focus();
    search.setSelectionRange(search.value.length, search.value.length);
  }
}

function renderList() {
  const shown = DATA.fixtures.filter(matches);
  const now = Date.now() / 1000;

  if (!shown.length) {
    document.getElementById("list").innerHTML =
      `<ul><li><div class="empty">Nothing to show. Build a new round with
       <code>python run.py --league "Premier League"</code>.</div></li></ul>`;
    return;
  }

  const groups = [];
  shown.forEach(f => {
    const key = f.kickoff ? dayKey(f.kickoff) : "tbc";
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(f);
    else groups.push({ key, ts: f.kickoff, items: [f] });
  });

  document.getElementById("list").innerHTML = groups.map(g => {
    const label = g.ts ? dayLabel(g.ts) : "Date to be confirmed";
    const soon = label === "Today" || label === "Tomorrow";
    const rows = g.items.map(f => {
      const played = f.kickoff && f.kickoff <= now;
      const tags = (f.players ? '<span class="tag">players</span>' : "")
                 + (f.adjusted ? '<span class="tag">adjusted</span>' : "");
      // ?v= is the build stamp. It changes every time the index is rebuilt,
      // so the browser is forced to fetch the report rather than serve a copy
      // it cached before the report was re-rendered. Without this a fixed
      // report looks unfixed for as long as the cache holds, which is the
      // most confusing possible failure.
      return `<li class="${played ? "played" : ""}">
        <a href="reports/${escapeAttr(f.report)}?v=${DATA.stamp}#e${f.id}">
          <span class="time">${timeLabel(f.kickoff)}</span>
          <span class="match">
            <span class="teams">${escapeHtml(f.home)} v ${escapeHtml(f.away)}</span>${tags}
            <span class="meta">${escapeHtml(f.competition)}${played ? " &middot; kicked off" : ""}</span>
          </span>
        </a></li>`;
    }).join("");
    return `<div class="day${soon ? " soon" : ""}">${escapeHtml(label)}</div>
            <ul>${rows}</ul>`;
  }).join("");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function escapeAttr(s) { return escapeHtml(s).replace(/'/g, "&#39;"); }

document.getElementById("footer").textContent =
  `Built ${DATA.built}. Each report is a snapshot: the numbers are frozen at ` +
  `the moment it was generated. Times are shown in your own timezone.`;

renderFilters();
renderList();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
