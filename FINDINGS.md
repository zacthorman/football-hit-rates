# What the backtest actually measured

Written 1 September 2026, after a day of changes that were all measured rather
than argued. The point of this file is to stop good ideas being re-litigated
from intuition. Several things in here are counterintuitive, and every one of
them was tried, measured, and either kept or thrown away on the numbers.

Everything below comes from `backtest.py`, which replays past fixtures pricing
each bet from data available before its kick-off, and settles it against what
happened. It runs from cache and makes no requests.

---

## The measurement instrument was wrong first

Before trusting any number, two bugs in the backtest itself had to go.

It collected every finished fixture the league's clubs played, with no
competition filter, so a "Premier League" backtest silently included promoted
clubs' Championship season, playoffs and cups: 1,093 of 3,778 bets. And it fed
today's team list into replays of last season's fixtures, so relegated clubs
could never be rated and every bet in their matches fell back to raw-record
pricing: 755 bets.

It also defaulted to a 10-match form window while `update.json` built the live
site with 38. Every calibration figure it produced described a model nobody was
betting off. The gap it reported was 8.2 points; the real one at 38 was 5.8.
It now reads the window from `update.json` so the two cannot drift again.

**Lesson worth keeping: a backtest that measures something other than
production is worse than no backtest, because it is believed.**

## What was kept

**Model coverage.** `MIN_PAIR_LINKS` required two teams to share four
opponents, with a comment claiming healthy pairs share 18 to 22. That is
arithmetically impossible on a 10-match opponent window, where the overlap tops
out around 11 and healthy pairs sit at 3 to 8. At four, a quarter of bets lost
their projection. At two, model coverage went from 75% to 91% and the recovered
bets priced far better. Cross-division pairs joined only by a cup tie share 0
or 1 and are still rejected.

**Team calibration.** Fair prices were 12.9 points optimistic; `need`, the
column you are told to insist on, was 3.9 points optimistic, which is the
dangerous direction. A Platt scaling of the log-odds fixed it: overall said
71.2% against 70.4% landed, and `need` moved to one point on the cautious side.
Fitted on the Premier League, it generalised unseen to the Championship and
La Liga.

**Player thin-sample pricing.** Below three appearances the price fell back to
a Wilson interval on the raw record, which made `need` exactly 4.84 for every
one-appearance player who cleared his line, whatever the stat, line or player.
It now shrinks the player's own per-90 rate toward a same-team, same-position
prior. Measured on the same bets: Brier 0.2278 against the old 0.3911 in the
Premier League, 0.2110 against 0.3628 in the Championship, and near-calibrated
in aggregate.

**Player calibration, established branch only.** Established player bets were
7.3 points optimistic in the Premier League and 6.9 in the Championship. A
separate Platt pair fixed it to 0.0 and +0.6. Deliberately not applied to the
thin branch, which is already honest and which the established fit damages.

**The quoting gate.** The scan only quoted a player whose recent hit rate
cleared a fixed floor. Applied to markets with different base rates, that gate
selects skill in some and pure luck in others, and the overconfidence tracks
the distance between floor and base rate almost perfectly:

| market | base rate | gap |
|---|---|---|
| Tackles > 0.5 | 62.4% | -3.4 |
| Shots > 0.5 | 53.6% | -4.2 |
| Shots on target > 0.5 | 25.7% | -10.3 |
| Goals > 0.5 | 9.5% | -25.5 |

The record is now shrunk toward the market's own base rate before the floor is
applied. Player Brier went 0.2090 to 0.1946 (PL) and 0.2023 to 0.1872 (CH), at
a cost of about a third of quoted volume, concentrated exactly where the old
gate was selecting luck.

**Player Goals is suppressed from the scan.** Of 745 players with 10+
appearances, not one sustains a 65% scoring rate; the base rate is under 10%.
Every Goals bet the tool could produce was a player mid lucky streak. Quoted
bets averaged an 82.5% pre-match rate and landed 21.8%, and more appearances
made it worse, because a longer streak is a rarer fluke. Within the quoted set
the model had no ranking skill at all (AUC 0.543), so repricing would have been
suppression with extra steps. The records are still visible; the tool just no
longer proposes the bet.

## What was tried and thrown away

**Head to head in the price.** Out of sample the blend improved Brier by
0.0024 with a confidence interval straddling zero, and it made corners and
fouls *worse*. Decisively: blending toward a plain mean containing no
head-to-head information at all produced the same gain. What looked like
head-to-head insight was shrinkage of an overconfident number toward any
sensible mean. Kept as display, never priced.

**Possession and style covariates.** Expected possession predicts actual
possession well, and possession genuinely drives corners and fouls in-match.
But the attack x defence expectation already contains it. Of 30 slope tests one
cleared significance, which is what chance gives you at that many tests. Every
apparent gain was matched exactly by the same no-information shrinkage control.

**Player-level matchup effects.** The hypothesis that a strong opposing midfield
isolates a holding midfielder into more fouls: pooled coefficient +0.8% per 10
points of possession deficit, CI from -2.4% to +4.3%. Per-player deviations had
a spread *smaller* than sampling noise alone predicts, which is what pure noise
looks like. A positive control on tackles nearly reached significance, so the
design could see an effect of that size; fouls is smaller than that.

**Recency weighting.** Weighting recent matches more heavily made things
monotonically worse at every half-life tried, significantly so at 4 and below.
The model is starved of history, not drowning in stale history.

**Refitting the player calibration after the gate changed.** The surviving
population left prices 0.7 points cautious in the PL. A refit lost out of
sample in both split directions, the residual flips sign across the season, and
it would have halved `need`'s safety margin. Left alone.

## Standing rules these findings imply

1. Nothing new moves a price until it has been backtested. Referee data,
   positional matchup context and former-club records are all displayed and
   none of them are priced.
2. `need` must stay on the cautious side of what lands. Any change that
   improves `fair` while pushing `need` toward par does not ship.
3. When something looks informative, run the shrinkage control before
   believing it. Twice in one day the entire effect was generic shrinkage.
4. `verify.py` is the parity enforcement between `model.py` and the JavaScript
   in `report.py`. It extracts constants by name so a refit cannot leave the
   check comparing against stale numbers. Both implementations change together
   or neither does.

## When to refit

The calibration constants are window-dependent: the team slope was near 0.30 at
a 10-match window and 0.5647 at 38. Refit if `games` changes in `update.json`,
if the pricing maths changes, or if a same-signed residual shows up in both
halves of a date split *and* the refitted constants beat the current ones on
both held-out halves. A residual that flips sign mid-season is not a bias, and
fitting a scalar to it makes things worse.
