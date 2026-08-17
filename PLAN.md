# Fixture hit-rate dashboard: build plan

## What it does

Pick a fixture. See both teams' hit rates for every tracked stat, split by home form and away form, over the last 5 or 10 matches, with a small line chart per stat showing the game-by-game sequence.

Output is a self-contained HTML file that opens in a browser.

## Data sources

| Endpoint | Gives you |
|---|---|
| `/sport/football/scheduled-events/{YYYY-MM-DD}` | Fixtures for a date, to pick from |
| `/team/{team_id}/events/last/0` | A team's recent matches |
| `/event/{event_id}/statistics` | Team stats for one match: shots, corners, offsides, throw-ins, fouls, cards |
| `/event/{event_id}/lineups` | Per-player stats (already working, not needed for v1) |

## Progress

- [x] Fetch and parse JSON from a protected endpoint
- [x] Navigate nested dicts and lists
- [x] Flatten to a pandas table
- [x] Loop over matches with delays and error handling
- [x] Group and calculate hit rates
- [ ] **Part 1: caching layer**
- [ ] Part 2: read the statistics endpoint
- [ ] Part 3: home/away split
- [ ] Part 4: hit rates across all stats
- [ ] Part 5: HTML output with charts

---

## Part 1: caching

Every response saved to disk before parsing. Check the cache before every fetch.

Why it comes first:

- Reruns become instant instead of 40 seconds
- You stop hammering SofaScore, which is what gets IPs banned
- If they change the response format, you keep everything already collected in its original shape
- Finished matches never change, so a cached copy is permanent and correct

New concepts: `pathlib`, reading and writing files.

## Part 2: the statistics endpoint

Fetch `/event/{id}/statistics` for a finished match and work out its shape. It's nested more deeply than lineups: periods, then groups, then items, with each item holding a home and away value.

Goal: a function `match_stats(event_id)` returning a flat dict like
`{"Total shots": (14, 9), "Corner kicks": (7, 3), ...}`

New concepts: deeper nesting, tuples.

## Part 3: home and away split

For a given team, fetch their last N matches, work out whether they were home or away in each, and pull their own side's value for each stat.

The awkward bit: a stat's "home" value belongs to whichever team was at home, so you have to check which side your team was on before reading it. Getting this backwards silently gives you your opponents' numbers.

New concepts: conditional logic inside a loop, building a per-match record.

## Part 4: hit rates across all stats

For each stat and each line, count how often the team went over. Produce a table:

| Stat | Line | Last 5 | Last 10 | Home | Away | Sequence |
|---|---|---|---|---|---|---|
| Total shots | 12.5 | 4/5 | 7/10 | 4/5 | 3/5 | 14, 11, 16, 13, 9 |

Sensible default lines come from the team's own median, so they adapt per team rather than being hardcoded.

New concepts: nested loops over stats, working out sensible thresholds.

## Part 5: HTML output

Generate a standalone HTML file: one section per team, one row per stat, hit rate plus an inline SVG sparkline of the sequence.

Self-contained, so no internet needed to view it and it works from anywhere.

New concepts: building strings, inline SVG, writing files.

---

## Things to watch

- **Silent breakage.** If SofaScore renames a stat, `.get(name, 0)` returns 0 and nothing errors. Add a check that shouts when an expected stat is missing.
- **Match selection.** "Last 10" should mean 10 competitive matches in the same competition, not friendlies and cup ties mixed in. Worth filtering on tournament id.
- **Small samples.** Five matches is a small sample. A 4/5 hit rate is not strong evidence of anything. The chart matters more than the percentage, because it shows whether the number is stable or two extremes averaged.
