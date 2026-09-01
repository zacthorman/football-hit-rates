"""
Does the model actually know anything? Settle every bet it would have made.

    python backtest.py --league "Premier League"
    python backtest.py --league "Premier League" --from 2025-10-01 --games 10
    python backtest.py --leagues "Premier League,Championship,LaLiga"
    python backtest.py --league "Premier League" --players

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

Player bets are opt-in via --players, so the team-only behaviour every
existing number was produced under stays the default. They settle with two
extra rules of their own: the lineup of the match being predicted is read
only to settle the bet, never to price it, and a player who does not appear
-- or plays under the page's 45-minute appearance bar -- is VOID rather
than lost, exactly as a bookmaker would grade it. Voids are counted and
reported, not buried.
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
    def __init__(self, tournament_id: int, games: int, verbose: bool = True,
                 players: bool = False):
        self.tournament_id = tournament_id
        self.games = games
        self.verbose = verbose
        self.players = players
        self.ratings_cache: dict = {}
        self.skipped = 0
        self.player_skipped = 0
        self.rows: list[dict] = []
        self.player_rows: list[dict] = []

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

        if self.players:
            self.player_bets(event, records, projection)

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


    # --------------------------------------------------------- player bets

    def player_form(self, team_id: int, before: float) -> list[dict]:
        """One record per player per match, strictly before kick-off.

        current_squad_only is off, deliberately, where the production build
        leaves it on. Today's squad is information from after the fixtures
        being replayed: judged from March, a player who left in June was
        still there, and filtering him out with knowledge of the transfer
        is a small lookahead of its own. Keeping everyone who actually
        played is the season-correct view, and a bet on someone who later
        moved settles as void anyway when he is not in the lineup.
        """
        return hitrates.player_form(
            team_id=team_id, team_name=str(team_id),
            tournament_id=self.tournament_id, limit=self.games,
            verbose=False, current_squad_only=False, before=before,
        )

    def player_adjustment(self, stat, team_index, records, projection) -> float:
        """playerAdjustment() from the page, fed the backtest's own inputs.

        The team projection for the paired market over the team's own mean,
        clipped only against a near-zero denominator. When the fixture has
        no projection the answer is 1, which is also what the page does
        when a report carries none.
        """
        team_stat = model.PLAYER_STAT_TO_TEAM.get(stat)
        if not team_stat:
            return 1.0
        pair = (projection.get("ALL") or {}).get(team_stat)
        if not pair or pair[team_index] is None:
            return 1.0
        values = [r["stats"].get("ALL", {}).get(team_stat)
                  for r in records[team_index]]
        values = [v for v in values if v is not None]
        if len(values) < 3:
            return 1.0
        mean = sum(values) / len(values)
        if mean <= 0:
            return 1.0
        return min(2.5, max(0.2, pair[team_index] / mean))

    def player_bets(self, event, records, projection) -> None:
        """Price and settle every player line the page would have quoted.

        Mirrors scanPlayerBets(): overs only, at the suggested line, gated
        on the record -- shrunk towards the market's own base rate by
        model.gate_rate() -- clearing MATCHUP_FLOOR, priced through
        pricePlayer with the positional prior. Goals is excluded here
        exactly as on the page, and for the reason measured by this very
        tool: no player sustains a scoring rate any floor would accept, so
        every goals record that qualified was a lucky streak, and the
        quoted set landed 21.8% against an 82.5% average pre-match record. Two deliberate departures, both in the
        direction of measuring more rather than less: no minimum
        appearances, because the thin blended branch is the thing this
        exists to measure and the scan's default minimum of four would
        never reach it; and no three-per-fixture cap, because the cap is
        page furniture and every priced row is a data point here.

        The asymmetry that keeps this honest: the lineup of the match being
        predicted is read once, into `lineups`, and nothing derived from it
        touches a price -- it exists only to settle. Form, lines, priors and
        adjustments are all built from player_form called with
        before=kick-off, which filters strictly earlier, and the assertions
        below turn any leak of the fixture's own match id into a crash
        rather than a quietly flattering number.
        """
        kickoff = event["startTimestamp"]
        try:
            lineups = cached_only(f"event/{event['id']}/lineups")
        except Skipped:
            self.player_skipped += 1
            return

        squads = [
            self.player_form(event["homeTeam"]["id"], kickoff),
            self.player_form(event["awayTeam"]["id"], kickoff),
        ]
        if not any(squads):
            return

        stats = hitrates.player_stat_names(*squads, bettable_only=True)
        lines = hitrates.suggest_player_lines(squads, stats)

        for team_index in (0, 1):
            recs = squads[team_index]
            if not recs:
                continue

            # The same match window the team scan uses, venue pooled: a
            # player's sample does not survive being halved by venue.
            allowed = {r["id"] for r in records[team_index]}
            assert event["id"] not in allowed, \
                "form window contains the fixture being predicted"
            assert all(r["match_id"] != event["id"] for r in recs), \
                "player form contains the fixture being predicted"

            by_player: dict[str, list[dict]] = {}
            for r in recs:
                if r["match_id"] in allowed:
                    by_player.setdefault(r["player"], []).append(r)

            side = "home" if team_index == 0 else "away"

            for stat in stats:
                if stat not in model.PLAYER_STAT_TO_TEAM:
                    continue
                if stat in model.PLAYER_SCAN_EXCLUDE:
                    continue
                line = lines.get(stat)
                if line is None:
                    continue
                adjustment = self.player_adjustment(
                    stat, team_index, records, projection)

                # The market's own base rate at this line: every appearance
                # by every player in this squad's window, the population a
                # record must stand out from before the gate lets it in.
                base_k = base_n = 0
                apps_by_name: dict[str, list[dict]] = {}
                for name, played in by_player.items():
                    apps = model.appearances(
                        played, stat, hitrates.PLAYER_ZERO_FILL)
                    apps_by_name[name] = apps
                    for a in apps:
                        base_n += 1
                        if a["value"] > line:
                            base_k += 1
                base = base_k / base_n if base_n else 0.0

                for name, played in by_player.items():
                    apps = apps_by_name[name]
                    if not apps:
                        continue
                    vals = [a["value"] for a in apps]
                    hits = sum(1 for v in vals if v > line)
                    if model.gate_rate(hits, len(vals), base) \
                            < model.MATCHUP_FLOOR:
                        continue

                    prior = model.position_prior(
                        by_player, played[0].get("position") or "", stat,
                        name, hitrates.PLAYER_ZERO_FILL)
                    priced = model.price_player(
                        apps, line, True, adjustment, prior)
                    if not math.isfinite(priced["fair"]):
                        continue

                    result = self.settle_player(
                        lineups, side, played[0].get("player_id"), stat, line)

                    self.player_rows.append({
                        "date": datetime.fromtimestamp(
                            kickoff, tz=timezone.utc).strftime("%Y-%m-%d"),
                        "fixture": (f"{event['homeTeam']['name']} v "
                                    f"{event['awayTeam']['name']}"),
                        "team": event[
                            "homeTeam" if team_index == 0 else "awayTeam"
                        ]["name"],
                        "player": name,
                        "stat": stat, "line": line, "over": True,
                        "apps": len(vals),
                        "p_model": priced["p"],
                        "p_record": hits / len(vals),
                        "source": priced["source"],
                        "need": priced["need"],
                        "result": result,
                        "won": result == "won",
                    })

    def settle_player(self, lineups, side, player_id, stat, line) -> str:
        """won, lost, or void, by the page's own appearance rule.

        A bet on a player who does not appear is void, not lost: the
        bookmaker refunds it and it is not an event. The page's bar for an
        appearance is MIN_MINUTES, below which a record is a cameo, and
        settlement uses the same bar so the backtest grades bets the way
        the sample that priced them was built. The stat value goes through
        _player_stat_values, the same zero-fill as everywhere else: a
        player who appeared and has no key for a counting stat did none of
        it, and that is a settled loss on an over, not a void.
        """
        entries = (lineups.get(side) or {}).get("players") or []
        entry = next(
            (e for e in entries
             if (e.get("player") or {}).get("id") == player_id), None)
        if entry is None:
            return "void_absent"
        values = hitrates._player_stat_values(entry.get("statistics") or {})
        if not values:
            return "void_absent"
        if values.get("Minutes", 0) < model.MIN_MINUTES:
            return "void_cameo"
        actual = values.get(stat)
        if actual is None:
            return "void_absent"
        return "won" if actual > line else "lost"


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


def _production_games(fallback: int = 38) -> int:
    """The form window the scheduled build uses, read from update.json."""
    try:
        import json
        from pathlib import Path as _Path
        config = _Path(__file__).parent / "update.json"
        return int(json.loads(config.read_text(encoding="utf-8"))["games"])
    except Exception:
        return fallback


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", help="one competition by name")
    parser.add_argument("--leagues", help="several, comma separated")
    # Defaults to whatever the scheduled build actually uses, not a number
    # of its own.
    #
    # It used to default to 10 while update.json built the live site with 38,
    # so every calibration figure this tool produced described a model nobody
    # was betting off. The gap it reported was 8.2 points; the site's real one
    # at 38 matches is 5.8. A backtest that measures a different model from the
    # one in production is worse than no backtest, because it is believed.
    parser.add_argument("--games", type=int, default=_production_games(),
                        help="matches of form the model may look back on "
                             "(defaults to the games setting in update.json)")
    parser.add_argument("--from", dest="since", default=None,
                        help="only fixtures on or after this date, YYYY-MM-DD")
    parser.add_argument("--csv", help="write every settled bet to this file")
    # Off by default on purpose: every calibration number ever quoted from
    # this tool, including the fitted CALIBRATION constants, came from the
    # team-only run, and a default that silently widened the population
    # would change what those numbers mean without anyone deciding it.
    parser.add_argument("--players", action="store_true",
                        help="also price and settle player bets, reported "
                             "separately (team-only output is unchanged)")
    parser.add_argument("--player-csv",
                        help="write every player bet, voids included, "
                             "to this file")
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
    all_player_rows: list[dict] = []
    total_skipped = 0
    player_skipped = 0

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
            roster = api.tournament_team_ids(tournament_id)
        except Exception:
            roster = []
        if len(roster) < 4:
            print("  could not read the team list from cache, skipping")
            continue

        tester = Backtester(tournament_id, args.games, players=args.players)

        def competition_of(event: dict):
            return (event.get("tournament", {})
                    .get("uniqueTournament", {}).get("id"))

        # Harvest every finished fixture these clubs played, de-duplicated.
        # collect_events falls back to all competitive matches when a club is
        # short of history in this competition, which is right when building
        # form but wrong as a source of fixtures to settle: it is how a
        # "Premier League" backtest came to quietly settle a promoted club's
        # entire Championship season, playoffs and cup ties, and to answer a
        # different question from the one printed at the top. So harvest
        # loosely, then keep only fixtures actually tagged with this
        # competition, and say how many were dropped.
        seen = set()
        fixtures = []

        def harvest(team_id: int) -> None:
            try:
                events = hitrates.collect_events(
                    team_id, tournament_id, team_name=str(team_id), verbose=False)
            except Skipped:
                return
            for event in events:
                if event["id"] in seen:
                    continue
                if (event.get("startTimestamp") or 0) < since:
                    continue
                seen.add(event["id"])
                fixtures.append(event)

        for team_id in roster:
            harvest(team_id)

        # The roster above is today's table, but the fixtures being replayed
        # may belong to an earlier season. A club relegated since then is not
        # on today's table, so none of its own matches were harvested, and a
        # fixture between two such clubs would be missed entirely. Any club
        # appearing in this competition's fixtures belongs in the replay, so
        # keep harvesting until no new club turns up.
        harvested = set(roster)
        while True:
            discovered = {
                event[side]["id"]
                for event in fixtures if competition_of(event) == tournament_id
                for side in ("homeTeam", "awayTeam")
            } - harvested
            if not discovered:
                break
            for team_id in discovered:
                harvest(team_id)
            harvested |= discovered

        replay = [e for e in fixtures if competition_of(e) == tournament_id]
        excluded = len(fixtures) - len(replay)
        replay.sort(key=lambda e: e.get("startTimestamp", 0))

        # Ratings are fitted over the clubs that appear in the replayed
        # fixtures, not over today's table. Replaying last season with this
        # season's roster leaves every relegated club unrated -- all of their
        # bets silently fall back to raw-record pricing -- and lets the
        # promoted clubs drag their old division's numbers into the league
        # average. The fixtures themselves are the season-correct roster.
        team_ids = sorted({
            e[side]["id"] for e in replay for side in ("homeTeam", "awayTeam")
        })

        print(f"  {len(replay)} finished fixture(s) to replay, "
              f"{len(team_ids)} club(s) involved")
        if excluded:
            print(f"  {excluded} fixture(s) excluded as other competitions "
                  f"(cups, playoffs, another division): this backtest settles "
                  f"only {name} matches")

        for i, event in enumerate(replay, start=1):
            tester.fixture(event, team_ids)
            if i % 10 == 0:
                print(f"    {i}/{len(replay)}, {len(tester.rows)} bets settled", end="\r")

        note = (f", {len(tester.player_rows)} player rows"
                if args.players else "")
        print(f"    {len(replay)}/{len(replay)}, {len(tester.rows)} bets settled{note}     ")
        all_rows.extend(tester.rows)
        all_player_rows.extend(tester.player_rows)
        total_skipped += tester.skipped
        player_skipped += tester.player_skipped

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

    if all_player_rows:
        settled = [r for r in all_player_rows if r["result"] in ("won", "lost")]
        absent = sum(1 for r in all_player_rows if r["result"] == "void_absent")
        cameo = sum(1 for r in all_player_rows if r["result"] == "void_cameo")

        print(f"\n\n{'=' * 62}")
        print(f"PLAYER BETS: {len(settled)} settled, {absent + cameo} void "
              f"({absent} did not appear, {cameo} under "
              f"{model.MIN_MINUTES} minutes)"
              + (f", {player_skipped} fixture(s) without a cached lineup"
                 if player_skipped else ""))
        print("=" * 62)
        print("  A void is a bookmaker's refund, not a loss or a win. Voids")
        print("  are excluded from every table below and counted here only.")

        if settled:
            below = sum(1 for r in settled if r["p_model"] < BUCKETS[0][0])
            if below:
                print(f"\n  {below} settled bet(s) priced under "
                      f"{BUCKETS[0][0]:.0%} sit outside the bucket table but "
                      f"inside every Brier score.")

            calibration(settled, "p_model", "ALL PLAYER BETS")

            thin = [r for r in settled if r["source"] == "blend"]
            if thin:
                calibration(thin, "p_model",
                            "THIN PLAYER BETS, blended prior (under 3 "
                            "appearances) -- today's change")
            established = [r for r in settled if r["source"] == "model"]
            if established:
                calibration(established, "p_model",
                            "ESTABLISHED PLAYER BETS, own record (3+ "
                            "appearances)")
            record = [r for r in settled if r["source"] == "record"]
            if record:
                calibration(record, "p_model",
                            "RECORD-ONLY PLAYER BETS, no prior to blend")

            said = sum(r["p_model"] for r in settled) / len(settled)
            landed = sum(1 for r in settled if r["won"]) / len(settled)
            print(f"\n  Player bets overall: said {said:.1%}, "
                  f"landed {landed:.1%} of settled bets")

    if args.player_csv and all_player_rows:
        import csv
        with open(args.player_csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle,
                                    fieldnames=list(all_player_rows[0]))
            writer.writeheader()
            writer.writerows(all_player_rows)
        print(f"\n  Every player bet written to {args.player_csv}")

    if args.csv:
        import csv
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(all_rows[0]))
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\n  Every settled bet written to {args.csv}")


if __name__ == "__main__":
    main()
