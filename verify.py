"""
Check that model.py and the JavaScript inside report.py agree.

    python verify.py

The count model exists twice: once in Python for the backtest, once in
JavaScript so the page can reprice a bet when you drag a line. Two copies of
one piece of maths will drift apart, and when they do the backtest will be
validating a model the site does not use. That is the worst kind of bug,
because everything keeps working and the numbers quietly stop meaning what
they claim.

So this pulls the functions straight out of report.py's JS, runs them in node
over a grid of inputs, runs model.py over the same grid, and fails loudly on
any disagreement.

Needs node on the path. If node is missing it says so and exits 0 rather than
failing, because a missing tool is not a broken model.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import hitrates
import model
import report

ROOT = Path(__file__).parent

# Every input combination worth checking: means spanning a rare event to a
# common one, lines from just-above-zero to well into the tail, and samples
# that are underdispersed, Poisson-like and overdispersed.
MEANS = [0.4, 1.2, 2.5, 3.2, 4.5, 7.0, 11.3, 21.4]
LINES = [0.5, 1.5, 2.5, 4.5, 6.5, 10.5, 15.5]
SAMPLES = {
    "tight":  [3, 3, 3, 3, 3, 3, 3, 3, 3, 3],
    "poisson": [1, 3, 2, 4, 2, 3, 1, 5, 2, 3],
    "spread": [0, 1, 8, 2, 12, 1, 6, 3, 9, 2],
    "big":    [18, 22, 14, 19, 16, 21, 15, 20, 17, 19],
}

TOLERANCE = 1e-9


def extract_js() -> str:
    """The maths functions out of report.py's JS, with no DOM in sight."""
    js = report.JS
    wanted = ["logGamma", "poissonCdf", "negBinCdf", "logChoose", "binomCdf",
              "dispersion", "predictiveRatio", "probOver", "wilsonLow",
              "calibrate"]

    out = []
    for name in wanted:
        match = re.search(
            rf"function {name}\(.*?\n\}}", js, re.S
        )
        if not match:
            raise SystemExit(f"could not find {name}() in report.py's JS")
        out.append(match.group(0))

    constants = re.search(r"const LG_C = \[.*?\];", js, re.S)
    if not constants:
        raise SystemExit("could not find LG_C in report.py's JS")

    prior = re.search(r"const DISPERSION_PRIOR = \d+;", js)
    if not prior:
        raise SystemExit("could not find DISPERSION_PRIOR in report.py's JS")

    # Pulled out by name rather than hardcoded here, so a refit that edits the
    # numbers in report.py cannot leave this check silently comparing against
    # yesterday's constants.
    cal = re.search(
        r"const CALIBRATION_A = [-\d.]+;\s*\nconst CALIBRATION_B = [-\d.]+;", js)
    if not cal:
        raise SystemExit("could not find the calibration constants in report.py's JS")

    return (constants.group(0) + "\n" + prior.group(0) + "\n"
            + cal.group(0) + "\n" + "\n".join(out))


def run_js(cases: list[dict]) -> list[dict]:
    script = extract_js() + """
const cases = JSON.parse(process.argv[2]);
const out = cases.map(c => ({
  probOver: probOver(c.line, c.mean, c.values),
  probWide: probOver(c.line, c.mean, c.values, predictiveRatio(c.values, c.mean)),
  wilson: wilsonLow(c.hits, c.total),
  calibrated: calibrate(probOver(c.line, c.mean, c.values)),
}));
console.log(JSON.stringify(out));
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
        handle.write(script)
        path = handle.name

    result = subprocess.run(
        ["node", path, json.dumps(cases)], capture_output=True, text=True
    )
    Path(path).unlink()

    if result.returncode != 0:
        raise SystemExit(f"node failed:\n{result.stderr}")
    return json.loads(result.stdout)


def check_zero_fill() -> None:
    """The zero-fill set exists in both copies and they agree.

    This lives here because the set is duplicated on purpose: hitrates.py fills
    the gaps at fetch time so new data is right, and report.py fills them again
    at render time so reports built before the fix are corrected by a re-render.
    Two copies of one list is exactly the drift verify.py exists to catch.

    It also catches the dumber failure that actually happened: the use in
    player_form() was shipped without the constant it referenced, so every build
    with --players died on a NameError. Nothing tested that path, because the
    only way to reach it is a live fetch. Touching the name from here means an
    import is enough to notice.
    """
    py = set(hitrates.PLAYER_ZERO_FILL)

    match = re.search(r"const ZERO_FILL = new Set\(\[(.*?)\]\);", report.JS, re.S)
    if not match:
        raise SystemExit("could not find ZERO_FILL in report.py's JS")
    js = set(re.findall(r'"([^"]+)"', match.group(1)))

    if py != js:
        print("ZERO_FILL disagrees between hitrates.py and report.py:")
        for name in sorted(py - js):
            print(f"  only in hitrates.py: {name}")
        for name in sorted(js - py):
            print(f"  only in report.py:   {name}")
        sys.exit(1)

    print(f"zero-fill set agrees, {len(py)} stats")


def check_rating_pools() -> None:
    """Teams that never met are not put on one scale, and no count goes <= 0.

    Guards the Hull City bug. A Premier League report projected Hull to score
    exactly 0.00 goals against Manchester United, because Hull's 38 matches
    were all Championship and the fit normalised both divisions to one mean.
    Three of ten fixtures in that report were affected, two of them sharing no
    opponents at all, so this is a class of bug and not one fixture.

    Built as a synthetic two-division league rather than a fixture file,
    because the failure needs teams that provably never met, and real data
    stops being a clean example the moment a cup tie connects them.
    """
    names = {"ALL": ["Goals", "Corner kicks"]}

    def build(ids, mean_g, mean_c, tag, strengths):
        recs = {t: [] for t in ids}
        for a in ids:
            for b in ids:
                if a == b:
                    continue
                sa, sb = strengths[a], strengths[b]
                recs[a].append({
                    "id": a * 1000 + b, "date": "2025-01-01", "competition": tag,
                    "opponent": f"T{b}", "opponent_id": b, "venue": "home",
                    "goals_for": 1, "goals_against": 1, "result": "D",
                    "stats": {"ALL": {"Goals": mean_g * sa / sb,
                                      "Corner kicks": mean_c * sa / sb}},
                    "against": {"ALL": {"Goals": mean_g * sb / sa,
                                        "Corner kicks": mean_c * sb / sa}},
                })
        return recs

    top, lower = list(range(1, 9)), list(range(9, 17))
    strength = {t: 0.6 + 0.16 * (i % 8) for i, t in enumerate(top + lower)}
    records = {}
    records.update(build(top, 2.0, 6.0, "Premier League", strength))
    records.update(build(lower, 1.0, 4.0, "Championship", strength))

    pools = hitrates.rating_pools(records)
    if len(pools) != 2:
        print(f"rating pools: expected 2 disconnected groups, got {len(pools)}")
        sys.exit(1)

    ratings = hitrates.league_ratings(records, names)

    if hitrates.project_fixture(ratings, 9, 1, names) != {}:
        print("rating pools: projected across divisions that never met")
        sys.exit(1)

    if not hitrates.project_fixture(ratings, 1, 2, names).get("ALL", {}).get("Goals"):
        print("rating pools: a normal same-division projection was lost")
        sys.exit(1)

    # The case the first version of this fix missed. Ratings are fitted from
    # every club in the division and each club's record spans all
    # competitions, so a single cup tie between divisions creates a path. Bare
    # connectivity called that comparable and let the bug straight through.
    bridged = {t: [list(r) for r in [rs]][0][:] for t, rs in records.items()}
    bridged[9] = list(records[9]) + [{
        "id": 99999, "date": "2025-02-01", "competition": "FA Cup",
        "opponent": "T1", "opponent_id": 1, "venue": "away",
        "goals_for": 0, "goals_against": 3, "result": "L",
        "stats": {"ALL": {"Goals": 0.0, "Corner kicks": 2.0}},
        "against": {"ALL": {"Goals": 3.0, "Corner kicks": 9.0}},
    }]
    bridged[1] = list(records[1]) + [{
        "id": 99999, "date": "2025-02-01", "competition": "FA Cup",
        "opponent": "T9", "opponent_id": 9, "venue": "home",
        "goals_for": 3, "goals_against": 0, "result": "W",
        "stats": {"ALL": {"Goals": 3.0, "Corner kicks": 9.0}},
        "against": {"ALL": {"Goals": 0.0, "Corner kicks": 2.0}},
    }]
    if len(hitrates.rating_pools(bridged)) != 2:
        print("rating pools: one cup tie was enough to merge two divisions")
        sys.exit(1)
    if hitrates.project_fixture(
            hitrates.league_ratings(bridged, names), 9, 1, names) != {}:
        print("rating pools: projected across divisions joined by one cup tie")
        sys.exit(1)

    # The same shared-opponent count must always give the same answer. Pool
    # membership is transitive and did not: on real data one Championship pair
    # sharing a single opponent kept all 11 projections while another sharing
    # two lost every one. Judged on the pair, the outcome is a pure function of
    # the evidence, which is the property that makes the rule explainable.
    opp = ratings.get("opponents") or {}

    def shared(a, b):
        m, t = set(opp.get(str(a)) or []), set(opp.get(str(b)) or [])
        n = len(m & t)
        if b in m or a in t:
            n += 1
        return n

    seen: dict[int, bool] = {}
    for a, b in [(1, 2), (3, 4), (9, 10), (11, 12), (9, 1), (2, 10), (5, 13)]:
        count = shared(a, b)
        projected = bool(hitrates.project_fixture(
            ratings, a, b, names).get("ALL", {}))
        if count in seen and seen[count] != projected:
            print(f"rating pools: {count} shared opponents gave both answers")
            sys.exit(1)
        seen[count] = projected

    single = build(list(range(1, 13)), 2.5, 5.0, "Premier League",
                   {t: 0.7 + 0.05 * t for t in range(1, 13)})
    solo = hitrates.league_ratings(single, names)
    if len(hitrates.rating_pools(single)) != 1:
        print("rating pools: a fully connected league was split")
        sys.exit(1)

    for home in range(1, 13):
        for away in range(1, 13):
            if home == away:
                continue
            for stat, pair in hitrates.project_fixture(
                    solo, home, away, names).get("ALL", {}).items():
                if min(pair) <= 0:
                    print(f"rating pools: non-positive projection {stat}={pair}")
                    sys.exit(1)

    print("rating pools: pair test consistent, cup-tie bridges refused")


def check_clustering() -> None:
    """Bets from one fixture must not count as independent evidence.

    Ten bets on one match are not ten observations: when a side is dominated
    it drags their shots, their shots on target and their opponent's goal
    kicks all the same way at once. Counting them as ten produces an interval
    far too narrow, and MIN_SAMPLE fires long before the evidence justifies it.
    """
    import review

    def rows(spec):
        return [{"fixture": fx, "won": bool(w), "modelP": 0.75,
                 "stat": "Corner kicks"}
                for fx, results in spec.items() for w in results]

    one = rows({"A": [1, 1, 1, 0, 0, 1, 1, 1, 0, 1]})
    if review.effective_n(one) != 1.0:
        print(f"clustering: 10 bets from one fixture counted as "
              f"{review.effective_n(one)}, expected 1")
        sys.exit(1)

    spread = rows({f"F{i}": [i % 2] for i in range(10)})
    if abs(review.effective_n(spread) - 10) > 0.01:
        print("clustering: one bet per fixture was penalised and should not be")
        sys.exit(1)

    correlated = rows({"A": [1] * 5, "B": [0] * 5, "C": [1] * 5, "D": [0] * 5})
    if review.effective_n(correlated) >= 5:
        print("clustering: fixtures that landed all-or-nothing were not discounted")
        sys.exit(1)

    print("clustering: correlated bets discounted, independent ones untouched")


def check_slip_input() -> None:
    """The slip must not rebuild itself while a price is being typed.

    The price field used to re-render the whole table 200ms after the first
    keystroke, which replaced the input element being typed into. Focus, cursor
    and any characters since were lost, so "2.50" ended up as "2.5" and the box
    appeared to reject input altogether.

    Checked by reading the JS rather than driving a browser, because verify.py
    has to run anywhere. Two properties matter: the input handler must not
    schedule a full slipView(), and the combined-price panel must live in its
    own element so it can refresh without touching the table.
    """
    js = report.JS

    handler = re.search(
        r'getElementById\("slip"\)\.addEventListener\("input".*?\n\}\);',
        js, re.S)
    # Non-greedy still runs past the first close when the body contains nested
    # braces at column 0, so cut at the first line that closes the listener.
    if handler:
        text = handler.group(0)
        end = text.find("\n});")
        handler_body = text[:end + 4] if end >= 0 else text
    else:
        handler_body = None
    if not handler:
        print("slip: could not find the price input handler")
        sys.exit(1)

    # Strip comments before checking: this handler's own comment explains the
    # bug and names slipView(), which would otherwise trip the test.
    body = re.sub(r"/\*.*?\*/", "", handler_body or "", flags=re.S)
    body = re.sub(r"//[^\n]*", "", body)
    if "slipView" in body:
        print("slip: the price handler still re-renders the whole slip, which")
        print("      destroys the input being typed into")
        sys.exit(1)

    if 'id="slip-combo"' not in js:
        print("slip: the combined-price panel has no element of its own to refresh")
        sys.exit(1)

    for name in ("comboPanel", "updateSlipTotals"):
        if f"function {name}(" not in js:
            print(f"slip: {name}() is missing")
            sys.exit(1)

    print("slip: price input is not clobbered mid-type")


def check_new_panels() -> None:
    """The four added features are wired up, not just defined.

    Each of these has a function and a place in the page, and a missing link
    between the two fails silently: the function exists, nothing calls it, and
    the panel is simply blank. That is hard to notice and easy to ship.
    """
    js = report.JS
    # The page markup is assembled inside write_report() rather than held in a
    # module constant, so the file's own source is the reliable place to look
    # for an element id.
    page = (ROOT / "report.py").read_text(encoding="utf-8")

    wiring = [
        ("customRow", 'id="c-add"', "custom bet builder"),
        ("recommendedSlip", 'id="rec-slip"', "recommended slip"),
        ("resultView", 'id="result"', "post-match review"),
        ("pricePlayer", 'id="c-player"', "custom player pricing"),
    ]
    for fn, marker, label in wiring:
        if f"function {fn}(" not in js:
            print(f"panels: {label} has no {fn}()")
            sys.exit(1)
        if marker not in page:
            print(f"panels: {label} has no {marker} in the page")
            sys.exit(1)

    for call in ("resultView();", "fillCustom();", "recommendedSlip();"):
        if call not in js:
            print(f"panels: nothing calls {call}")
            sys.exit(1)

    # A custom player bet must price through pricePlayer(), not the team path.
    # Using priceRow() there ignores minutes and showed a fouls under at 1.00.
    if "r.player ? r.price : priceRow(r)" not in js:
        print("panels: the custom preview does not use the player price")
        sys.exit(1)

    # A player with few appearances must be shown and marked, not dropped.
    # Christos Tzolis started for Arsenal with one appearance in the sample and
    # was simply absent from the page, which looked exactly like the transfer
    # never having been picked up at all.
    if "if (!vals.length) return null;" not in js:
        print("panels: players below the minimum are still being dropped")
        sys.exit(1)
    if "tag-thin" not in page:
        print("panels: thin-sample players are not marked")
        sys.exit(1)

    print("panels: custom builder, recommended slip and post-match all wired")
    print("players: thin samples shown and flagged, not hidden")


def main() -> None:
    check_zero_fill()
    check_slip_input()
    check_new_panels()
    check_rating_pools()
    check_clustering()

    if not shutil.which("node"):
        print("node is not installed, skipping the cross-check.")
        print("The Python model is still tested by its own numbers in the docstring.")
        return

    cases = []
    for mean in MEANS:
        for line in LINES:
            for name, values in SAMPLES.items():
                cases.append({
                    "mean": mean, "line": line, "values": values,
                    "sample": name,
                    "hits": sum(1 for v in values if v > line),
                    "total": len(values),
                })

    js_results = run_js(cases)

    worst_prob = worst_wilson = worst_cal = 0.0
    failures = []

    for case, js in zip(cases, js_results):
        py_prob = model.prob_over(case["line"], case["mean"], case["values"])
        py_wilson = model.wilson_low(case["hits"], case["total"])

        py_wide = model.prob_over(case["line"], case["mean"], case["values"],
                                  ratio=model.predictive_ratio(case["values"], case["mean"]))
        d_wide = abs(py_wide - js["probWide"])
        worst_prob = max(worst_prob, d_wide)

        d_prob = abs(py_prob - js["probOver"])
        d_wilson = abs(py_wilson - js["wilson"])
        worst_prob = max(worst_prob, d_prob)
        worst_wilson = max(worst_wilson, d_wilson)

        # The calibration is the newest place the two implementations can
        # drift, and the most dangerous: it is a pair of fitted constants
        # applied to every quoted price, so a typo in one copy would move
        # every number on the site while both files still ran perfectly.
        d_cal = abs(model.calibrate(py_prob) - js["calibrated"])
        worst_cal = max(worst_cal, d_cal)

        if (d_prob > TOLERANCE or d_wilson > TOLERANCE or d_wide > TOLERANCE
                or d_cal > TOLERANCE):
            failures.append(
                f"  mean={case['mean']} line={case['line']} sample={case['sample']}: "
                f"python {py_prob:.12f} vs js {js['probOver']:.12f}"
            )

    print(f"checked {len(cases)} input combinations")
    print(f"  worst probOver  difference: {worst_prob:.2e}")
    print(f"  worst wilsonLow difference: {worst_wilson:.2e}")
    print(f"  worst calibrate difference: {worst_cal:.2e}")

    if failures:
        print(f"\nMISMATCH in {len(failures)} case(s):")
        for line in failures[:10]:
            print(line)
        sys.exit(1)

    print("\nmodel.py and report.py agree.")


if __name__ == "__main__":
    main()
