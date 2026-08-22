# Football fixture hit rates

Pick a fixture, get both teams' hit rates for every stat SofaScore tracks, split by home and away form, with a chart of the game-by-game sequence.

Output is a self-contained HTML file.

## Setup

Already done if you followed along, but from scratch:

```bash
cd "/Users/zacthorman/Vaults/Cowork Base/03 Code Projects/Football stats"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Use

```bash
# See it work with fake data, no network needed
python run.py --demo

# Find a team's id
python run.py --search espanyol

# List that team's next fixtures
python run.py --team 2814

# Build the report for fixture 0 in that list
python run.py --team 2814 --pick 0

# Three of that team's upcoming fixtures, one report
python run.py --team 2814 --pick 0,1,2

# Several teams, each one's next fixture, one report
python run.py --teams 2814,2833,2817 --players

# A whole division's next round
python run.py --league premier_league --players --h2h --adjust

# Every major league, one report each, all listed on the site
python run.py --leagues premier_league,championship,la_liga,serie_a,bundesliga,ligue_1 --adjust
python make_index.py
```

`--leagues` writes one report per division rather than a single enormous file, so the index reads as a list of rounds and no page has to carry a hundred fixtures. Files are named after the competition, so each league keeps its own and re-running replaces only that one.

`--league` reads the team list off the league table, so you don't have to know twenty ids, then collapses each team's next fixture into a round. Known names: `premier_league`, `championship`, `la_liga`, `serie_a`, `bundesliga`, `ligue_1`, `champions_league`, `europa_league`. Any other competition works by passing its uniqueTournament id.

A report can hold as many fixtures as you like, with a dropdown at the top to switch between them. All the filters and edited lines are per fixture.

## What it costs in requests

Roughly, per fixture:

| | Requests | Time |
|---|---|---|
| Team stats only | about 25 | 40 seconds |
| With `--h2h` | about 35 | 55 seconds |
| With `--players` | about 45 | 75 seconds |

So five fixtures with players is around 220 requests and six minutes, which is comfortably within what SofaScore will tolerate at a 1 to 2 second delay. Two things make it cheaper than that arithmetic suggests:

- **Teams in the same league share matches.** Building every fixture in a LaLiga round means each match's statistics is fetched once and reused by both teams involved, so the marginal cost per extra fixture drops as you add more.
- **Nothing is fetched twice, ever.** Re-running is instant, and adding `--players` to a fixture you already built only fetches the lineups.

Running a full weekend's card the night before is entirely reasonable. Running it repeatedly in a tight loop is not, and would get your IP blocked.

**Only bettable markets by default.** SofaScore returns plenty that has no market attached to it (goals prevented, expected assists, duels won), and every extra row is another combination for the Standout scan to trawl and another chance for a coincidence to look like a finding. Team stats are filtered to shots, shots on target, shots off target, blocked shots, shots inside and outside the box, corners, offsides, throw-ins, fouls, cards, goal kicks, free kicks, tackles and big chances. Player props are filtered to shots, shots on target, goals, assists, tackles, fouls, fouled, offsides, clearances, interceptions, passes, crosses and saves, plus minutes, which is not a market but decides whether the rest matter. `--all-stats` turns the filter off.

**Fouls won come free.** Fouls conceded is the "For" measure and fouls won is the "Against" measure of the same stat, so the Measure control already gives you both without a separate row.

Useful flags: `--players` to include per-player stats, `--games 20` for a deeper sample, `--show 10` to list more fixtures, `--no-open` to skip launching the browser.

## In the report

**Team stats tab.** One row per stat. Every line is editable: type a number, or use the plus and minus buttons, and both teams' hit rates recompute instantly. The buttons move by a whole unit and keep the .5, so 13.5 goes to 14.5, never 14. That matters because a line ending in .5 can never be exactly matched, so there is no ambiguity about whether a match hit it. An edited line is shown in bold so you can see which are yours and which came from the data. "Reset lines" puts them all back.

**Players tab.** Present when you ran with `--players`. Pick a stat, set a line, set a minimum number of appearances, and both squads are ranked by hit rate. It respects the same last 5 / last 10 and home / away filters as the team tab, so "last 5 at home" means the same thing in both.

**Standout lines tab.** Scans every combination of fixture, team, stat, period and venue split, and ranks what comes out. Two things make it honest rather than a fruit machine:

- It ranks by the lower bound of a 95% confidence interval, not by raw percentage. That matters because 5/5 is 100% and 18/20 is 90%, yet the second is far stronger evidence. Ranking by percentage puts the flukes on top; this puts them where they belong.
- It tells you how many combinations it scanned, and roughly how many would look that consistent from chance alone. Scan 1,400 combinations at ten matches each and about 15 will reach 9/10 by luck. Without that number, a list of "strong" lines is indistinguishable from a list of coincidences.

**Fair and Need.** Each row turns its hit rate into a price two ways. **Fair** is what the hit rate implies on its own (1 divided by the rate). **Need** comes from the bottom of the confidence interval and is the one to bet off. The gap between them is the point: 8/10 reads as a fair 1.25, but ten matches cannot tell 80% from 55%, so the evidence only really justifies 2.04 or better. Type a bookmaker's price into "Your price" and the row says whether it clears, using the conservative figure. Getting a yes should be hard.

Neither number includes the bookmaker's margin. A real market is priced so the implied probabilities sum above 100%, typically 105 to 108% on these, so the available price is worse than fair by design.

Treat it as a shortlist to price up. A hit rate is not an edge: what makes a bet worth taking is the price being wrong, and there is no odds feed here to tell you that. The suggested lines are also derived from the same matches being measured, which flatters every number in the table.

**Measure.** For, Against, or Matchup.

- **For** is each team's own numbers, the default.
- **Against** is what opponents managed against them, so "corners conceded" rather than "corners won".
- **Matchup** is the one worth reaching for: the home side's own numbers on the left against the away side's conceded numbers on the right. That answers whether an attack actually meets a leak, rather than comparing two attacks that never face each other.

None of this costs extra requests. The statistics endpoint always sends both teams' figures for every match; the earlier version simply discarded the opponent's half.

**Played fixtures drop off by themselves.** The report is a static snapshot, but the browser knows the time, so a multi-fixture report hides games once they have kicked off and the button next to the dropdown brings them back. If every fixture has been played it shows them all rather than an empty page, and the index marks that report as history.

**Opponent adjustment (`--adjust`).** Fits attack and defence ratings for every club in the competition, then projects what each team should actually do *in this fixture against this opponent*. Shown as "proj 11.0 v 8.4" under each line, and turned red when the projection lands on the other side of the line from the record. That red flag is the case you care about: a true 100% that the model expects to fail.

The model is the standard multiplicative one. A team's attack rating is its own average divided by the league average, its defence rating is what it concedes divided by the same, and the expected value is `league average x attack x opponent defence`, with separate home and away baselines. It is fitted iteratively rather than in one pass, because a single pass inherits the schedule: a strong side never plays itself, so its opponents are weaker than average and its rating comes out flattered. On a synthetic league with known multipliers, one pass overstated a projection by 17% and the iterative fit recovers the truth.

Three honest limits:

- **It needs the division.** Ratings are fitted from every club's recent form, so the first `--adjust` run on a competition fetches all twenty clubs. Slow once, then cached, and a `--league` round reuses matches it was fetching anyway.
- **A promoted side comes out as exactly average.** Their sample is from another division, so there are no matches against this division's teams to fit against, and they default to a 1.0 rating. That is a guess, not a measurement, and the different-opposition warning still fires.
- **Ten matches is a thin fit.** The ratings are directionally useful and not precise. They know nothing about injuries, rotation, or a manager changing shape.

**Different opposition warning.** If a team's sample was built mostly in another competition, the team tab says so and the Standout scan leaves them out until you ask for them. This is the trap the tool is least able to solve on its own: a promoted side putting up 12 shots a game against Championship defences has a perfectly true 100% record over 2.5 shots, and it tells you almost nothing about how they'll do away at Arsenal. The hit rate carries no memory of who it was set against.

Note what this does and does not do. It flags a mismatch; it does not adjust for one. Adjusting properly means weighting every match by the opponent's strength, which is a model rather than a filter.

**Sample.** Recent form, or head to head. Head to head is the same layout over previous meetings between these two teams instead of their recent matches, with its own suggested lines, since two teams meeting each other produce different numbers from their form against everyone else. Needs `--h2h` when building.

**Team.** Both, or one side on its own. Picking a single team drops the head-to-head split and gives that team the full width, which is the easier read when you only care about one of them. The projection, the strong-row shading and the charts all follow the selection.

**Layout.** Each stat is one row with the two teams facing each other around the stat name, so the comparison is a single glance. On a phone the same row stacks into a card. **Main** shows the seven stats worth most attention; **All** shows everything the endpoint returned. **Strongest first** sorts by distance from an even split, and **Strong only** keeps just the rows where a team is at 80% or above, or 20% or below. Those rows are also shaded.

**The dots** are colour-coded against the line: a filled green dot is over, a hollow red one is under. Colour is not carrying that alone, since position relative to the dashed line and the fill state say the same thing, which keeps it readable in greyscale and for red-green colour blindness.

**Period.** Full match, first half or second half. Each period keeps its own lines, because a first-half shots line has nothing to do with a full-match one, and its own hit rates and charts. The halves come straight from SofaScore rather than being derived, since summing the halves does not reliably reproduce the full-match figure.

Player stats are full match only, since SofaScore doesn't publish per-player numbers by half. Players who have left the club are excluded automatically: the squad is read fresh, so a striker sold in July no longer shows up with last season's shot record. New signings appear once they have minutes, and the terminal reports how many squad members have none yet.

Hovering any point on a chart gives you the date, opponent and value.

It works team-first rather than date-first because SofaScore removed their date-based fixture endpoint. `check.py` is the script that established that, and it's worth keeping: if something else breaks later, add the suspect path to its list and run it.

The report lands in `reports/` and opens automatically. Inside it you can switch between last 5, last 10 and all, and between all matches, home only and away only. Hover any point on a chart for the date, opponent and value.

## Best bets

A tab that scans the whole round for fixtures where **both halves point the
same way**: the team's own record at this venue, and what their opponent
concedes at theirs. Forest have gone over 1.5 first-half corners in 10 of
their last 10 at home, and Leeds have conceded over 1.5 in 9 of their last 10
away. Two separate records agreeing is stronger than one record twice as long,
because they can fail independently.

Rules the scan follows, and why:

- **Venue is enforced on both sides.** Home record against away record, never
  the pooled one. That is the actual fixture.
- **Both halves must clear 65% on their own** before the pairing is scored, so
  a 10/10 cannot drag a 3/10 into the list.
- **The two records are pooled into one interval.** 20 observations at 85%
  supports a much shorter price than 10 at 85%, and the interval says so.
- **The line ladder is one-sided.** An over is only tried at the median line
  and above, an under at the median and below. Without this the list fills up
  with things like "Newcastle over 0.5 yellow cards, 20 from 20", which is
  true, useless, and priced at about 1.05.
- **Ties break towards the harder line.** The score depends only on how many
  went the right way, so over 0.5 and over 2.5 both score identically at
  10/10. The more demanding line wins.
- **Grouped by competition**, three per division by default.

Every card shows both sequences in full, the pooled record, the fair price,
the price the evidence actually supports, how often a scan this size throws up
something this good by chance, and whether the opponent-adjusted projection
agrees. The projection is the only figure on the card that did not come from
the same matches as the record.

None of this knows what the bookmaker is offering, and the price is the entire
bet. Treat it as a shortlist to price up.

## Goals

Goals are not in SofaScore's statistics feed at all, they live on the
scoreline, so they are bolted into the stat blocks from there. That makes
`Goals` behave like every other stat: it has a line, a hit rate, a for and
against split, and it feeds the matchup scan. Full match only, because the
half-time score is a separate call.

## The front page

`make_index.py` lists **fixtures**, not report files. A league round is one
file holding ten matches, and `premier-league-10-fixtures.html` tells you
nothing about whether Arsenal are playing tonight. So every report's payload
is read, each fixture pulled out with its kick-off time, and the lot sorted by
when they actually start and grouped under Today, Tomorrow and then by day.
Competition chips filter, and there is a search box for a club name.

Each fixture links straight to itself inside its report using the event id in
the URL hash, so `reports/premier-league.html#e16363633` opens on that match
rather than on whichever one happened to be first.

Kick-off times render in the reader's own timezone. The page ships unix
timestamps and lets the device do it, because a 20:00 UTC kick-off is 21:00 in
most of Europe and being an hour out is the sort of thing that loses a bet.

## Reviewing itself after the games (`review.py`)

    python review.py reports/laliga-11-fixtures.html
    python review.py reports/*.html --history
    python review.py --history

For every fixture in a report that has now been played, this takes the bets the
Best bets tab would have shown, settles them against what actually happened,
and says why each one landed or missed. Then it appends everything to
`review_history.json`, so the picture builds week after week.

The per-bet verdict separates a good call from a lucky one:

```
Rayo Vallecano v Deportivo Alaves   10/10 landed
  OK   Alaves over 6.5 goal kicks
       said 90%  got 11   projection was right (10.3 expected, 11 actual)
  OK   Rayo over 1.5 corner kicks 1st
       said 71%  got 2    landed by 0.5, tighter than the price implied
```

Both won. Only the first was actually predicted.

### Why it does not retune itself

The obvious next step is to let it adjust the model automatically. That would
be a mistake.

A gameweek gives maybe twenty settled bets. Fitting anything to twenty
observations produces a model that explains last Saturday beautifully and knows
nothing about next Saturday. Do it every week and the model chases noise in a
circle, each week undoing the last. The failure mode is the worst kind: the
numbers keep looking better while the predictions get worse.

So it reports evidence and stops. Three rules:

1. **Nothing below 40 settled bets for a stat.** Under that a lean cannot be
   told from a run of luck. The output says `only 8, need 40` and moves on.
2. **Every figure carries an interval.** If it spans the claim, there is
   nothing there.
3. **Any suggested correction is fitted on the older half of the history and
   scored on the newer half.** If it does not survive out of sample it is
   reported as noise and explicitly not applied.

Only global corrections are ever considered: a per-stat calibration shift, or
the dispersion prior. Never a per-team or per-player adjustment, because there
is never enough data for one and it is the fastest route to a model fitted to
individual results.

Most weeks the honest answer is "nothing to change", and the script says so
rather than inventing work.

## Checked against real bookmaker prices (`market_check.py`)

    python market_check.py reports/premier-league-10-fixtures.html

Forty-eight bet365 player prices are saved in `market_prices.json`. This
reprices every one of them using the current model and reports how far off the
market it is, broken down by stat.

Every other test here checks the model against itself. `verify.py` checks the
two implementations agree; `backtest.py` checks the predictions are calibrated
against outcomes. Neither can catch the model being confidently wrong in a way
a bookmaker would spot instantly.

**It caught a real bug on its first run.** Shots on target and tackles were
both about 20% too confident. The cause: SofaScore leaves a stat out entirely
when a player records none of it. Adrien Truffert's shots on target came back
as `1, -, 1, 1, -, 2, -, -` across eight matches, and reading the gaps as
unknown rather than as zero gave 1.25 a game when the truth is 0.62. Every
shots-on-target and tackles price in the tool was built on roughly double the
real rate. Shots escaped it because zeros are recorded there, which is exactly
why eyeballing shots had suggested everything was fine.

| stat | before | after |
|------|--------|-------|
| Shots | -6.1% | -6.1% |
| Shots on target | +21.7% | +3.2% |
| Tackles | +16.0% | -4.7% |

The fix is applied both at fetch time and at render time, so reports built
before it was found are corrected by `rerender.py` without refetching.

The bookmaker's margin is a guess and the answer moves with it, so the guess
is not allowed to decide the verdict. Each stat is scored at 5%, 7% and 9%
overround, and only a lean that survives all three counts as a bias. A
difference that appears at 5% and vanishes at 9% is a statement about the
assumption, not about the model.

Run it after any change to the pricing. It exits non-zero on a real bias.

## Does it actually work? (`backtest.py`)

The one question nothing inside the model can answer: when it says 85%, do
those bets land 85% of the time? If they land 70%, every price on the site is
too short and the tool has been quietly lying to you.

    python backtest.py --league "Premier League" --games 10
    python backtest.py --leagues "Premier League,Championship" --csv bets.csv

It replays past fixtures, rebuilds what the tool would have said the day
before each one, settles every bet the Best bets scan would have produced, and
buckets the predictions against the outcomes. It runs entirely from the cache
and makes no requests, so it cannot get your IP blocked. Missing lookups are
counted rather than fetched.

**The bit that decides whether any of it means anything.** Every fixture is
built with an as-of cutoff at its own kick-off, so the model can only see
matches played earlier. Without that it reads the result of the match it is
predicting. Measured on a synthetic league:

| | bets | said | landed |
|---|---|---|---|
| with the cutoff | 511 | 81.4% | 85.1% |
| without it | 825 | 79.6% | 90.1% |

Ten points of pure fiction, and 60% more bets that only qualified because the
future was visible. That is lookahead bias, and it is the standard way a
backtest flatters itself into looking like a business.

The backtest also answers a question worth asking honestly: does the opponent
adjustment beat just using the raw hit rate? Both are scored side by side on
the same bets with a Brier score. On the synthetic league the count model came
out ahead, 0.1242 against 0.1274, and was near perfectly calibrated between
82% and 97% where the raw hit rate was seven points overconfident. On real
football it may not win, and that is worth knowing.

## The model lives in two places

`model.py` is the Python implementation, used by the backtest. The JavaScript
inside `report.py` is the same maths again, because the page reprices bets in
the browser when you drag a line. Two copies of one calculation will drift.

    python verify.py

pulls the functions straight out of `report.py`, runs them in node over 224
combinations of mean, line and sample spread, runs `model.py` over the same
grid, and fails if they disagree by more than 1e-9. Run it after touching
either one. Both were also checked against scipy.

## Player lines: minutes, and the worst bug in the tool

Saka over 1.5 shots was priced at `need 3.00`. bet365 were offering 1.22. Two
separate faults, both mine.

**Minutes were ignored.** His last eight records included a match he did not
play in at all, one where he came on for nine minutes, and one where he was
off at half time. The nil from the game he missed was counted as a losing bet.
A bookmaker voids that: it is not a loss, it is not an event. Counting it
dragged his record to 5/8 and his expectation to 1.9 shots.

Now any match under 45 minutes is dropped, the rest are converted to a rate
per 90, and that rate is multiplied by the minutes he is likely to play. Which
is how the market prices it, and the only way a 45-minute cameo and a full 90
can sit in the same average.

**The distribution was wrong in one direction.** The model switched to a
negative binomial when counts were more spread out than Poisson, but had
nothing for the other case. A regular starter's shots are *less* spread out
than Poisson: he takes two or three most weeks and almost never none. Poisson
with a mean of 2.6 assumes a 7% chance of zero shots, which for a starting
winger does not happen, and that misplaced weight below the line made every
player price too long.

There is now a binomial branch for the underdispersed case. And because the
dispersion estimate is itself noisy on six matches, it is shrunk towards
Poisson by `n / (n + 8)`.

The result, on the same six appearances:

| | fair |
|---|---|
| before | 1.75 |
| minutes fixed, Poisson | 1.37 |
| plus the binomial branch | **1.28** |
| bet365, margin removed | ~1.29 |

Worth reading the conclusion carefully. Fair is 1.28 and bet365 offer 1.22, so
that bet is **not** worth taking: the price is shorter than the odds justify.
The tool is not being timid, it is telling you the bookmaker has the edge on
that one.

Adding the binomial branch also caught a divergence between the Python and the
JavaScript, via `verify.py`: Python's `round(4.5)` is 4 and JavaScript's
`Math.round(4.5)` is 5, so the two implementations picked different numbers of
trials and quoted different prices. Exactly the drift that script exists for.

## Player lines and the strength of the opponent

A second round of the same bug. Coventry's Brandon Thomas-Asante was priced at
1.52 for over 1.5 shots when the market was 3.00, which looks like enormous
value and is not: Coventry are away at Arsenal and will barely get a shot off.

The player adjustment was clipped to between 0.7 and 1.35, on the reasoning
that an adjustment should nudge a line rather than move it a long way. That
reasoning was simply wrong. Coventry average 15.8 shots in the Championship
and are expected to manage **4.83** at the Emirates. The true adjustment is
**0.31**, and clipping it to 0.7 priced their forwards at more than double the
shots they will get. A mismatch really is a big move; that is what a mismatch
is. The bounds are now wide enough to be only a divide-by-zero guard.

That exposed a second fault underneath, and then a third.

The haircut behind `need` was an absolute standard error measured on the
player's own sample and subtracted from an adjusted expectation a third the
size. Taking 0.6 off an expectation of 0.9 leaves almost nothing, and the bet
priced at 20.0.

Fixing that proportionally was still wrong, because the whole mechanism was
wrong. It stacked two uncertainties on top of each other: the match itself is
random, which the count distribution already knows about, and then the mean
was cut again for being an estimate. On Havertz's five-match sample the cut
hit its 50% cap, halving his expectation, so a bet with a fair price of 1.43
came out needing 2.84. Nobody would ever take that.

`need` now widens the distribution instead of moving its centre, by the law of
total variance:

    var(total) = expected x dispersion  +  standard error squared

Which is the correct way to be cautious about a small sample. It converges on
the plain price as the sample grows, which is what should happen, and it stays
honest when the sample is genuinely thin. Havertz goes from 2.84 to 1.50, and
a three-match sample still shows a visible gap between fair and need.

One subtlety: extra variance usually hurts a bet, but when the expectation
sits below the line it helps, because a wider spread makes an unlikely total
more reachable. `need` takes whichever of the two views is worse, so it is
always a floor on the price you should accept.

Both fixes apply to team bets too, since they share the model.

The direction is now right: Arsenal's players price short, Coventry's price
long. The remaining gap is at team level rather than player level. The tier
estimate says Coventry manage 4.83 shots at Arsenal; the market implies nearer
7. If that team number is harsh then every Coventry player price is harsh in
proportion, and the fix is more matches behind the tier estimate rather than
anything in the player maths.

## Club colours

Each fixture is drawn in the two clubs' own colours rather than a fixed blue
and orange, so Newcastle against Liverpool looks different from Man City
against Bournemouth.

Kit colours cannot be used raw. Three things go wrong:

- **Contrast.** Newcastle's black vanishes on a dark background, Norwich's
  yellow on a light one, Wolves' gold on both.
- **Clash.** Manchester United against Liverpool is red against red. Arsenal
  against Forest, the same. You cannot tell whose line is whose.
- **Grey.** A monochrome club reads as an axis rather than as data.

So `clubcolour.py` treats the kit colour as a starting hue, not a final value.
Working in OKLab, it moves each colour into a legible lightness band for the
mode, floors its chroma so it does not read as grey, and then measures the
pair's separation under normal vision and under both red-green colour
blindnesses. If the two clubs are still too close, the away side is rotated
away in hue until they separate, so at least one team keeps its real colour.
Clubs with no usable hue get a slot from the validated palette.

The thresholds are not invented: they are the ones `dataviz`'s palette
validator enforces, and the output is checked against it. All 420 pairs from a
fifteen-club test set, across both light and dark, pass every check.

That test caught a real mistake. The first monochrome fallback was a slate
blue I picked because it looked right, and the validator failed it on the
chroma floor in both modes and on the lightness band in dark. Which is the
whole argument for running the validator instead of trusting your eye.

Colours are worked out at build time and shipped per fixture, then applied when
the fixture changes and again on a theme change, since the light and dark
values are separately chosen rather than one flipped. Reports built before this
existed keep the old defaults.

## How the Need price is worked out

`Fair` is what the record implies on its own. `Need` is the price to insist on
before staking. The first version of it was too blunt: it looked only at how
many matches went over the line and how many did not, so every 19 from 20 came
out at 1.31 regardless of the fixture. That throws away almost everything. A
team getting 4, 5, 3, 6, 4 corners and one getting 2, 2, 2, 2, 2 are both
"5 from 5 over 1.5", and one is far safer. It also never looked at the opponent.

`Need` now comes from a count model:

1. Take the opponent-adjusted expectation for this team in this fixture. That
   is the projection already on the page: league average times this team's
   attack rating times this opponent's defence rating, off the right home or
   away base. This is where the mismatch enters.
2. Fit the spread from the team's own matches. If the variance is close to the
   mean, counts behave like a Poisson process and Poisson is used. If the
   variance is larger, which is normal for shots, a negative binomial carries
   the extra spread across rather than quoting a price that is too short.
3. Read the probability off that distribution. A line of 1.5 asks for P(X >= 2).
4. Haircut for the fact the expectation is itself an estimate, by recomputing
   at the bottom of a one-sided 95% interval on the mean.

Both distributions were checked against scipy across 54 combinations of mean
and line, agreeing to machine precision.

The same record now prices very differently depending on who is playing:

| Bet, all on the same shape of 10-match record | Expected | Need |
|-----------------------------------------------|----------|------|
| Man City total shots over 9.5 v Bournemouth   | 17.2     | 1.05 |
| Arsenal first-half corners over 1.5 v Coventry| 3.4      | 1.26 |
| Arsenal first-half corners over 1.5 v Man City| 2.1      | 2.03 |
| Bournemouth total shots over 9.5 v Man City   | 9.8      | 2.59 |

Two guards sit on top of it.

The interval on the expectation is clipped to half and double the point
estimate. Ten matches of a noisy stat can produce a standard error big enough
to drag the lower bound to nothing, and a bound of nothing prices everything
at 20.0, which is not caution, it is noise wearing caution's clothes.

A pairing is dropped entirely when the model and the record contradict each
other beyond what either one's uncertainty allows, or when the projection is
less than half or more than double the team's own average. An adjustment
should move a team's average, that is its job, but it should not halve it. The
case that exposed this was an expected 0.46 second-half offsides for a side
that had gone over 0.5 in thirteen of twenty, which priced at 21.0. The number
dropped is shown on the page.

Where there is no opponent-adjusted expectation, which means one side could
not be rated, it falls back to the old record-only interval and tags the price
`record only`, because an invented expectation is worse than an honest blunt
number.

The Best bets tab can be ordered three ways. **Evidence** puts the strongest
combined records first. **Most likely** sorts by the model's probability, which
favours mismatches. **Best price** sorts the other way, surfacing the ones that
actually pay, which are the ones worth pricing up against a bookmaker.

## Standard of opposition (`--tiers`)

The opponent-adjusted projection needs a rating for both sides, and a
promoted club has none: every match on its record was played in a division
nobody else in the fit belongs to. Coventry came up with exactly one usable
match, away at Hull, who were also promoted, so the two of them were fitted
in a closed loop off a single Championship game. That is how Coventry ended
up projected for more corners at the Emirates than Arsenal.

`--tiers` reads last season's final tables for the division and the one
below, stacks them, and sorts every club into four bands:

| Band   | Where they finished                       |
|--------|-------------------------------------------|
| Top 6  | 1st to 6th                                |
| Upper  | 7th to 11th                               |
| Lower  | 12th to 17th                              |
| Bottom | 18th and below, plus every promoted club  |

Two things then become possible.

**The Opposition control** filters any team's record to matches against one
band. Arsenal's corner record against bottom-tier sides is a different and
far more relevant number from their record against everyone.

**The estimate.** When one side cannot be rated, the projection is taken
from the other side's record against bottom-tier opposition instead. Arsenal
at home to bottom-tier clubs gives both figures at once: what Arsenal
manage becomes Arsenal's number, and what those clubs manage at the Emirates
becomes Coventry's. No Coventry data is used at all, which is the point,
because their data is the part that does not carry across divisions.

Estimates are shown as `est` rather than `proj`, underlined with a dotted
rule, and hovering one lists the exact matches it came from. If there are
fewer than three usable matches even then, nothing is shown.

It wants a full season rather than ten games, otherwise there are barely any
bottom-tier matches to average:

    python run.py --league "Premier League" --games 38 --adjust --tiers --players

Last season's table is used, not this one. In August the current table is
three games old and would put whoever won on the opening weekend in the top
six.

## Track record (`track.py`)

The tool has no evidence yet that it beats the market, and neither does anything else after a few weeks. The only way to find out is to write picks down before kickoff at the price you could actually have got, settle them from the result, and count.

```bash
python track.py add --event 14083629 --team 2814 --stat "Total shots" \
                    --line 12.5 --side over --price 1.95 \
                    --rate 0.7 --need 1.68 --proj 13.1
python track.py settle
python track.py report
```

Three things are enforced rather than suggested, because a record that can be quietly tidied is worth nothing:

- a pick cannot be logged once the match has kicked off
- settlement reads the result from the API, so a loser cannot be dropped
- the model's numbers at the time are stored, so you can later ask whether its signal predicted anything

The report gives ROI with a 95% interval, and splits results by whether the price cleared the Need figure. If those two halves perform the same, the model is not adding anything and you have learned something valuable for the price of some record-keeping.

**Expect the interval to span zero for a long time.** Simulating a genuine 10% edge over 400 bets gave +6.3% ROI with an interval of -3.3% to +15.8%, still consistent with no edge at all. It needed about 900 settled bets to separate from luck. That is not a flaw in the tracker, it is what betting variance actually looks like, and it is the single most important number to know before selling anything.

## My slip

A fourth tab. Press Add on any Standout row and it lands here, scored out of 100:

- **Value, 45 points.** How far your price beats what the evidence supports. Carries the most weight because the record tells you what happened and only the price tells you whether the bet is worth making. A 10/10 record at 1.10 is a bad bet.
- **Evidence, 25 points.** How much data sits behind it.
- **Model, 15 points.** Whether the opponent-adjusted projection agrees with the record.
- **Context, 15 points.** Whether the record was built against the right standard of opposition.

The breakdown is always shown. A score you cannot interrogate is just an opinion with a number stuck on it.

Add more than one and it shows the combined price against the fair price, and how much better each leg would need to be priced to break even. It also states plainly what multiples do: the bookmaker's margin compounds, so at 5% per market a treble carries about 16% against you and a five-fold about 28%. Singles are where value survives.

## Weekly routine

```bash
python run.py --leagues premier_league,championship,la_liga --adjust
./publish.sh
```

That is the whole thing. No `git add`, no commit, no push for the reports.

Two reasons it stays cheap:

**Fetching is already incremental.** Finished matches never change, so their responses are cached permanently. A new gameweek only fetches that week's matches; everything before it is read off disk. The second run of a season is nearly instant regardless of how many leagues you build.

**Publishing does not grow the repo.** `publish.sh` force-pushes the built site to a `gh-pages` branch as a single commit, replacing whatever was there. `main` never carries a report, so it stays small forever. Committing a 3.5 MB file every gameweek would otherwise write the better part of a gigabyte into history over a season, for files that rebuild from cache in seconds.

One-time setup: Settings, Pages, Source "Deploy from a branch", Branch `gh-pages`, Folder `/ (root)`. The script also writes a `.nojekyll` file, which stops GitHub running the site through Jekyll, the step that failed during the outage.

Commit source changes to `main` as normal. Only generated output goes to `gh-pages`.

## The files

| File | What it does |
|---|---|
| `run.py` | Command line entry point. Start here. |
| `sofascore_api.py` | Fetching and caching. Every response saved to `cache/` before parsing. |
| `hitrates.py` | Parses match statistics, builds each team's form, works out the lines. |
| `report.py` | Generates the HTML. |
| `publish.sh` | Pushes the built site to gh-pages without growing the repo. |
| `track.py` | Logs picks before kickoff, settles them, reports honestly. |
| `make_index.py` | Builds the front page listing every report. |
| `check.py` | Probes endpoints when something breaks. |
| `explore.ipynb` | Your notebook. Keep it for experimenting. |
| `TEST.md` | The 21 questions. |
| `PLAN.md` | What this was meant to be, and what's left. |

## How the lines are chosen

There is no odds feed here, so the line for each stat is derived from the data: the median across both teams' matches, pushed down to the nearest .5 so there are no pushes. One line per stat, shared by both teams, so the two columns compare directly.

If you want real bookmaker lines, that's a separate feed and a separate problem.

## Things worth knowing

**Caching is permanent by design.** Finished matches never change, so their responses are cached forever. Fixture lists use a few hours. If you ever need to force a refetch, delete the relevant file in `cache/` or the whole folder. The folder grows slowly; `run.py` prints its size after each run.

**Friendlies are excluded automatically.** Matches are filtered to the same competition as the fixture, because pre-season friendlies appear in the same feed with no detailed statistics and would silently shrink your sample.

**Small samples lie.** Five matches is not evidence. A 4/5 hit rate and a 40/50 hit rate look the same in the percentage column and are not remotely the same thing. The chart is there so you can see whether a number is steady or two extremes averaged together, and the fraction is shown next to every percentage for the same reason.

**Cross-season samples are misleading.** "Last 10" can straddle a summer transfer window, which means half the sample describes a squad that no longer exists. Check the dates in the tooltips before trusting anything in August or September.

**This will break eventually.** It reads an undocumented API. If SofaScore rename a stat, `.get(name)` returns nothing and the row simply disappears rather than erroring. If rows vanish that you expect to be there, that's the first thing to check.

## Extending it

The obvious next moves:

- **Player props.** `sofascore_api.event_lineups()` is already there and returns per-player stats. Same pattern as `hitrates.team_form`, one level deeper.
- **Opponent stats.** Currently each record holds the team's own numbers. Store the opponent's too and you get "cards conceded", "shots faced" and so on.
- **Real lines.** Swap the median-derived line for a bookmaker's, and the hit rates become directly actionable rather than descriptive.
- **A watchlist.** Run it across every fixture on a Saturday and surface only the stats above some threshold.
