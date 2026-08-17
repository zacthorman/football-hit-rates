"""
Turn SofaScore match statistics into per-team form and hit rates.

The statistics endpoint is nested three deep:

    statistics -> [period] -> groups -> [group] -> statisticsItems -> [item]

Each item carries a display name ("Total shots") and two numbers, one for the
home team and one for the away team. So for any given team you have to know
which side they were on before reading a value. Getting that backwards
silently gives you their opponents' numbers, which is the sort of bug that
never throws an error and quietly ruins everything downstream.
"""

from __future__ import annotations

import statistics as stats_lib
from datetime import datetime, timezone

import sofascore_api as api

# Shown first, in this order, when present. Anything else the endpoint
# returns is still collected and appears after these.
PREFERRED_STATS = [
    "Total shots",
    "Shots on target",
    "Shots off target",
    "Blocked shots",
    "Corner kicks",
    "Offsides",
    "Fouls",
    "Yellow cards",
    "Throw-ins",
    "Big chances",
    "Ball possession",
    "Passes",
    "Tackles",
]

# Stats where a hit-rate line makes no sense or reads oddly.
SKIP_STATS = {"Ball possession"}


def _as_number(value):
    """Coerce a statistics value to a float, or None if it isn't one.

    SofaScore mixes types: plain ints, percentage strings like '52%', and
    fraction strings like '14/20'. For a fraction the first number is the
    successful count, which is the one worth having.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip().replace("%", "")
    if "/" in text:
        text = text.split("/")[0]
    if "(" in text:
        text = text.split("(")[0]
    try:
        return float(text.strip())
    except ValueError:
        return None


PERIODS = {"ALL": "Full match", "1ST": "First half", "2ND": "Second half"}


def extract_match_stats(
    stats_json: dict | None,
) -> dict[str, dict[str, tuple[float, float]]]:
    """One match's statistics as {period: {name: (home_value, away_value)}}.

    SofaScore sends the full match plus each half separately, so all three
    are kept in separate buckets. Don't be tempted to derive one from the
    others: summing the halves does not reliably reproduce the full-match
    figure, because a few stats are counted on different bases.
    """
    if not stats_json:
        return {}

    out: dict[str, dict[str, tuple[float, float]]] = {}

    for period in stats_json.get("statistics", []):
        key = period.get("period")
        if key not in PERIODS:
            continue

        bucket: dict[str, tuple[float, float]] = {}
        for group in period.get("groups", []):
            for item in group.get("statisticsItems", []):
                name = item.get("name")
                if not name:
                    continue
                home = _as_number(item.get("homeValue", item.get("home")))
                away = _as_number(item.get("awayValue", item.get("away")))
                if home is None or away is None:
                    continue
                bucket[name] = (home, away)

        if bucket:
            out[key] = bucket

    return out


def _match_date(event: dict) -> str:
    ts = event.get("startTimestamp")
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def collect_events(
    team_id: int,
    tournament_id: int | None = None,
    pages: int = 2,
) -> list[dict]:
    """Gather a team's finished matches, newest last.

    Filtering by tournament matters more than it looks. Pre-season friendlies
    appear in the same feed but carry no detailed statistics, so leaving them
    in produces empty rows and a much smaller sample than you think you have.
    """
    events: list[dict] = []
    for page in range(pages):
        events.extend(api.team_events(team_id, page))

    # Pages overlap occasionally, so de-duplicate on id.
    seen = set()
    unique = []
    for event in events:
        if event["id"] in seen:
            continue
        seen.add(event["id"])
        unique.append(event)

    unique.sort(key=lambda e: e.get("startTimestamp", 0))

    def keep(event: dict) -> bool:
        if event.get("status", {}).get("type") != "finished":
            return False
        if tournament_id is None:
            return True
        unique_tid = (
            event.get("tournament", {}).get("uniqueTournament", {}).get("id")
        )
        return unique_tid == tournament_id

    return [e for e in unique if keep(e)]


def team_form(
    team_id: int,
    team_name: str,
    tournament_id: int | None = None,
    limit: int = 10,
    verbose: bool = True,
) -> list[dict]:
    """Build one record per match for a team, newest last.

    Each record holds the team's own value for every stat, plus who they
    played, where, and the score.
    """
    events = collect_events(team_id, tournament_id)
    events = events[-limit:]

    if verbose:
        print(f"  {team_name}: {len(events)} matches to fetch")

    records = []
    for i, event in enumerate(events, start=1):
        event_id = event["id"]
        raw = api.event_statistics(event_id)
        match_stats = extract_match_stats(raw)

        if not match_stats:
            if verbose:
                print(f"    {i}/{len(events)} {event_id} no statistics, skipped")
            continue

        is_home = event.get("homeTeam", {}).get("id") == team_id
        opponent = (event.get("awayTeam") if is_home else event.get("homeTeam")) or {}

        home_score = event.get("homeScore", {}).get("current", 0)
        away_score = event.get("awayScore", {}).get("current", 0)
        goals_for, goals_against = (
            (home_score, away_score) if is_home else (away_score, home_score)
        )

        # Index 0 is the home value, index 1 the away value. This single
        # line is where a mistake would silently swap both teams' numbers.
        own_index = 0 if is_home else 1

        records.append(
            {
                "id": event_id,
                "date": _match_date(event),
                "opponent": opponent.get("shortName") or opponent.get("name", "?"),
                "venue": "home" if is_home else "away",
                "goals_for": goals_for,
                "goals_against": goals_against,
                "result": (
                    "W" if goals_for > goals_against
                    else "D" if goals_for == goals_against
                    else "L"
                ),
                # {period: {stat: this team's value}}
                "stats": {
                    period: {
                        name: values[own_index] for name, values in bucket.items()
                    }
                    for period, bucket in match_stats.items()
                },
            }
        )

        if verbose:
            periods = "/".join(sorted(match_stats, key=list(PERIODS).index))
            print(
                f"    {i}/{len(events)} {event_id} {event.get('homeTeam', {}).get('shortName', '?')}"
                f" v {event.get('awayTeam', {}).get('shortName', '?')}"
                f" ({len(match_stats.get('ALL', {}))} stats, {periods})"
            )

    return records


# SofaScore's per-player keys are camelCase and not always guessable, so
# rename the ones worth showing and leave the rest alone. Anything not listed
# still gets collected, just with a tidied-up version of its own key.
PLAYER_STAT_NAMES = {
    "totalShots": "Shots",
    "onTargetScoringAttempt": "Shots on target",
    "totalTackle": "Tackles",
    "totalPass": "Passes",
    "accuratePass": "Accurate passes",
    "keyPass": "Key passes",
    "duelWon": "Duels won",
    "duelLost": "Duels lost",
    "aerialWon": "Aerials won",
    "wasFouled": "Fouled",
    "fouls": "Fouls",
    "totalClearance": "Clearances",
    "interceptionWon": "Interceptions",
    "touches": "Touches",
    "rating": "Rating",
    "minutesPlayed": "Minutes",
    "goals": "Goals",
    "goalAssist": "Assists",
    "expectedGoals": "xG",
    "expectedAssists": "xA",
    "possessionLostCtrl": "Possession lost",
    "totalCross": "Crosses",
    "bigChanceCreated": "Big chances created",
    "bigChanceMissed": "Big chances missed",
    "savedShotsFromInsideTheBox": "Saves inside box",
    "saves": "Saves",
}

# Shown at the top of the stat picker, when present.
PLAYER_STAT_ORDER = [
    "Shots",
    "Shots on target",
    "Tackles",
    "Passes",
    "Key passes",
    "Duels won",
    "Fouls",
    "Fouled",
    "Clearances",
    "Interceptions",
    "Touches",
    "Rating",
    "Minutes",
]


def _pretty(key: str) -> str:
    """camelCase to something readable, for keys not in the lookup."""
    out = ""
    for i, char in enumerate(key):
        if char.isupper() and i:
            out += " " + char.lower()
        else:
            out += char
    return out[:1].upper() + out[1:]


def player_form(
    team_id: int,
    team_name: str,
    tournament_id: int | None = None,
    limit: int = 10,
    verbose: bool = True,
) -> list[dict]:
    """One record per player per match, for a team's recent matches.

    Note the shape difference from team_form: this is flat, one row per
    player per game, rather than one row per game. Grouping happens later,
    which keeps the venue and last-N filters working the same way.
    """
    events = collect_events(team_id, tournament_id)[-limit:]

    if verbose:
        print(f"  {team_name}: player stats from {len(events)} matches")

    records = []
    for i, event in enumerate(events, start=1):
        event_id = event["id"]
        lineups = api.event_lineups(event_id)
        if not lineups:
            if verbose:
                print(f"    {i}/{len(events)} {event_id} no lineups")
            continue

        is_home = event.get("homeTeam", {}).get("id") == team_id
        side = "home" if is_home else "away"
        opponent = (event.get("awayTeam") if is_home else event.get("homeTeam")) or {}

        players = lineups.get(side, {}).get("players", [])
        kept = 0

        for entry in players:
            raw = entry.get("statistics") or {}
            if not raw:
                # Unused substitute. No stats at all, so not a zero, an absence.
                continue

            values = {}
            for key, value in raw.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                values[PLAYER_STAT_NAMES.get(key, _pretty(key))] = float(value)

            if not values:
                continue

            person = entry.get("player", {})
            records.append(
                {
                    "player": person.get("name", "?"),
                    "player_id": person.get("id"),
                    "position": entry.get("position"),
                    "started": not entry.get("substitute", False),
                    "match_id": event_id,
                    "date": _match_date(event),
                    "opponent": opponent.get("shortName") or opponent.get("name", "?"),
                    "venue": side,
                    "minutes": values.get("Minutes", 0),
                    "stats": values,
                }
            )
            kept += 1

        if verbose:
            print(f"    {i}/{len(events)} {event_id} {kept} players")

    return records


def player_stat_names(*record_lists: list[dict]) -> list[str]:
    """Every player stat present, the useful ones first."""
    found = set()
    for records in record_lists:
        for record in records:
            found.update(record["stats"].keys())

    ordered = [name for name in PLAYER_STAT_ORDER if name in found]
    ordered += sorted(found - set(ordered))
    return ordered


def suggest_player_lines(
    record_lists: list[list[dict]], names: list[str]
) -> dict[str, float]:
    """A line per player stat, from the median of everyone who recorded one.

    Zeroes are excluded deliberately. Half a squad never has a shot, and
    including all those zeroes drags every line down to 0.5, which makes
    the hit rates meaningless.
    """
    lines: dict[str, float] = {}

    for name in names:
        values = [
            record["stats"][name]
            for records in record_lists
            for record in records
            if record["stats"].get(name)
        ]
        if not values:
            continue
        median = stats_lib.median(values)
        lines[name] = max(0.5, round(median) - 0.5)

    return lines


def stat_names(*record_lists: list[dict]) -> dict[str, list[str]]:
    """Stats present in each period, as {period: [names]}.

    Periods are kept separate because they don't carry the same stats.
    Possession is reported for a half, red cards effectively aren't.
    """
    per_period: dict[str, set[str]] = {key: set() for key in PERIODS}

    for records in record_lists:
        for record in records:
            for period, bucket in record["stats"].items():
                per_period.setdefault(period, set()).update(bucket.keys())

    out: dict[str, list[str]] = {}
    for period, found in per_period.items():
        found = found - SKIP_STATS
        if not found:
            continue
        ordered = [name for name in PREFERRED_STATS if name in found]
        ordered += sorted(found - set(ordered))
        out[period] = ordered

    return out


def suggest_lines(
    record_lists: list[list[dict]],
    names: dict[str, list[str]],
) -> dict[str, dict[str, float]]:
    """A line per stat per period, from the combined sample of both teams.

    Sharing one line between the two teams is what makes their columns
    directly comparable. Each period gets its own, because a first-half
    shots line has no business being the same as a full-match one.
    """
    lines: dict[str, dict[str, float]] = {}

    for period, period_names in names.items():
        bucket: dict[str, float] = {}
        for name in period_names:
            values = [
                record["stats"][period][name]
                for records in record_lists
                for record in records
                if name in record["stats"].get(period, {})
            ]
            if not values:
                continue
            bucket[name] = max(0.5, round(stats_lib.median(values)) - 0.5)
        if bucket:
            lines[period] = bucket

    return lines


def hit_rate(
    records: list[dict],
    name: str,
    line: float,
    period: str = "ALL",
) -> tuple[int, int]:
    """How many of these matches went over the line, out of those with the stat."""
    values = [
        r["stats"][period][name]
        for r in records
        if name in r["stats"].get(period, {})
    ]
    hits = sum(1 for v in values if v > line)
    return hits, len(values)
