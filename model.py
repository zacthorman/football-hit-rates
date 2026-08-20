"""
The count model, in Python.

This is a deliberate mirror of the JavaScript in report.py. The page has to do
this in the browser because lines are adjustable there; the backtest has to do
it here because it walks thousands of past fixtures. Two implementations of one
piece of maths is a liability, so `verify.py` runs both over the same inputs and
fails if they ever disagree. Change one, run that, change the other.

What it does, in one paragraph. A bet on "over 1.5 corners" is a question about
a count, so model the count. Take the opponent-adjusted expectation for the team
in this fixture, fit the spread from the team's own matches, and read the
probability off the resulting distribution. Poisson when the variance is close
to the mean, negative binomial when it is larger, which is normal for shots.
Then haircut for the fact that the expectation is itself estimated.

No imports beyond the standard library, on purpose: the backtest should not need
the network stack to price a bet.
"""

from __future__ import annotations

import math

# Each side of a matchup must clear this on its own before the pair is scored.
MATCHUP_FLOOR = 0.65

# One-sided 95%. Used to put a band on the estimated expectation.
Z_95 = 1.645


def wilson_low(hits: int, total: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson interval for a proportion.

    The honest version of hits/total. Five from five is not 100%, it is
    "somewhere above 57%", and this is the number that says so.
    """
    if total == 0:
        return 0.0
    p = hits / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (centre - spread) / denom)


def poisson_cdf(k: int, mean: float) -> float:
    """P(X <= k). Summed forwards rather than via a gamma function because k
    is always small here and the loop is exact."""
    if mean <= 0:
        return 1.0
    if k < 0:
        return 0.0
    term = math.exp(-mean)
    total = term
    for i in range(1, k + 1):
        term *= mean / i
        total += term
    return min(1.0, total)


def neg_bin_cdf(k: int, mean: float, size: float) -> float:
    """P(X <= k) for a negative binomial with the given mean and dispersion.

    Parameterised by mean and `size` rather than by the usual r and p, because
    the mean is what the projection gives us and the dispersion is what the
    sample gives us. Computed in logs to stay stable when size is large.
    """
    if mean <= 0:
        return 1.0
    if k < 0:
        return 0.0
    p = size / (size + mean)
    total = 0.0
    for i in range(k + 1):
        log_pmf = (
            math.lgamma(i + size) - math.lgamma(i + 1) - math.lgamma(size)
            + size * math.log(p) + i * math.log1p(-p)
        )
        total += math.exp(log_pmf)
    return min(1.0, total)


def prob_over(line: float, mean: float, values: list[float]) -> float:
    """P(count > line), choosing the distribution from the observed spread.

    A line of 1.5 asks for two or more, hence the floor: P(X > 1.5) is
    1 - P(X <= 1).
    """
    if mean <= 0:
        return 0.0
    k = math.floor(line)

    n = len(values)
    if n >= 3:
        m = sum(values) / n
        var = sum((x - m) ** 2 for x in values) / (n - 1)
        # Overdispersed relative to Poisson: carry the sample's spread onto
        # the projected mean rather than pretending the spread is not there,
        # which would quote a price that is too short.
        if var > m * 1.05 and m > 0:
            size = (m * m) / (var - m)
            if math.isfinite(size) and size > 0:
                return 1 - neg_bin_cdf(k, mean, size)

    return 1 - poisson_cdf(k, mean)


def price(
    line: float,
    over: bool,
    expected: float | None,
    values: list[float],
    hits: int,
    total: int,
) -> dict:
    """Probability, fair price and the price to insist on.

    `expected` is the opponent-adjusted projection for this team in this
    fixture, and is what makes the price move with the matchup. Without one,
    which happens when a side cannot be rated, this falls back to the raw
    record and marks itself, because an invented expectation is worse than an
    honest blunt number.
    """
    record_p = hits / total if total else 0.0
    record_need = 1 / wilson_low(hits, total) if wilson_low(hits, total) > 0 else math.inf

    if expected is None or expected <= 0 or len(values) < 3:
        return {
            "p": record_p,
            "fair": 1 / record_p if record_p > 0 else math.inf,
            "need": record_need,
            "expected": None,
            "source": "record",
            "conflict": False,
        }

    n = len(values)
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / (n - 1)
    se = math.sqrt(max(var, 1e-9) / n)

    # Clipped to half and double. Ten matches of a noisy stat can produce a
    # standard error big enough to drag the lower bound to nothing, and a bound
    # of nothing prices everything at 20.0, which is noise dressed as caution.
    low = max(expected * 0.5, expected - Z_95 * se)
    high = min(expected * 2, expected + Z_95 * se)

    if over:
        p = prob_over(line, expected, values)
        p_low = prob_over(line, low, values)
        p_high = prob_over(line, high, values)
    else:
        p = 1 - prob_over(line, expected, values)
        p_low = 1 - prob_over(line, high, values)
        p_high = 1 - prob_over(line, low, values)

    # When the record's own lower bound sits above anything the model will
    # allow even at its most generous, the two disagree beyond either one's
    # uncertainty and neither should be trusted. The blunter check catches a
    # broken ratings fit: an adjustment should move a team's average, but it
    # should not halve it or double it.
    absurd = expected < 0.5 * mean or expected > 2 * mean
    conflict = absurd or wilson_low(hits, total) > p_high + 0.05

    return {
        "p": p,
        "fair": 1 / p if p > 0 else math.inf,
        "need": 1 / max(p_low, 0.01),
        "expected": expected,
        "source": "model",
        "conflict": conflict,
    }
