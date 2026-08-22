"""
Settle the bets a report made, and work out why each one landed or missed.

    python review.py reports/laliga-11-fixtures.html
    python review.py reports/*.html --history
    python review.py --history          # just the accumulated verdict

For every fixture in a report that has now been played, this takes the bets the
Best bets tab would have shown, settles them against what actually happened,
and decomposes the error. Then it appends the lot to review_history.json so the
picture builds up week after week.

WHY IT DOES NOT RETUNE ANYTHING BY ITSELF

The obvious next step is to have it adjust the model automatically. That would
be a mistake, and it is worth being explicit about why.

A gameweek gives maybe twenty settled bets. Fitting anything to twenty
observations produces a model that explains last Saturday beautifully and
knows nothing about next Saturday. Do it every week and the model chases noise
in a circle, each week undoing the last. That is overfitting, and the failure
mode is the worst kind: the numbers keep looking better while the predictions
get worse.

So this reports evidence and stops. Three rules keep it honest:

  1. Nothing is suggested below MIN_SAMPLE settled bets for that stat. Under
     that, a lean is indistinguishable from a run of luck.
  2. Every suggestion is quoted with a confidence interval. If the interval
     spans zero, there is nothing there.
  3. A suggestion is fitted on the older half of the history and checked on the
     newer half. If it does not survive that, it is noise and is reported as
     such rather than applied.

Only global corrections are ever considered, and only a handful of them: a
per-stat calibration factor and the dispersion prior. Never a per-team or
per-player fudge, because there is never enough data for one and it is the
fastest possible route to a model that is fitted to individual results.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import hitrates
import sofascore_api as api

ROOT = Path(__file__).parent
HISTORY = ROOT / "review_history.json"

# Below this many settled bets for a stat, no suggestion is made at all.
MIN_SAMPLE = 40

# A per-stat correction is only worth reporting if it is bigger than this.
# Smaller than this and it is inside the noise of the market's own margin.
MATERIAL = 0.04


# --------------------------------------------------------------- settling

def read_bets(report_path: Path) -> list[dict]:
    """The bets the report itself would show, read out of the live page.

    Driving the page rather than reimplementing the scan, so this can never
    settle a bet the tool would not actually have made. The payload is frozen
    at build time, so recomputing from it uses only what was known before
    kick-off.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "Needs playwright:  pip install playwright && playwright install chromium")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{report_path.resolve()}")
        page.wait_for_timeout(3000)

        count = page.evaluate("() => ALL.fixtures.length")
        out = []
        for i in range(count):
            # Select by assigning DATA directly, not through the dropdown.
            # A played fixture is filtered out of the dropdown, so setting its
            # value silently does nothing, the change handler reads an empty
            # string, and DATA ends up undefined. Which is precisely the case
            # this whole script deals in.
            page.evaluate(f"""() => {{
              showPast = true;
              scanScope = 'fixture';
              DATA = ALL.fixtures[{i}];
              fillFixtures();
              DATA = ALL.fixtures[{i}];
              applyFixture();
            }}""")
            page.wait_for_timeout(300)

            bets = page.evaluate("""() => {
              const r = scanMatchups(4);
              const rows = r.found.map(b => {
                b.price = priceRow(b);
                return b;
              }).filter(b => !b.price.conflict);
              rows.sort((a, b) => b.score - a.score);
              return {
                fixture: DATA.fixture,
                combos: r.combos,
                bets: rows.slice(0, 10).map(b => ({
                  team: b.team, teamIndex: b.teamIndex, opponent: b.opponent,
                  stat: b.stat, period: b.period, line: b.line, over: b.over,
                  k: b.k, n: b.n, recordP: b.k / b.n,
                  modelP: b.price.p, fair: b.price.fair, need: b.price.need,
                  expected: b.price.expected, source: b.price.source,
                })),
              };
            }""")
            if bets["bets"]:
                out.append(bets)

        browser.close()
    return out


def settle(entry: dict) -> list[dict]:
    """Compare every bet in one fixture against what the match produced."""
    fixture = entry["fixture"]
    raw = api.get_json(f"event/{fixture['id']}/statistics", max_age_hours=None,
                       verbose=False)
    actual = hitrates.extract_match_stats(raw)
    if not actual:
        return []

    settled = []
    for bet in entry["bets"]:
        values = actual.get(bet["period"], {}).get(bet["stat"])
        if values is None:
            continue
        got = values[bet["teamIndex"]]
        won = (got > bet["line"]) == bet["over"]

        settled.append(dict(
            bet,
            fixture=f"{fixture['home']} v {fixture['away']}",
            kickoff=fixture.get("kickoff", 0),
            actual=got,
            won=won,
            # How far the projection was from the truth, as a proportion.
            # This is the number that says whether a miss was bad luck or a
            # bad expectation.
            projection_error=(
                (got - bet["expected"]) / bet["expected"]
                if bet.get("expected") else None
            ),
        ))
    return settled


# -------------------------------------------------------------- reporting

def explain(bet: dict) -> str:
    """One line on why this bet did what it did."""
    got, line, exp = bet["actual"], bet["line"], bet.get("expected")
    direction = "over" if bet["over"] else "under"
    margin = abs(got - line)

    if exp is None:
        return "no projection, priced off the record alone"

    error = bet["projection_error"]
    close = margin <= 1

    if bet["won"]:
        if error is not None and abs(error) < 0.2:
            return f"projection was right ({exp:.1f} expected, {got:.0f} actual)"
        if close:
            return f"landed by {margin:g}, tighter than the price implied"
        return f"comfortable, {got:.0f} against a {line} line"

    if error is not None and error < -0.35:
        return (f"the projection was too high: expected {exp:.1f}, got {got:.0f}"
                f" ({error:+.0%})")
    if close:
        return f"missed by {margin:g}, inside the noise for a {direction} bet"
    return f"badly wrong: expected {exp:.1f}, got {got:.0f}"


def wilson(hits: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if not total:
        return 0.0, 1.0
    p = hits / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (centre - spread) / denom), min(1.0, (centre + spread) / denom)


def report_fixture(settled: list[dict]) -> None:
    by_fixture: dict[str, list[dict]] = defaultdict(list)
    for bet in settled:
        by_fixture[bet["fixture"]].append(bet)

    for fixture, bets in by_fixture.items():
        won = sum(1 for b in bets if b["won"])
        print(f"\n{fixture}   {won}/{len(bets)} landed")
        print("-" * 74)
        for bet in sorted(bets, key=lambda b: -b["modelP"]):
            mark = "OK  " if bet["won"] else "MISS"
            label = (f"{bet['team']} {'over' if bet['over'] else 'under'} "
                     f"{bet['line']} {bet['stat'].lower()}")
            period = {"1ST": " 1st", "2ND": " 2nd"}.get(bet["period"], "")
            print(f"  {mark} {label}{period}")
            print(f"       said {bet['modelP']:.0%}  got {bet['actual']:.0f}"
                  f"   {explain(bet)}")


def report_history(rows: list[dict]) -> None:
    if not rows:
        print("No history yet.")
        return

    print(f"\n{'=' * 74}")
    print(f"ACCUMULATED: {len(rows)} settled bets across "
          f"{len({r['fixture'] for r in rows})} fixtures")
    print("=" * 74)

    total_said = sum(r["modelP"] for r in rows)
    total_won = sum(1 for r in rows if r["won"])
    lo, hi = wilson(total_won, len(rows))
    print(f"\n  Said {total_said / len(rows):.1%}, landed {total_won / len(rows):.1%}"
          f"  (95% interval {lo:.0%} to {hi:.0%})")

    print(f"\n  {'stat':18} {'n':>4} {'said':>7} {'landed':>7} {'gap':>7}  "
          f"{'proj error':>11}  verdict")
    print("  " + "-" * 72)

    suggestions = []
    by_stat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_stat[r["stat"]].append(r)

    for stat, group in sorted(by_stat.items(), key=lambda kv: -len(kv[1])):
        said = sum(r["modelP"] for r in group) / len(group)
        landed = sum(1 for r in group if r["won"]) / len(group)
        errors = [r["projection_error"] for r in group
                  if r.get("projection_error") is not None]
        median_error = statistics.median(errors) if errors else 0.0

        if len(group) < MIN_SAMPLE:
            verdict = f"only {len(group)}, need {MIN_SAMPLE}"
        else:
            lo, hi = wilson(sum(1 for r in group if r["won"]), len(group))
            if lo <= said <= hi:
                verdict = "calibrated"
            elif abs(landed - said) < MATERIAL:
                verdict = "inside the noise"
            else:
                verdict = "MISCALIBRATED"
                suggestions.append((stat, said, landed, len(group), median_error))

        print(f"  {stat:18} {len(group):>4} {said:>6.1%} {landed:>6.1%} "
              f"{landed - said:>+6.1%}  {median_error:>+10.0%}  {verdict}")

    holdout_check(rows, suggestions)


def holdout_check(rows: list[dict], suggestions: list) -> None:
    """Would the proposed correction have helped on data it was not fitted to?

    This is the guard that stops the whole exercise turning into curve
    fitting. A correction is worked out on the older half of the history and
    then scored on the newer half. If it does not help there, it was fitted to
    noise and is reported as such.
    """
    print()
    if not suggestions:
        print("  No stat is miscalibrated on a large enough sample. Nothing to change.")
        print("  That is the expected answer most weeks, and it is a good one.")
        return

    ordered = sorted(rows, key=lambda r: r.get("kickoff", 0))
    split = len(ordered) // 2
    older, newer = ordered[:split], ordered[split:]

    print("  Possible corrections, each fitted on the older half of the history")
    print("  and then scored on the newer half it has never seen:")
    print()

    for stat, said, landed, n, median_error in suggestions:
        fit = [r for r in older if r["stat"] == stat]
        test = [r for r in newer if r["stat"] == stat]
        if len(fit) < 15 or len(test) < 15:
            print(f"    {stat}: not enough on both sides of the split to test. "
                  f"Leave it alone.")
            continue

        fit_said = sum(r["modelP"] for r in fit) / len(fit)
        fit_landed = sum(1 for r in fit if r["won"]) / len(fit)
        correction = fit_landed - fit_said

        test_said = sum(r["modelP"] for r in test) / len(test)
        test_landed = sum(1 for r in test if r["won"]) / len(test)

        before = abs(test_landed - test_said)
        after = abs(test_landed - (test_said + correction))

        if after < before - 0.01:
            print(f"    {stat}: shift probabilities by {correction:+.1%}.")
            print(f"      Out-of-sample error {before:.1%} -> {after:.1%}. Worth doing.")
        else:
            print(f"    {stat}: a {correction:+.1%} shift was fitted on the older half,")
            print(f"      but out of sample it makes things worse "
                  f"({before:.1%} -> {after:.1%}).")
            print(f"      That is noise. Do not apply it.")


# ------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="*", help="built report files to review")
    parser.add_argument("--history", action="store_true",
                        help="also print the accumulated verdict")
    parser.add_argument("--no-save", action="store_true",
                        help="do not append to review_history.json")
    args = parser.parse_args()

    stored = []
    if HISTORY.exists():
        stored = json.loads(HISTORY.read_text(encoding="utf-8")).get("bets", [])

    now = datetime.now(tz=timezone.utc).timestamp()
    fresh = []

    for name in args.reports:
        path = Path(name)
        if not path.exists():
            print(f"{name}: not found")
            continue

        entries = [e for e in read_bets(path)
                   if (e["fixture"].get("kickoff") or 0) < now]
        if not entries:
            print(f"{path.name}: nothing played yet")
            continue

        settled = []
        for entry in entries:
            settled.extend(settle(entry))

        if not settled:
            print(f"{path.name}: played, but no statistics available yet")
            continue

        print(f"\n{'#' * 74}\n# {path.name}\n{'#' * 74}")
        report_fixture(settled)
        fresh.extend(settled)

    if fresh and not args.no_save:
        seen = {(b["fixture"], b["stat"], b["period"], b["line"], b["over"],
                 b["team"]) for b in stored}
        added = [b for b in fresh
                 if (b["fixture"], b["stat"], b["period"], b["line"], b["over"],
                     b["team"]) not in seen]
        stored.extend(added)
        HISTORY.write_text(json.dumps({"bets": stored}, indent=1) + "\n",
                           encoding="utf-8")
        print(f"\n{len(added)} new settled bet(s) added, {len(stored)} in history.")

    if args.history or not args.reports:
        report_history(stored)


if __name__ == "__main__":
    main()
