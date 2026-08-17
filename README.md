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
python run.py --league premier_league --players
```

`--league` reads the team list off the league table, so you don't have to know twenty ids, then collapses each team's next fixture into a round. Known names: `premier_league`, `championship`, `la_liga`, `serie_a`, `bundesliga`, `ligue_1`, `champions_league`, `europa_league`. Any other competition works by passing its uniqueTournament id.

A report can hold as many fixtures as you like, with a dropdown at the top to switch between them. All the filters and edited lines are per fixture.

## What it costs in requests

Roughly, per fixture:

| | Requests | Time |
|---|---|---|
| Team stats only | about 25 | 40 seconds |
| With `--players` | about 45 | 75 seconds |

So five fixtures with players is around 220 requests and six minutes, which is comfortably within what SofaScore will tolerate at a 1 to 2 second delay. Two things make it cheaper than that arithmetic suggests:

- **Teams in the same league share matches.** Building every fixture in a LaLiga round means each match's statistics is fetched once and reused by both teams involved, so the marginal cost per extra fixture drops as you add more.
- **Nothing is fetched twice, ever.** Re-running is instant, and adding `--players` to a fixture you already built only fetches the lineups.

Running a full weekend's card the night before is entirely reasonable. Running it repeatedly in a tight loop is not, and would get your IP blocked.

Useful flags: `--players` to include per-player stats, `--games 20` for a deeper sample, `--show 10` to list more fixtures, `--no-open` to skip launching the browser.

## In the report

**Team stats tab.** One row per stat. Every line is editable: type a number, or use the plus and minus buttons, and both teams' hit rates recompute instantly. The buttons move by a whole unit and keep the .5, so 13.5 goes to 14.5, never 14. That matters because a line ending in .5 can never be exactly matched, so there is no ambiguity about whether a match hit it. An edited line is shown in bold so you can see which are yours and which came from the data. "Reset lines" puts them all back.

**Players tab.** Present when you ran with `--players`. Pick a stat, set a line, set a minimum number of appearances, and both squads are ranked by hit rate. It respects the same last 5 / last 10 and home / away filters as the team tab, so "last 5 at home" means the same thing in both.

**Period.** Full match, first half or second half. Each period keeps its own lines, because a first-half shots line has nothing to do with a full-match one, and its own hit rates and charts. The halves come straight from SofaScore rather than being derived, since summing the halves does not reliably reproduce the full-match figure.

Player stats are full match only. SofaScore doesn't publish per-player numbers by half.

Hovering any point on a chart gives you the date, opponent and value.

It works team-first rather than date-first because SofaScore removed their date-based fixture endpoint. `check.py` is the script that established that, and it's worth keeping: if something else breaks later, add the suspect path to its list and run it.

The report lands in `reports/` and opens automatically. Inside it you can switch between last 5, last 10 and all, and between all matches, home only and away only. Hover any point on a chart for the date, opponent and value.

## The files

| File | What it does |
|---|---|
| `run.py` | Command line entry point. Start here. |
| `sofascore_api.py` | Fetching and caching. Every response saved to `cache/` before parsing. |
| `hitrates.py` | Parses match statistics, builds each team's form, works out the lines. |
| `report.py` | Generates the HTML. |
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
