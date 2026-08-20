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
    wanted = ["logGamma", "poissonCdf", "negBinCdf", "probOver", "wilsonLow"]

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

    return constants.group(0) + "\n" + "\n".join(out)


def run_js(cases: list[dict]) -> list[dict]:
    script = extract_js() + """
const cases = JSON.parse(process.argv[2]);
const out = cases.map(c => ({
  probOver: probOver(c.line, c.mean, c.values),
  wilson: wilsonLow(c.hits, c.total),
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


def main() -> None:
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

    worst_prob = worst_wilson = 0.0
    failures = []

    for case, js in zip(cases, js_results):
        py_prob = model.prob_over(case["line"], case["mean"], case["values"])
        py_wilson = model.wilson_low(case["hits"], case["total"])

        d_prob = abs(py_prob - js["probOver"])
        d_wilson = abs(py_wilson - js["wilson"])
        worst_prob = max(worst_prob, d_prob)
        worst_wilson = max(worst_wilson, d_wilson)

        if d_prob > TOLERANCE or d_wilson > TOLERANCE:
            failures.append(
                f"  mean={case['mean']} line={case['line']} sample={case['sample']}: "
                f"python {py_prob:.12f} vs js {js['probOver']:.12f}"
            )

    print(f"checked {len(cases)} input combinations")
    print(f"  worst probOver  difference: {worst_prob:.2e}")
    print(f"  worst wilsonLow difference: {worst_wilson:.2e}")

    if failures:
        print(f"\nMISMATCH in {len(failures)} case(s):")
        for line in failures[:10]:
            print(line)
        sys.exit(1)

    print("\nmodel.py and report.py agree.")


if __name__ == "__main__":
    main()
