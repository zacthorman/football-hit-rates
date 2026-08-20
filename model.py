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

# How hard to pull a small sample's dispersion towards Poisson. Chosen so that
# a six-match player sample reproduces the market's own price once the
# bookmaker's margin is removed; see dispersion().
DISPERSION_PRIOR = 8.0


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


def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for a binomial. The narrow end of the count family."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    p = min(1.0, max(0.0, p))
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def dispersion(values: list[float], prior: float = DISPERSION_PRIOR) -> float:
    """Variance divided by mean, pulled towards 1 by how little data there is.

    The ratio decides which distribution to use, and on a short sample it is
    itself a noisy estimate. Six matches of a player's shots gave a raw ratio
    of 0.46, which is far more certainty than six numbers can support, and
    reading it literally priced a bet at 1.20 when the market was near 1.29.

    So it is shrunk towards 1, which is Poisson, by n / (n + prior). With the
    default prior of 8 that same sample gives 0.77 and a price of 1.29, which
    is bet365's own price once their margin is taken off.
    """
    n = len(values)
    if n < 3:
        return 1.0
    m = sum(values) / n
    if m <= 0:
        return 1.0
    var = sum((x - m) ** 2 for x in values) / (n - 1)
    weight = n / (n + prior)
    return 1 + weight * (var / m - 1)


def prob_over(line: float, mean: float, values: list[float]) -> float:
    """P(count > line), choosing the distribution from the observed spread.

    A line of 1.5 asks for two or more, hence the floor: P(X > 1.5) is
    1 - P(X <= 1).

    Three distributions, chosen by whether the counts are more or less spread
    out than a Poisson process would be:

      variance > mean   negative binomial. Normal for team shots: a side either
                        dominates or gets pinned back.
      variance = mean   Poisson.
      variance < mean   binomial. Normal for a regular starter's shots: he
                        takes two or three most weeks and almost never none.

    The third case is the one that was missing, and its absence was expensive.
    Poisson on an underdispersed count puts far too much mass below the line.
    For a player expected to take 2.6 shots it assumes a 7% chance of taking
    none, which for a starting winger is simply not a thing that happens, and
    every player price came out far too long as a result.
    """
    if mean <= 0:
        return 0.0
    k = math.floor(line)
    ratio = dispersion(values)

    if ratio > 1.05:
        size = mean / (ratio - 1)
        if math.isfinite(size) and size > 0:
            return 1 - neg_bin_cdf(k, mean, size)

    if ratio < 0.95:
        p = 1 - ratio
        # floor(x + 0.5), not round(). Python's round() uses banker's rounding
        # so round(4.5) is 4, while JavaScript's Math.round(4.5) is 5. That one
        # difference put the two implementations of this model on different
        # numbers of trials and therefore different prices, which verify.py
        # caught on the first run after this branch was added.
        trials = max(2, math.floor(mean / p + 0.5))
        if trials > k:
            return 1 - binom_cdf(k, trials, mean / trials)

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
