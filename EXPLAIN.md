# Football betting model: how it works

A one-page explanation. Written to be read aloud in an interview.

---

## What it is

A tool that takes a football fixture and prices bets on countable events:
corners, shots, cards, tackles, offsides. For any line, such as "over 1.5
first-half corners", it produces a probability and the odds you should insist
on before staking.

It scrapes match statistics from SofaScore, caches everything permanently, and
publishes a static site that rebuilds itself on a schedule.

---

## The core idea

Most tools like this count how often something happened before. That throws
away almost everything.

A team getting **4, 5, 3, 6, 4** corners and a team getting **2, 2, 2, 2, 2**
are both "five from five over 1.5". One of those is far safer than the other,
and a hit rate cannot tell them apart. It also has no idea who they are
playing next.

So rather than counting hits, the model treats a bet as a question about a
count, and models the count.

---

## How it works, in four steps

### 1. Expect

How many corners *should* this team get, in this fixture, against this
opponent?

```
expected  =  league average  ×  team's attack rating  ×  opponent's defence rating
```

with separate home and away baselines, since most of home advantage lives
there.

The ratings are fitted **iteratively**, not in one pass. One pass inherits the
schedule: a strong team never plays itself, so its opponents are weaker than
average and its rating comes out flattered. Refitting against the current
opponent estimates removes that. Tested on a synthetic league with known
multipliers, a single pass overshot a projection by 17%; the iterative fit
recovers the truth.

### 2. Choose a distribution

Poisson or negative binomial, decided by the data. See below.

### 3. Read the probability

A line of 1.5 asks for two or more, so the answer is `P(X ≥ 2)`, read straight
off the fitted distribution.

### 4. Take a haircut

That expectation is an estimate, not a fact. So the probability is recomputed
at the bottom of a one-sided 95% interval on the mean. The optimistic number
is labelled **fair**; the conservative one is labelled **need**, and it is the
one to bet off.

---

## Why negative binomial

Poisson is the obvious first choice for counts, but it carries a strong
assumption baked in:

> **variance = mean**

That holds for genuinely random arrivals. Football counts often break it,
because matches are not interchangeable. A team either dominates and takes nine
corners, or gets pinned back and takes two. The spread is wider than Poisson
permits. This is called **overdispersion**.

Using Poisson on overdispersed data understates the tails, which means quoting
prices that are **too short**. Same ten matches, both ways:

| | probability of over 3.5 | fair odds |
|---|---|---|
| Poisson | 0.955 | **1.05** |
| Negative binomial | 0.764 | **1.31** |

*(sample mean 7.9, variance 33.0)*

Poisson calls it a near certainty. It is not, and betting 1.05 on it loses
money.

So the code measures each sample and switches:

```python
if variance > mean * 1.05:
    size = mean**2 / (variance - mean)   # dispersion, fitted from the sample
    use negative binomial
else:
    use Poisson
```

The dispersion comes from the team's own matches and is applied to the
projected mean. The choice is made **from the data**, not from preference.

---

## Keeping it honest

Three things stop the tool flattering itself.

**Wilson intervals.** Where a raw hit rate is used it is reported through a
Wilson score interval, not as a point estimate. Five from five is not 100%, it
is "above 57%".

**Multiple comparisons.** The scan looks at over a thousand combinations of
fixture, team, stat, period and line every round. At that many, something will
always look 95% certain by pure chance. The page reports how many of its own
findings would look that good with nothing behind them.

**Contradiction checks.** If the count model and the raw record disagree beyond
what either one's uncertainty allows, the bet is dropped rather than priced.
One case in testing: an expected 0.46 second-half offsides for a side that had
gone over 0.5 in thirteen of twenty, which priced at 21.0. That is a broken
ratings fit, not a finding.

---

## How I know it works

### The maths is right

The model exists twice: in Python for the backtest, and in JavaScript so the
page can reprice a bet when you drag a line. Two copies of one calculation
will drift apart, so `verify.py` runs both over **224 combinations** of mean,
line and sample spread and fails if they disagree by more than 1e-9. Both were
also checked against scipy.

### The predictions are calibrated

`backtest.py` replays past fixtures, settles every bet the tool would have
made, and buckets predicted probability against observed frequency. If bets
called 85% land 85% of the time, the prices mean what they say.

### The backtest is not cheating

This is the part worth leading with. Each fixture is rebuilt with an **as-of
cutoff** at its own kick-off, so the model can only see matches played earlier.
Without that it reads the result of the match it is predicting.

I tested the guard by deliberately removing it:

| | bets found | model said | actually landed |
|---|---|---|---|
| with the cutoff | 511 | 81.4% | 85.1% |
| **without it** | 825 | 79.6% | **90.1%** |

Ten points of pure fiction, and 60% more bets that only qualified because the
future was visible. That is **lookahead bias**, and controlling for it is what
separates a real backtest from a fantasy.

---

## What it deliberately does not claim

The tool has no odds feed. It can say a bet is worth 1.31, but not whether
anyone is offering 1.55. Value is your price against theirs, and it currently
computes one side of that subtraction. That is stated plainly on the page
rather than glossed over, because a hit rate is not an edge: only a wrong price
is.

---

## On how it was built

Built with AI assistance, which is worth being straightforward about. The value
was in directing it and knowing when the output was wrong.

Some of those moments:

- Coventry were projected for more corners at the Emirates than Arsenal. Chasing
  that down found their entire rating resting on **one** Championship match
  against the only other promoted side, the two of them fitted in a closed loop.
  Now any rating built on fewer than four usable matches is dropped and the
  reason is shown.

- Every 19-from-20 record was pricing at exactly 1.31, regardless of fixture.
  That is the symptom that led to replacing the hit-rate pricing with the count
  model, because the price was ignoring the matchup entirely.

- A Premier League fixture list containing Tromsø against Brighton, caused by
  taking each team's next fixture in *any* competition.

- Bookmakers do not price "goals prevented" or "hit woodwork". The market list
  is now matched against what bet365 actually offers, filtered at scan time so
  even reports built before that rule get it.

The pattern throughout: **measure before building, diagnose before guessing.**
Key compression was measured at 1.33x and dropped rather than built. A dead
API endpoint was proven dead with a probe script in thirty seconds after an
hour lost guessing. A deploy failure was traced to a GitHub outage rather than
to the code.
