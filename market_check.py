"""
Check the model against real bookmaker prices.

    python market_check.py reports/premier-league-10-fixtures.html

Loads a built report, reprices every line in market_prices.json using the
current model, and reports how far off the market it is, broken down by stat.

Why this exists. Every other test in this project checks the model against
itself: verify.py checks the two implementations agree, backtest.py checks the
predictions are calibrated against outcomes. Neither can catch the model being
confidently wrong in a way that a bookmaker would spot instantly.

This one caught a real bug on its first run. Shots on target and tackles were
both roughly 20% too confident, and the cause was that SofaScore leaves a stat
out entirely when a player records none of it. Averaging only the matches where
the key was present gave double the real rate. Shots were unaffected, because
zeros are recorded there, which is exactly why eyeballing shots had suggested
the model was fine.

A caveat that matters. The saved prices are over-only, so the bookmaker's
margin is still in them, and a two-way player prop is typically 6 to 8 per cent
over round. That is assumed and split proportionally below. It means small
differences are not meaningful and only a consistent lean is worth acting on.
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
PRICES = ROOT / "market_prices.json"

# Typical two-way overround on a player prop. Their offered price implies a
# probability slightly higher than the truth; this takes it back out.
ASSUMED_MARGIN = 0.07

# Below this the model and the market are close enough that the difference is
# swamped by not knowing their real margin.
NOISE = 0.06


def true_probability(price: float) -> float:
    return (1 / price) / (1 + ASSUMED_MARGIN)


def reprice(report_path: Path, prices: list[dict]) -> list[dict]:
    """Run the report's own JavaScript over each saved line.

    Driving the real page rather than reimplementing the pricing, so this
    cannot quietly test something the site does not do.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "This needs playwright:  pip install playwright && playwright install chromium"
        )

    wanted: dict[str, list[dict]] = {}
    for row in prices:
        wanted.setdefault(row["fixture"], []).append(row)

    out = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{report_path.resolve()}")
        page.wait_for_timeout(3000)

        for fixture, rows in wanted.items():
            found = page.evaluate(
                """(key) => {
                  const i = ALL.fixtures.findIndex(f =>
                    f.fixture.home.includes(key) || f.fixture.away.includes(key));
                  if (i < 0) return false;
                  document.getElementById('fixture').value = String(i);
                  document.getElementById('fixture').dispatchEvent(new Event('change'));
                  return true;
                }""", fixture)
            if not found:
                print(f"  {fixture}: not in this report, skipped")
                continue
            page.wait_for_timeout(400)

            for row in rows:
                priced = page.evaluate(
                    """([player, stat, line]) => {
                      for (let t = 0; t < 2; t++) {
                        const allowed = new Set(filtered(DATA.records[t]).map(m => m.id));
                        const recs = DATA.players[t]
                          .filter(r => allowed.has(r.match_id) && r.player.includes(player));
                        if (!recs.length) continue;
                        const apps = appearances(recs, stat);
                        if (apps.length < 3) continue;
                        const p = pricePlayer(apps, line, true, playerAdjustment(stat, t));
                        return { fair: p.fair, expected: p.expected, n: p.n };
                      }
                      return null;
                    }""", [row["player"], row["stat"], row["line"]])
                if priced:
                    out.append(dict(row, **priced))

        browser.close()
    return out


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__.strip().splitlines()[2].strip())

    report_path = Path(sys.argv[1])
    if not report_path.exists():
        raise SystemExit(f"No such report: {report_path}")
    if not PRICES.exists():
        raise SystemExit(f"No saved prices at {PRICES.name}")

    saved = json.loads(PRICES.read_text(encoding="utf-8"))
    print(f"{len(saved['prices'])} prices from {saved['book']}, "
          f"captured {saved['captured']}")
    print(f"Assuming a {ASSUMED_MARGIN:.0%} overround, split proportionally.\n")

    priced = reprice(report_path, saved["prices"])
    if not priced:
        raise SystemExit("Nothing could be repriced from that report.")

    # Their margin is a guess, and the answer moves with it, so the guess is
    # not allowed to decide the verdict. A lean only counts if it survives the
    # whole plausible range: a bias that appears at 5% and vanishes at 9% is a
    # statement about the assumption, not about the model.
    MARGINS = [0.05, 0.07, 0.09]

    by_stat: dict[str, list] = {}
    for row in priced:
        their_p = true_probability(row["over"])
        my_p = 1 / row["fair"]
        by_stat.setdefault(row["stat"], []).append((my_p - their_p, row, their_p))

    print(f"  {'stat':18} {'n':>3}" + "".join(f"{m:>10.0%}" for m in MARGINS) + "   verdict")
    print("  " + "-" * 66)
    biased = []
    for stat, rows in sorted(by_stat.items()):
        medians = []
        for margin in MARGINS:
            errs = [1 / r[1]["fair"] - (1 / r[1]["over"]) / (1 + margin) for r in rows]
            medians.append(statistics.median(errs))

        # Only a lean that holds across every assumption counts.
        if all(m > NOISE for m in medians):
            verdict, bad = "too confident", True
        elif all(m < -NOISE for m in medians):
            verdict, bad = "too pessimistic", True
        elif max(abs(m) for m in medians) > NOISE:
            verdict, bad = "borderline, depends on their margin", False
        else:
            verdict, bad = "in line", False

        if bad:
            biased.append(stat)
        print(f"  {stat:18} {len(rows):>3}"
              + "".join(f"{m:>+10.1%}" for m in medians) + f"   {verdict}")

    print("\n  Biggest single disagreements:")
    flat = sorted(((abs(e), e, r, tp) for rows in by_stat.values() for e, r, tp in rows),
                  reverse=True)
    for _, err, row, their_p in flat[:6]:
        print(f"    {row['player']:16} {row['stat']:16} "
              f"mine {row['fair']:>6.2f}  theirs {1/their_p:>6.2f}  "
              f"exp {row['expected']:>5.2f} from {row['n']} apps   {err:+.0%}")

    print()
    if biased:
        print(f"  {', '.join(biased)} lean the same way at every margin assumption.")
        print("  That is a real bias rather than noise, and worth chasing.")
        sys.exit(1)
    print("  No stat leans consistently across the plausible margin range.")


if __name__ == "__main__":
    main()
