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

# The market definitions live in markets.py, which imports nothing, so the
# report renderer can read them without dragging in the HTTP stack. Re-exported
# here because everything already reaches for them through hitrates.
from markets import (          # noqa: F401
    PREFERRED_STATS,
    SKIP_STATS,
    BETTABLE_STATS,
    BETTABLE_PLAYER_STATS,
)

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


def _is_friendly(event: dict) -> bool:
    name = event.get("tournament", {}).get("name", "").lower()
    slug = event.get("tournament", {}).get("slug", "").lower()
    return "friendly" in name or "friendly" in slug


def collect_events(
    team_id: int,
    tournament_id: int | None = None,
    pages: int = 2,
    min_matches: int = 5,
    team_name: str = "",
    verbose: bool = True,
    before: float | None = None,
) -> list[dict]:
    """Gather a team's finished matches, newest last.

    Filtering by tournament matters more than it looks. Pre-season friendlies
    sit in the same feed with no detailed statistics, so leaving them in
    produces empty rows and a much smaller sample than you think you have.

    But a strict filter breaks badly in three common cases: a promoted or
    relegated team has no history in their new division, and a cup tie has
    almost no history in that cup. Cardiff went up from League One, so
    filtering their form to the Championship returns nothing at all.

    So the filter is preferred, not enforced. If it leaves too little to work
    with, fall back to every competitive match and say so out loud, because a
    sample drawn from a different division is worth knowing about.
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

    finished = [
        e for e in unique
        if e.get("status", {}).get("type") == "finished" and not _is_friendly(e)
    ]

    # The as-of cutoff. Everything at or after this timestamp is invisible.
    #
    # This exists for backtesting and it is the single thing that decides
    # whether a backtest means anything. Predicting a March fixture using
    # matches played in April is not prediction, it is reading the answer,
    # and it produces a model that looks superb and cannot make money. The
    # comparison is strictly less-than so the fixture being predicted is
    # itself excluded.
    if before is not None:
        finished = [e for e in finished if e.get("startTimestamp", 0) < before]

    if tournament_id is None:
        return finished

    in_competition = [
        e for e in finished
        if e.get("tournament", {}).get("uniqueTournament", {}).get("id")
        == tournament_id
    ]

    if len(in_competition) >= min_matches:
        return in_competition

    if verbose:
        label = f"{team_name}: " if team_name else ""
        others = {}
        for e in finished[-10:]:
            name = e.get("tournament", {}).get("name", "?")
            others[name] = others.get(name, 0) + 1
        mix = ", ".join(f"{n} {c}" for c, n in sorted(others.items(), key=lambda x: -x[1]))
        print(
            f"    {label}only {len(in_competition)} match(es) in this competition,"
            f" using all competitive matches instead"
        )
        if mix:
            print(f"      last 10 were: {mix}")

    return finished


def team_form(
    team_id: int,
    team_name: str,
    tournament_id: int | None = None,
    limit: int = 10,
    verbose: bool = True,
    before: float | None = None,
) -> list[dict]:
    """Build one record per match for a team, newest last.

    Each record holds the team's own value for every stat, plus who they
    played, where, and the score.
    """
    events = collect_events(
        team_id, tournament_id, team_name=team_name, verbose=verbose, before=before
    )[-limit:]

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
        opp_index = 1 - own_index

        records.append(
            {
                "id": event_id,
                "date": _match_date(event),
                "competition": event.get("tournament", {}).get("name", "?"),
                "opponent": opponent.get("shortName") or opponent.get("name", "?"),
                "opponent_id": opponent.get("id"),
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
                # And what the opposition managed against them.
                "against": {
                    period: {
                        name: values[opp_index] for name, values in bucket.items()
                    }
                    for period, bucket in match_stats.items()
                },
            }
        )

        # Goals are not in the statistics feed at all: they live on the
        # scoreline. Bolted on here so "Goals" behaves like every other stat,
        # which is what makes over 1.5 team goals, and the whole for-versus-
        # against matchup, work without a special case everywhere downstream.
        # Full match only, because the half-time score is a separate call.
        records[-1]["stats"].setdefault("ALL", {})["Goals"] = float(goals_for)
        records[-1]["against"].setdefault("ALL", {})["Goals"] = float(goals_against)

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

# Stats where a missing key means the player recorded none of it, not that the
# figure is unavailable. Only counting stats belong here: a missing "Rating" or
# "Minutes" really is absent data, and filling those with zero would be a lie.
#
# This list is the whole fix for the doubling described in player_form(). It has
# to be a module-level constant rather than a literal inside the loop because
# report.py needs the same set at render time, and the two drifting apart is
# what would let the bug back in.
PLAYER_ZERO_FILL = frozenset({
    "Shots",
    "Shots on target",
    "Goals",
    "Assists",
    "Tackles",
    "Fouls",
    "Fouled",
    "Saves",
})

# Shown at the top of the stat picker, when present.
PLAYER_STAT_ORDER = [
    "Shots",
    "Shots on target",
    "Goals",
    "Assists",
    "Tackles",
    "Fouls",
    "Fouled",
    "Passes",
    "Saves",
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
    current_squad_only: bool = True,
    before: float | None = None,
) -> list[dict]:
    """One record per player per match, for a team's recent matches.

    Note the shape difference from team_form: this is flat, one row per
    player per game, rather than one row per game. Grouping happens later,
    which keeps the venue and last-N filters working the same way.
    """
    events = collect_events(
        team_id, tournament_id, team_name=team_name, verbose=verbose, before=before
    )[-limit:]

    if verbose:
        print(f"  {team_name}: player stats from {len(events)} matches")

    # A "last 10" sample straddles the transfer window, so it contains
    # players who have since left. Their numbers are real but useless: a
    # departed striker's shot record tells you nothing about Saturday.
    squad: set[int] | None = None
    if current_squad_only:
        squad = api.squad_player_ids(team_id)
        if not squad:
            squad = None
            if verbose:
                print("    couldn't read the squad, keeping everyone who played")

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
        departed = 0

        for entry in players:
            raw = entry.get("statistics") or {}
            if not raw:
                # Unused substitute. No stats at all, so not a zero, an absence.
                continue

            person_id = entry.get("player", {}).get("id")
            if squad is not None and person_id not in squad:
                departed += 1
                continue

            values = {}
            for key, value in raw.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                values[PLAYER_STAT_NAMES.get(key, _pretty(key))] = float(value)

            if not values:
                continue

            # A missing stat means zero, not "no data".
            #
            # SofaScore leaves the key out entirely when a player records none
            # of something. Adrien Truffert's shots on target came back as
            # 1, -, 1, 1, -, 2, -, - across eight matches. Reading the gaps as
            # unknown and averaging only the four that were there gave 1.25 a
            # game when the truth is 0.62, and every shots-on-target and
            # tackles price in the tool was built on roughly double the real
            # number. Shots escaped it because zeros are recorded there.
            #
            # He played, so whatever he did not do, he did none of.
            for name in PLAYER_ZERO_FILL:
                values.setdefault(name, 0.0)

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
            note = f", {departed} since left" if departed else ""
            print(f"    {i}/{len(events)} {event_id} {kept} players{note}")

    if squad is not None and verbose:
        seen = {r["player_id"] for r in records}
        new_signings = squad - seen
        if new_signings:
            print(
                f"    {len(new_signings)} squad member(s) have no minutes in this"
                " sample (new signings or unused)"
            )

    return records


def player_stat_names(
    *record_lists: list[dict], bettable_only: bool = True
) -> list[str]:
    """Every player stat present, the useful ones first."""
    found = set()
    for records in record_lists:
        for record in records:
            found.update(record["stats"].keys())

    if bettable_only:
        found = found & BETTABLE_PLAYER_STATS

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


def _record_from_event(
    event: dict,
    team_id: int,
    match_stats: dict[str, dict[str, tuple[float, float]]],
) -> dict:
    """One team's view of one match. Shared by form and head to head."""
    is_home = event.get("homeTeam", {}).get("id") == team_id
    opponent = (event.get("awayTeam") if is_home else event.get("homeTeam")) or {}

    home_score = event.get("homeScore", {}).get("current", 0)
    away_score = event.get("awayScore", {}).get("current", 0)
    goals_for, goals_against = (
        (home_score, away_score) if is_home else (away_score, home_score)
    )

    own_index = 0 if is_home else 1
    opp_index = 1 - own_index

    return {
        "id": event["id"],
        "date": _match_date(event),
        "competition": event.get("tournament", {}).get("name", "?"),
        "opponent": opponent.get("shortName") or opponent.get("name", "?"),
        "opponent_id": opponent.get("id"),
        "venue": "home" if is_home else "away",
        "goals_for": goals_for,
        "goals_against": goals_against,
        "result": (
            "W" if goals_for > goals_against
            else "D" if goals_for == goals_against
            else "L"
        ),
        "stats": {
            period: {name: values[own_index] for name, values in bucket.items()}
            for period, bucket in match_stats.items()
        },
        # What the opposition managed against them. Same payload, other index,
        # so "corners against" costs nothing extra to collect.
        "against": {
            period: {name: values[opp_index] for name, values in bucket.items()}
            for period, bucket in match_stats.items()
        },
    }


def head_to_head(
    event_id: int,
    home_id: int,
    away_id: int,
    limit: int = 10,
    verbose: bool = True,
) -> list[list[dict]]:
    """Previous meetings between these two teams, as two record lists.

    Same shape as team_form's output, so the report can render head to head
    with exactly the same code as recent form.

    No competition filter here on purpose: when these two meet in a cup, that
    is still a meeting between them, and the sample is small enough already.
    """
    events = api.h2h_events(event_id)
    events = [e for e in events if e.get("status", {}).get("type") == "finished"]
    events.sort(key=lambda e: e.get("startTimestamp", 0))
    events = events[-limit:]

    if verbose:
        print(f"  head to head: {len(events)} previous meeting(s)")

    home_records, away_records = [], []

    for i, event in enumerate(events, start=1):
        match_stats = extract_match_stats(api.event_statistics(event["id"]))
        if not match_stats:
            if verbose:
                print(f"    {i}/{len(events)} {event['id']} no statistics")
            continue
        home_records.append(_record_from_event(event, home_id, match_stats))
        away_records.append(_record_from_event(event, away_id, match_stats))
        if verbose:
            print(
                f"    {i}/{len(events)} {_match_date(event)}"
                f" {event.get('homeTeam', {}).get('shortName', '?')}"
                f" {event.get('homeScore', {}).get('current', 0)}-"
                f"{event.get('awayScore', {}).get('current', 0)}"
                f" {event.get('awayTeam', {}).get('shortName', '?')}"
            )

    return [home_records, away_records]


def stat_names(
    *record_lists: list[dict], bettable_only: bool = True
) -> dict[str, list[str]]:
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
        if bettable_only:
            found = found & BETTABLE_STATS
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


# ---------------------------------------------------------------- adjustment

# ------------------------------------------------------- standard of opposition
#
# The opponent-adjusted model needs a rating for both sides, and a promoted
# club has none, because everyone it played is in another division. This is
# the way round that: instead of asking "how good are Coventry", ask "what do
# Arsenal do to sides of that standard", and answer it from Arsenal's own
# record, which is well sampled.
#
# Standard is read off last season's final table. This season's is three
# games old in August and says nothing. Clubs from a lower division sit below
# every club from the higher one, which is crude but is the honest default:
# promoted sides are, on average, about as good as the teams that finished
# just above the drop.

TIERS = [
    ("top", "top six"),
    ("upper", "upper mid-table"),
    ("lower", "lower mid-table"),
    ("bottom", "bottom of the table and promoted sides"),
]
TIER_LABELS = dict(TIERS)


def build_tier_map(
    tables: list[list[dict]], top: int = 6, upper: int = 11, lower: int = 17
) -> dict[int, str]:
    """Club id to tier, from one or more final league tables.

    Pass the higher division first. Clubs from later tables are stacked
    underneath it, so a Championship side always ranks below a Premier League
    one. The cut-offs are positions in that stacked ranking, so with the
    defaults the top six are "top", 7 to 11 "upper", 12 to 17 "lower", and
    everything from 18 down, including every promoted club, is "bottom".
    """
    tier_map: dict[int, str] = {}
    offset = 0

    for table in tables:
        if not table:
            continue
        for order, row in enumerate(table, start=1):
            # Position is normally present, but SofaScore leaves it null on
            # some competitions. The row order is never missing, so it is the
            # fallback. Without this a null position crashes the whole build
            # after twenty minutes of fetching, which is the worst possible
            # moment to find out.
            position = row.get("position") or order
            rank = offset + position
            if rank <= top:
                tier = "top"
            elif rank <= upper:
                tier = "upper"
            elif rank <= lower:
                tier = "lower"
            else:
                tier = "bottom"
            # First table wins: a club relegated last season is judged on the
            # division it actually played in, not on where it now sits.
            tier_map.setdefault(row["id"], tier)
        offset += len(table)

    return tier_map


def tier_of(tier_map: dict[int, str], team_id: int | None) -> str:
    """A club with no table entry is treated as promoted, so: bottom.

    Defaulting to "bottom" rather than "unknown" is deliberate. Anyone
    missing from both tables came up from below, and pretending otherwise
    would put them in mid-table by accident.
    """
    return tier_map.get(team_id, "bottom") if team_id is not None else "bottom"


def tier_split(
    records: list[dict],
    tier_map: dict[int, str],
    tier: str,
    period: str = "ALL",
    venue: str | None = None,
) -> dict:
    """What a team did, and had done to it, against one standard of opponent.

    Returns {"for": {stat: mean}, "against": {stat: mean}, "matches": n,
    "opponents": [names]}. Everything is a plain average over the matches
    that qualify, with no modelling on top, because the whole point of this
    route is that it is directly checkable against the match list shown
    beside it.
    """
    rows = [
        r for r in records
        if tier_of(tier_map, r.get("opponent_id")) == tier
        and (venue is None or r.get("venue") == venue)
    ]

    totals_for: dict[str, list[float]] = {}
    totals_against: dict[str, list[float]] = {}

    for r in rows:
        for stat, value in (r.get("stats", {}).get(period) or {}).items():
            totals_for.setdefault(stat, []).append(value)
        for stat, value in (r.get("against", {}).get(period) or {}).items():
            totals_against.setdefault(stat, []).append(value)

    return {
        "for": {k: round(sum(v) / len(v), 2) for k, v in totals_for.items() if v},
        "against": {k: round(sum(v) / len(v), 2) for k, v in totals_against.items() if v},
        "matches": len(rows),
        "opponents": [r.get("opponent", "?") for r in rows],
    }


def tier_projection(
    rated_records: list[dict],
    tier_map: dict[int, str],
    opponent_id: int,
    rated_is_home: bool,
    period: str = "ALL",
    min_matches: int = 5,
) -> dict | None:
    """Project a fixture from the rated side's record against that standard.

    Used when one club cannot be rated at all. Arsenal against bottom-tier
    sides gives both numbers at once: what Arsenal manage becomes Arsenal's
    projection, and what those sides manage against Arsenal becomes the
    promoted club's. No Coventry data is used, which is the point, because
    Coventry's data is the part that does not transfer.

    Venue is honoured where there is enough of it, because Arsenal at home to
    a bottom side is a different match from Arsenal away at one. Below the
    threshold it falls back to both venues and says so.
    """
    venue = "home" if rated_is_home else "away"
    split = tier_split(rated_records, tier_map, "bottom", period, venue=venue)
    used_venue = venue

    if split["matches"] < min_matches:
        split = tier_split(rated_records, tier_map, "bottom", period, venue=None)
        used_venue = None

    if split["matches"] < 3:
        return None

    stats = {}
    for stat in set(split["for"]) | set(split["against"]):
        rated = split["for"].get(stat)
        other = split["against"].get(stat)
        if rated is None or other is None:
            continue
        stats[stat] = [rated, other] if rated_is_home else [other, rated]

    if not stats:
        return None

    return {
        "stats": stats,
        "matches": split["matches"],
        "venue": used_venue,
        "opponents": split["opponents"],
        "tier": "bottom",
    }


# A rating is only meaningful if it was fitted against opponents whose own
# ratings are known. A promoted club's last ten matches were all played in a
# division nobody else here belongs to, so almost every one of them is
# unusable, and what survives is one or two games fitted in a closed loop
# against the only other promoted side. That produced Coventry City rated as
# a better defensive corner side than Arsenal off a single Championship
# match. Below this many usable matches the rating is dropped rather than
# published, and project_fixture then omits the stat entirely.
MIN_RATED_MATCHES = 4

# A projection this far from the league average is a broken fit, not a bold
# call. Real team-level variation in these counts lives well inside 3x, so
# anything outside is the multipliers running away rather than football.
PROJECTION_CEILING = 3.0
PROJECTION_FLOOR = 0.25


def rating_pools(records_by_team: dict[int, list[dict]]) -> list[set[int]]:
    """Split teams into groups that can actually be compared with each other.

    The multiplicative fit only means anything within a set of teams connected
    by shared opponents. Two teams that have never played anyone in common sit
    on separate scales, and nothing in the arithmetic knows that.

    This is not a hypothetical. A Premier League report containing Hull City v
    Manchester United projected Hull to score exactly 0.00 goals. Hull's 38
    matches were 33 Championship, 3 playoffs and 2 FA Cup, with no opponent in
    common with United. Because attack is normalised to mean 1.0 across the
    whole pool, the Championship sides were pushed to the bottom of a scale
    calibrated on Premier League scoring, and Hull landed on the floor of it.
    The model was not measuring that Hull are worse. It was measuring that
    Championship matches contain fewer goals and blaming the teams for it.

    MIN_RATED_MATCHES does not catch this, because the count is fine: Hull had
    38 matches. What is missing is a path through the opponent graph, so that
    is what gets measured here, with a union-find over who has played whom.
    """
    parent = {t: t for t in records_by_team}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for team, records in records_by_team.items():
        for r in records:
            opp = r.get("opponent_id")
            if opp in parent:
                union(team, opp)

    pools: dict[int, set[int]] = {}
    for t in records_by_team:
        pools.setdefault(find(t), set()).add(t)
    return sorted(pools.values(), key=len, reverse=True)


def pool_of(pools: list[set[int]], team_id: int) -> int | None:
    """Which comparable group a team belongs to, or None if it is unknown."""
    for i, pool in enumerate(pools):
        if team_id in pool:
            return i
    return None



def league_ratings(
    records_by_team: dict[int, list[dict]],
    names: dict[str, list[str]],
    min_matches: int = MIN_RATED_MATCHES,
) -> dict:
    """Express every team as a multiplier on the league average.

    This is the standard multiplicative model, and it is what turns a raw
    record into something transferable. A team averaging 12 shots against
    defences that concede 9 is not the same team as one averaging 12 against
    defences that concede 15, but a hit rate cannot tell them apart.

        attack  = the team's own average / league average
        defence = what they concede      / league average
        expected for A against B = league average * A.attack * B.defence

    Home advantage is carried by using separate home and away league averages,
    which is where most of it actually lives.

    Verified against a synthetic league where the true multipliers were known:
    the model recovers them exactly.
    """
    ratings: dict = {"average": {}, "home": {}, "away": {}, "attack": {}, "defence": {}}
    # How many matches each rating was actually fitted from, so the report
    # can say why a projection is missing instead of silently omitting it.
    samples: dict = {t: {p: {} for p in names} for t in records_by_team}

    for period, period_names in names.items():
        avg, home_avg, away_avg = {}, {}, {}

        for stat in period_names:
            all_for, home_for, away_for = [], [], []
            for records in records_by_team.values():
                for r in records:
                    value = r["stats"].get(period, {}).get(stat)
                    if value is None:
                        continue
                    all_for.append(value)
                    (home_for if r["venue"] == "home" else away_for).append(value)

            if not all_for:
                continue
            avg[stat] = sum(all_for) / len(all_for)
            home_avg[stat] = sum(home_for) / len(home_for) if home_for else avg[stat]
            away_avg[stat] = sum(away_for) / len(away_for) if away_for else avg[stat]

        ratings["average"][period] = avg
        ratings["home"][period] = home_avg
        ratings["away"][period] = away_avg

    # Fit iteratively. A single pass divides by the league average and calls
    # it a rating, but that inherits the schedule: a strong side never plays
    # itself, so its opponents are weaker than average and its rating comes
    # out flattered. Re-fitting against the current opponent estimates removes
    # that. On a synthetic league with known multipliers, one pass overshot a
    # projection by 17%; this converges onto the truth.
    ids = list(records_by_team)
    attack = {t: {p: {} for p in names} for t in ids}
    defence = {t: {p: {} for p in names} for t in ids}

    # Teams that share no opponents cannot be put on one scale. Normalising
    # each connected group separately keeps a Championship side's rating
    # relative to the Championship, instead of to a Premier League average it
    # was never measured against.
    pools = rating_pools(records_by_team)
    pool_index = {t: i for i, pool in enumerate(pools) for t in pool}

    for period, period_names in names.items():
        league = ratings["average"].get(period, {})

        for stat in period_names:
            base = league.get(stat)
            if not base:
                continue

            att = {t: 1.0 for t in ids}
            dfn = {t: 1.0 for t in ids}

            def observations(team_id):
                for r in records_by_team[team_id]:
                    opp = r.get("opponent_id")
                    if opp not in att:
                        continue
                    mine = r["stats"].get(period, {}).get(stat)
                    theirs = r.get("against", {}).get(period, {}).get(stat)
                    if mine is None or theirs is None:
                        continue
                    yield opp, mine, theirs

            for _ in range(25):
                new_att, new_def = {}, {}

                for t in ids:
                    a_vals, d_vals = [], []
                    for opp, mine, theirs in observations(t):
                        if dfn[opp] > 0:
                            a_vals.append(mine / (base * dfn[opp]))
                        if att[opp] > 0:
                            d_vals.append(theirs / (base * att[opp]))
                    new_att[t] = sum(a_vals) / len(a_vals) if a_vals else att[t]
                    new_def[t] = sum(d_vals) / len(d_vals) if d_vals else dfn[t]

                # Normalise so the average team sits at 1.0, otherwise attack
                # and defence can drift together and mean nothing.
                #
                # Done per connected pool, not across the whole set. A global
                # mean mixes divisions that have never played each other and
                # silently rescales one against the other; that is what drove
                # Hull City to a projected 0.00 goals against Manchester
                # United. Within a pool the mean is meaningful, because every
                # team in it is joined by a chain of real fixtures.
                for pool in pools:
                    members = [t for t in pool if t in new_att]
                    if not members:
                        continue
                    a_mean = sum(new_att[t] for t in members) / len(members)
                    d_mean = sum(new_def[t] for t in members) / len(members)
                    if a_mean > 0:
                        for t in members:
                            new_att[t] = new_att[t] / a_mean
                    if d_mean > 0:
                        for t in members:
                            new_def[t] = new_def[t] / d_mean

                shift = max(
                    max(abs(new_att[t] - att[t]) for t in ids),
                    max(abs(new_def[t] - dfn[t]) for t in ids),
                )
                att, dfn = new_att, new_def
                if shift < 1e-6:
                    break

            # Count what each rating was actually built from, then drop the
            # ones that rest on too little. A team can appear in the fit and
            # still have almost no usable matches, because every opponent it
            # faced was outside this division.
            for t in ids:
                usable = sum(1 for _ in observations(t))
                samples[t][period][stat] = usable
                if usable >= min_matches:
                    attack[t][period][stat] = att[t]
                    defence[t][period][stat] = dfn[t]

    ratings["attack"] = {str(t): attack[t] for t in ids}
    ratings["defence"] = {str(t): defence[t] for t in ids}
    ratings["samples"] = {str(t): samples[t] for t in ids}
    ratings["minMatches"] = min_matches

    ratings["pools"] = {str(t): pool_index[t] for t in ids}
    ratings["poolSizes"] = [len(pool) for pool in pools]

    ratings["teams"] = len(records_by_team)
    return ratings


def rating_coverage(ratings: dict, team_id: int, period: str = "ALL") -> int:
    """How many usable matches this team's ratings were fitted from.

    Usable means the opponent was also in the fit. A promoted club scores
    near zero here even with ten matches on file, which is exactly the case
    that needs explaining rather than hiding.
    """
    block = ratings.get("samples", {}).get(str(team_id), {}).get(period, {})
    return max(block.values()) if block else 0


def project_fixture(
    ratings: dict,
    home_id: int,
    away_id: int,
    names: dict[str, list[str]],
) -> dict:
    """Expected value of each stat for this specific fixture.

    Returns {period: {stat: [home_expected, away_expected]}}. Missing ratings
    simply drop out rather than falling back to the raw average, because a
    projection built on a guess is worse than no projection.
    """
    out: dict = {}

    # Refuse outright if the two sides were never on the same scale. A rating
    # is a multiplier relative to a pool's own average, so comparing one
    # across pools is a category error, not merely a noisy estimate. Better no
    # projection than a confident wrong one: the report already knows how to
    # fall back to the raw record and say so.
    pools = ratings.get("pools") or {}
    home_pool = pools.get(str(home_id))
    away_pool = pools.get(str(away_id))
    if home_pool is not None and away_pool is not None and home_pool != away_pool:
        return {}

    home_att = ratings.get("attack", {}).get(str(home_id), {})
    away_att = ratings.get("attack", {}).get(str(away_id), {})
    home_def = ratings.get("defence", {}).get(str(home_id), {})
    away_def = ratings.get("defence", {}).get(str(away_id), {})

    for period, period_names in names.items():
        bucket = {}
        home_base = ratings.get("home", {}).get(period, {})
        away_base = ratings.get("away", {}).get(period, {})

        for stat in period_names:
            ha = home_att.get(period, {}).get(stat)
            ad = away_def.get(period, {}).get(stat)
            aa = away_att.get(period, {}).get(stat)
            hd = home_def.get(period, {}).get(stat)

            if None in (ha, ad, aa, hd):
                continue
            if stat not in home_base or stat not in away_base:
                continue

            home_expected = home_base[stat] * ha * ad
            away_expected = away_base[stat] * aa * hd

            # A failed fit does not announce itself; it produces a number.
            # These two checks catch the shapes it produces. An expectation at
            # or below zero is impossible for a count and always means the
            # ratings collapsed. An expectation many times the league average,
            # or a tiny fraction of it, means the multipliers ran away rather
            # than that a team is genuinely that extreme.
            if home_expected <= 0 or away_expected <= 0:
                continue
            base_all = ratings.get("average", {}).get(period, {}).get(stat)
            if base_all and base_all > 0:
                worst = max(home_expected, away_expected) / base_all
                best = min(home_expected, away_expected) / base_all
                if worst > PROJECTION_CEILING or best < PROJECTION_FLOOR:
                    continue

            bucket[stat] = [
                round(home_expected, 2),
                round(away_expected, 2),
            ]

        if bucket:
            out[period] = bucket

    return out
