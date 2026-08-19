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
