"""
Does the model actually know anything? Settle every bet it would have made.

    python backtest.py --league "Premier League"
    python backtest.py --league "Premier League" --from 2025-10-01 --games 10
    python backtest.py --leagues "Premier League,Championship,LaLiga"

Walks past fixtures, rebuilds what the tool would have said the day before
each one, takes every bet the Best bets scan would have produced, and settles
it against what actually happened. Then buckets the predictions by their
stated probability and compares each bucket against the outcomes.

That comparison is the whole point. If the bets it calls 85% land 85% of the
time, the model is calibrated and `need` is a real price. If they land 70%,
every price the site quotes is too short and it has been quietly lying to you.
No amount of staring at the model from the inside can tell you which.

It runs entirely from the cache, so it makes no requests and cannot get your
IP blocked. Anything not already cached is skipped and counted.

THE THING THAT MATTERS: every fixture is built with `before` set to its own
kick-off, so the model can only see matches played earlier. Without that the
model reads the result of the match it is predicting, the output looks
extraordinary, and it means precisely nothing. That is lookahead bias and it
is the standard way a backtest flatters itself.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone

import hitrates
import markets
import model
import sofascore_api as api

# Same ladder and floor as the page: an over is tried at the median line and
# above, an under at the median and below.
LADDER = [-1, 0, 1]

# Buckets for the calibration table. Narrow near the top because that is where
# the bets are and where being wrong costs most.
BUCKETS = [(0.50, 0.65), (0.65, 0.75), (0.75, 0.82), (0.82, 0.88),
           (0.88, 0.93), (0.93, 0.97), (0.97, 1.01)]


def parse_date(text: str) -> float:
    return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


class Skipped(Exception):
    """Not in the cache. Counted, not fatal."""


_MISSES = {"count": 0}


def cache_only_get_json(path: str, max_age_hours=None, verbose: bool = True):
    """Stand-in for api.get_json that reads the cache and never fetches.

    Installed over the real one for the whole run rather than being called
    directly, because the fetch is reached through half a dozen helpers and
    patching each call site would leave a hole somewhere. A backtest that
    quietly started fetching would take days and put thousands of requests
    through your connection without asking, which is exactly what you would
    not want the moment you are worried about being blocked.
    """
    cache_file = api._cache_file(path)
    if not cache_file.exists():
        _MISSES["count"] += 1
        return None
    try:
        return json.loads(cache_file.read_text())
    except json.JSONDecodeError:
        _MISSES["count"] += 1
        return None


def cached_only(path: str, max_age_hours=None):
    data = cache_only_get_json(path)
    if data is None:
        raise Skipped(path)
    return data


class Backtester:
    def __init__(self, tournament_id: int, games: int, verbose: bool = True):
        self.tournament_id = tournament_id
        self.games = games
        self.verbose = verbose
        self.ratings_cache: dict = {}
        self.skipped = 0
        self.rows: list[dict] = []

    # ---------------------------------------------------------------- data

    def form(self, team_id: int, before: float) -> list[dict]:
        return hitrates.team_form(
            team_id=team_id, team_name=str(team_id),
            tournament_id=self.tournament_id, limit=self.games,
            verbose=False, before=before,
        )

    def ratings_as_of(self, team_ids: list[int], before: float):
        """Fit the league as it stood on a given day.

        Cached per day rather than per fixture: a Saturday's ten matches all
        see the same table, and refitting twenty teams ten times over would be
        the slowest part of this by a distance.
        """
        key = int(before // 86400)
        if key in self.ratings_cache:
            return self.ratings_cache[key]

        by_team = {}
        for team_id in team_ids:
            try:
                records = self.form(team_id, before)
            except Skipped:
                self.skipped += 1
                continue
            if records:
                by_team[team_id] = records

        if len(by_team) < 4:
            self.ratings_cache[key] = None
            return None

        names = hitrates.stat_names(*by_team.values())
        fitted = (hitrates.league_ratings(by_team, names), names)
        self.ratings_cache[key] = fitted
        return fitted

    # ------------------------------------------------------------ settling

    def actual(self, event_id: int) -> dict:
        """What the match actually produced, by period and stat."""
        raw = cached_only(f"event/{event_id}/statistics")
        stats = hitrates.extract_match_stats(raw)
        if not stats:
            raise Skipped(f"event/{event_id}/statistics empty")
        return stats

    # ------------------------------------------------------------- one tie

    def fixture(self, event: dict, team_ids: list[int]) -> None:
        kickoff = event.get("startTimestamp")
        if not kickoff:
            return

        home = event["homeTeam"]
        away = event["awayTeam"]

        try:
            outcome = self.actual(event["id"])
            records = [self.form(home["id"], kickoff), self.form(away["id"], kickoff)]
        except Skipped:
            self.skipped += 1
            return

        if not all(records) or min(len(r) for r in records) < 4:
            return

        fitted = self.ratings_as_of(team_ids, kickoff)
        projection = {}
        if fitted:
            ratings, league_names = fitted
            projection = hitrates.project_fixture(
                ratings, home["id"], away["id"], league_names
            )

        names = hitrates.stat_names(*records, bettable_only=True)
        lines = hitrates.suggest_lines(records, names)

        for period in hitrates.PERIODS:
            if period not in outcome:
                continue

            for stat in names.get(period, []):
                if stat not in markets.BETTABLE_STATS:
                    continue

                suggested = (lines.get(period) or {}).get(stat)
                if suggested is None:
                    continue

                truth = outcome[period].get(stat)
                if truth is None:
                    continue

                for side in (0, 1):
                    self.candidate(side, stat, period, suggested, records,
                                   projection, truth, event)

    def candidate(self, side, stat, period, suggested, records, projection,
                  truth, event) -> None:
        """One team, one stat, one period: every line and direction it offers."""
        attack_venue = "home" if side == 0 else "away"
        defend_venue = "away" if side == 0 else "home"

        for_vals = [
            r["stats"].get(period, {}).get(stat)
            for r in records[side] if r["venue"] == attack_venue
        ]
        against_vals = [
            r["against"].get(period, {}).get(stat)
            for r in records[1 - side] if r["venue"] == defend_venue
        ]
        for_vals = [v for v in for_vals if v is not None]
        against_vals = [v for v in against_vals if v is not None]

        if len(for_vals) < 3 or len(against_vals) < 3:
            return

        expected = (projection.get(period, {}).get(stat) or [None, None])[side]
        landed_value = truth[side]

        for step in LADDER:
            line = suggested + step
            if line < 0.5:
                continue

            for over in (True, False):
                if over and step < 0:
                    continue
                if not over and step > 0:
                    continue

                k_for = sum(1 for v in for_vals if (v > line) == over)
                k_agn = sum(1 for v in against_vals if (v > line) == over)
                p_for = k_for / len(for_vals)
                p_agn = k_agn / len(against_vals)

                if p_for < model.MATCHUP_FLOOR or p_agn < model.MATCHUP_FLOOR:
                    continue

                hits = k_for + k_agn
                total = len(for_vals) + len(against_vals)

                priced = model.price(line, over, expected, for_vals, hits, total)
                if priced["conflict"]:
                    continue

                won = (landed_value > line) == over

                self.rows.append({
                    "date": datetime.fromtimestamp(
                        event["startTimestamp"], tz=timezone.utc).strftime("%Y-%m-%d"),
                    "fixture": f"{event['homeTeam']['name']} v {event['awayTeam']['name']}",
                    "stat": stat, "period": period, "line": line, "over": over,
                    "p_model": priced["p"],
                    "p_record": hits / total,
                    "source": priced["source"],
                    "need": priced["need"],
                    "won": won,
                })


# ------------------------------------------------------------------ report


def calibration(rows: list[dict], key: str, label: str) -> None:
    print(f"\n{label}")
    print(f"  {'predicted':>14}  {'n':>6}  {'said':>7}  {'actual':>7}  {'gap':>7}")
    print("  " + "-" * 50)

    for low, high in BUCKETS:
        bucket = [r for r in rows if low <= r[key] < high]
        if not bucket:
            continue
        said = sum(r[key] for r in bucket) / len(bucket)
        actual = sum(1 for r in bucket if r["won"]) / len(bucket)
        gap = actual - said
        flag = "" if abs(gap) < 0.03 else ("  optimistic" if gap < 0 else "  cautious")
        print(f"  {low:.0%} to {high:.0%}".ljust(16)
              + f"  {len(bucket):>6}  {said:>6.1%}  {actual:>6.1%}  {gap:>+6.1%}{flag}")

    brier = sum((r[key] - (1 if r["won"] else 0)) ** 2 for r in rows) / len(rows)
    print(f"\n  Brier score: {brier:.4f}   (lower is better, 0.25 is a coin flip)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", help="one competition by name")
    parser.add_argument("--leagues", help="several, comma separated")
    parser.add_argument("--games", type=int, default=10,
                        help="matches of form the model may look back on")
    parser.add_argument("--from", dest="since", default=None,
                        help="only fixtures on or after this date, YYYY-MM-DD")
    parser.add_argument("--csv", help="write every settled bet to this file")
    args = parser.parse_args()

    # Nothing below this line may touch the network.
    api.get_json = cache_only_get_json

    wanted = []
    if args.leagues:
        wanted = [x.strip() for x in args.leagues.split(",") if x.strip()]
    elif args.league:
        wanted = [args.league]
    else:
        raise SystemExit("Pass --league or --leagues.")

    since = parse_date(args.since) if args.since else 0
    all_rows: list[dict] = []
    total_skipped = 0

    for name in wanted:
        key = name.lower().replace("-", "_").replace(" ", "_")
        tournament_id = api.TOURNAMENTS.get(key)
        if tournament_id is None and key.isdigit():
            tournament_id = int(key)
        if tournament_id is None:
            print(f"unknown league '{name}', skipping")
            continue

        print(f"\n{'=' * 62}\n{name}\n{'=' * 62}")

        try:
            team_ids = api.tournament_team_ids(tournament_id)
        except Exception:
            team_ids = []
        if len(team_ids) < 4:
            print("  could not read the team list from cache, skipping")
            continue

        tester = Backtester(tournament_id, args.games)

        # Every finished fixture any of these clubs played, de-duplicated.
        seen = set()
        fixtures = []
        for team_id in team_ids:
            try:
                events = hitrates.collect_events(
                    team_id, tournament_id, team_name=str(team_id), verbose=False)
            except Skipped:
                continue
            for event in events:
                if event["id"] in seen:
                    continue
                if (event.get("startTimestamp") or 0) < since:
                    continue
                seen.add(event["id"])
                fixtures.append(event)

        fixtures.sort(key=lambda e: e.get("startTimestamp", 0))
        print(f"  {len(fixtures)} finished fixture(s) to replay")

        for i, event in enumerate(fixtures, start=1):
            tester.fixture(event, team_ids)
            if i % 10 == 0:
                print(f"    {i}/{len(fixtures)}, {len(tester.rows)} bets settled", end="\r")

        print(f"    {len(fixtures)}/{len(fixtures)}, {len(tester.rows)} bets settled     ")
        all_rows.extend(tester.rows)
        total_skipped += tester.skipped

    if not all_rows:
        raise SystemExit(
            "\nNothing to settle. Either nothing is cached for those leagues, or "
            "\nevery fixture was too early to have enough form behind it. Build the "
            "\nleague normally first so the cache fills, then re-run this."
        )

    print(f"\n\n{'=' * 62}")
    print(f"{len(all_rows)} settled bets"
          + (f", {_MISSES['count']} lookups missing from the cache" if _MISSES["count"] else ""))
    print("=" * 62)

    modelled = [r for r in all_rows if r["source"] == "model"]

    # The comparison that decides whether any of the modelling was worth it.
    calibration(all_rows, "p_record", "RAW HIT RATE, no opponent adjustment")
    if modelled:
        calibration(modelled, "p_model", "COUNT MODEL, opponent adjusted")

        record_brier = sum(
            (r["p_record"] - (1 if r["won"] else 0)) ** 2 for r in modelled) / len(modelled)
        model_brier = sum(
            (r["p_model"] - (1 if r["won"] else 0)) ** 2 for r in modelled) / len(modelled)
        print(f"\n  On the same {len(modelled)} bets:")
        print(f"    raw hit rate Brier {record_brier:.4f}")
        print(f"    count model  Brier {model_brier:.4f}")
        better = "the model" if model_brier < record_brier else "the raw hit rate"
        print(f"    -> {better} is better by {abs(model_brier - record_brier):.4f}")

    overall = sum(1 for r in all_rows if r["won"]) / len(all_rows)
    said = sum(r["p_model"] for r in all_rows) / len(all_rows)
    print(f"\n  Overall: said {said:.1%}, landed {overall:.1%}")
    if overall < said - 0.02:
        print("  The model is overconfident. Every price it quotes is too short.")
    elif overall > said + 0.02:
        print("  The model is too cautious. It is leaving value on the table.")
    else:
        print("  Calibrated to within two points. The prices mean what they say.")

    if args.csv:
        import csv
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(all_rows[0]))
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\n  Every settled bet written to {args.csv}")


if __name__ == "__main__":
    main()
