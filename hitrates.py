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
                # The competition id as well as its name, so a caller can tell which
                # division a club actually plays in. A fixture's own tag describes the
                # round, not the teams, and the two differ whenever a lower-division
                # tie is listed under the senior competition.
                "tournament_id": (event.get("tournament", {})
                                  .get("uniqueTournament", {}).get("id")),
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


def _player_stat_values(raw: dict) -> dict[str, float]:
    """One player's statistics block as {readable name: value}.

    Shared by player_form and previous_club_form, so a player's numbers are
    read identically whichever club they were earned at. Letting the two
    drift apart would be the quiet way to make his imported record
    incomparable with everyone else's.

    A missing stat means zero, not "no data".

    SofaScore leaves the key out entirely when a player records none of
    something. Adrien Truffert's shots on target came back as
    1, -, 1, 1, -, 2, -, - across eight matches. Reading the gaps as
    unknown and averaging only the four that were there gave 1.25 a game
    when the truth is 0.62, and every shots-on-target and tackles price in
    the tool was built on roughly double the real number. Shots escaped it
    because zeros are recorded there.

    He played, so whatever he did not do, he did none of. Which is also why
    the zero-fill only happens when there are values at all: an empty block
    means he did not play, and an empty dict is how this says so.
    """
    values: dict[str, float] = {}
    for key, value in raw.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        values[PLAYER_STAT_NAMES.get(key, _pretty(key))] = float(value)

    if values:
        for name in PLAYER_ZERO_FILL:
            values.setdefault(name, 0.0)

    return values


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

            # The renaming and the zero-fill both live in the shared helper;
            # the reasoning, Truffert included, lives on its docstring.
            values = _player_stat_values(raw)
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


def previous_club_form(
    team_id: int,
    team_name: str,
    current_records: list[dict],
    max_signings: int = 3,
    max_matches: int = 6,
    max_appearances: int = 3,
    max_transfer_age_days: int = 365,
    before: float | None = None,
    verbose: bool = True,
) -> list[dict]:
    """A new signing's record from the club he just left, tagged as such.

    A player who arrived this summer has one or two appearances here, which
    prices nothing, and the report can only mark him "new / thin sample".
    His last half-season exists; it is just filed under another club. This
    pulls it in, in exactly player_form's record shape, with one addition: a
    "former_club" dict naming the club, its id and the competition each
    match was played in, so the front end can say where a number came from
    instead of passing it off as form for this team.

    Scale is the reason for every limit in the signature. Six leagues of
    twenty-odd squads is thousands of players, and fetching match history
    for all of them would add hours to a run that already takes five. So a
    player only qualifies if he already appears in the current sample - the
    report builds its rows from records, so a signing with no minutes yet
    would cost fetches to feed rows nothing displays - with at most
    `max_appearances` of them: in a 38-game sample anyone at the club since
    last season has dozens and walks straight past that bar. The transfer
    must also be recent, because the squad feed's previous-team list
    remembers moves back to 2008, and a veteran's club of a decade ago is
    trivia, not evidence; without this check an early-season 10-game sample
    could mistake a long-serving fringe player for a signing. `max_signings`
    then caps the spend however busy the window was, keeping the worst case
    at max_signings * (1 + max_matches) requests a side - and usually far
    fewer, since a previous club inside the covered leagues has its matches
    in the permanent cache already.

    The previous club itself costs nothing to find: the squad endpoint that
    player_form already fetched carries a playerPreviousTeam list complete
    with transfer dates, so this reads it straight back out of the cache.
    """
    # The raw squad payload, not team_squad(), because that helper keeps
    # only the players list and the transfer history is a sibling key.
    # Same path and max_age as team_squad, so within a run this is the
    # cached copy player_form's squad check just paid for.
    squad_json = api.get_json(f"team/{team_id}/players", max_age_hours=24) or {}

    now = datetime.now(timezone.utc).timestamp()
    window_start = now - max_transfer_age_days * 86400

    # player id -> (previous club, transfer timestamp), recent moves only.
    transfers: dict[int, tuple[dict, float]] = {}
    for item in squad_json.get("playerPreviousTeam") or []:
        person = item.get("player") or {}
        prev = item.get("previousTeam") or {}
        person_id, prev_id = person.get("id"), prev.get("id")
        if not isinstance(person_id, int) or not isinstance(prev_id, int):
            continue
        # A loan return lists the club itself, and a national side is not a
        # club: neither has a record worth importing.
        if prev_id == team_id or prev.get("national"):
            continue
        try:
            moved = datetime.fromisoformat(item.get("transferDate", "")).timestamp()
        except (TypeError, ValueError):
            continue
        # A transfer dated in the future is a pre-agreed move recorded
        # early; he is not "from" that club yet. The week of slack is for
        # feeds that stamp the date at the window rather than the signing.
        if not (window_start <= moved <= now + 7 * 86400):
            continue
        transfers[person_id] = (prev, moved)

    # Who has played, and how much, in the sample as it stands.
    apps: dict[int, int] = {}
    minutes: dict[int, float] = {}
    names: dict[int, str] = {}
    for record in current_records:
        person_id = record.get("player_id")
        if not isinstance(person_id, int):
            continue
        apps[person_id] = apps.get(person_id, 0) + 1
        minutes[person_id] = minutes.get(person_id, 0.0) + (record.get("minutes") or 0)
        names[person_id] = record.get("player", "?")

    candidates = [
        person_id for person_id, count in apps.items()
        if count <= max_appearances and person_id in transfers
    ]
    # Most minutes first: when the cap bites, it should keep the signings
    # who are actually being picked, because those are the ones anyone
    # will try to price.
    candidates.sort(key=lambda person_id: -minutes.get(person_id, 0.0))
    candidates = candidates[:max_signings]

    if verbose and candidates:
        print(f"    {team_name}: previous-club stats for "
              f"{len(candidates)} new signing(s)")

    out: list[dict] = []
    for person_id in candidates:
        prev, moved = transfers[person_id]

        # Strictly before both the transfer and any as-of cutoff. The
        # transfer bound keeps this to matches he was actually there for;
        # `before` keeps a backtest honest, same contract as collect_events.
        cutoff = moved if before is None else min(moved, before)

        events = collect_events(
            prev["id"], tournament_id=None, pages=1,
            verbose=False, before=cutoff,
        )[-max_matches:]

        found = 0
        for event in events:
            lineups = api.event_lineups(event["id"])
            if not lineups:
                continue

            for side in ("home", "away"):
                side_team = event.get(f"{side}Team") or {}
                # Only appearances FOR the previous club count. Their feed
                # can also hold him lining up against them for whichever
                # club he was at before that, and importing his numbers
                # from a third club under this one's name would be exactly
                # the mislabelling this field exists to prevent.
                if side_team.get("id") != prev["id"]:
                    continue
                entry = next(
                    (p for p in (lineups.get(side) or {}).get("players", [])
                     if (p.get("player") or {}).get("id") == person_id),
                    None,
                )
                if entry is None:
                    continue
                values = _player_stat_values(entry.get("statistics") or {})
                if not values:
                    continue

                opponent = (
                    event.get("awayTeam") if side == "home"
                    else event.get("homeTeam")
                ) or {}
                out.append(
                    {
                        "player": names.get(person_id)
                        or (entry.get("player") or {}).get("name", "?"),
                        "player_id": person_id,
                        "position": entry.get("position"),
                        "started": not entry.get("substitute", False),
                        "match_id": event["id"],
                        "date": _match_date(event),
                        "opponent": opponent.get("shortName")
                        or opponent.get("name", "?"),
                        "venue": side,
                        "minutes": values.get("Minutes", 0),
                        "stats": values,
                        # The marker the whole feature hangs off. Absent on
                        # a normal record, so the front end can read "has
                        # former_club" as "earned elsewhere" and label it,
                        # and an older front end that has never heard of the
                        # key keeps ignoring these rows entirely.
                        "former_club": {
                            "name": prev.get("name", "?"),
                            "id": prev["id"],
                            "competition": event.get("tournament", {})
                            .get("name", "?"),
                        },
                    }
                )
                found += 1

        if verbose:
            print(
                f"      {names.get(person_id, person_id)} <- "
                f"{prev.get('name', '?')}: {found} match(es) with stats"
            )

    return out


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
        # The competition id as well as its name, so a caller can tell which
        # division a club actually plays in. A fixture's own tag describes the
        # round, not the teams, and the two differ whenever a lower-division
        # tie is listed under the senior competition.
        "tournament_id": (event.get("tournament", {})
                          .get("uniqueTournament", {}).get("id")),
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


def referee_card_rates(event_details: dict | None) -> dict | None:
    """The referee on one match record, with his card averages, or None.

    SofaScore embeds the referee straight onto the event, running totals and
    all: yellowCards, redCards (straight), yellowRedCards (second yellows)
    and games, the number of matches those totals cover. That makes the card
    rate free - no per-referee endpoint, no extra request beyond the event
    itself.

    None means "no referee named on this record", and callers must keep that
    distinct from a referee with no card history. Appointments are usually
    published only days before kick-off, so for most of the week the honest
    answer is "not known yet", and rendering that as 0.0 cards per game
    would be a lie with decimals on.

    The per-game figures only appear when games > 0, and games itself is
    always carried, because 4.7 yellows a game over 3 matches and over 130
    matches are different claims and the page has to be able to say which
    it is making. redsPerGame counts straight reds and second yellows
    together, which is how every card market counts them.
    """
    if not isinstance(event_details, dict):
        return None
    ref = event_details.get("referee")
    if not isinstance(ref, dict) or not ref.get("name"):
        return None

    def _count(key: str) -> int:
        value = ref.get(key)
        return value if isinstance(value, int) and value >= 0 else 0

    games = _count("games")
    yellows = _count("yellowCards")
    straight_reds = _count("redCards")
    second_yellows = _count("yellowRedCards")

    out = {
        "name": ref["name"],
        "id": ref.get("id") if isinstance(ref.get("id"), int) else None,
        "country": (ref.get("country") or {}).get("name"),
        "games": games,
        "yellows": yellows,
        "straightReds": straight_reds,
        "secondYellows": second_yellows,
    }
    if games > 0:
        out["yellowsPerGame"] = round(yellows / games, 2)
        out["redsPerGame"] = round((straight_reds + second_yellows) / games, 2)
    return out


def api_meetings(
    home_id: int,
    away_id: int,
    before: float | None = None,
) -> list[dict]:
    """Matches between these two clubs, from the home side's own feed.

    Returns raw events rather than records, so head_to_head keeps ownership of
    the filtering and the as-of guard that follows it.
    """
    both = {away_id}
    found = []
    for event in collect_events(home_id, tournament_id=None, verbose=False,
                                before=before):
        sides = {
            (event.get("homeTeam") or {}).get("id"),
            (event.get("awayTeam") or {}).get("id"),
        }
        if sides & both:
            found.append(event)
    return found


def head_to_head(
    event_id: int,
    home_id: int,
    away_id: int,
    limit: int = 10,
    verbose: bool = True,
    before: float | None = None,
) -> list[list[dict]]:
    """Previous meetings between these two teams, as two record lists.

    Same shape as team_form's output, so the report can render head to head
    with exactly the same code as recent form.

    No competition filter here on purpose: when these two meet in a cup, that
    is still a meeting between them, and the sample is small enough already.

    `before` is the as-of cutoff, same contract as collect_events: a unix
    timestamp, compared strictly less-than, None meaning no explicit cutoff.
    The live path passes the fixture's own kickoff; a backtest would pass
    the moment it is pretending to stand at.
    """
    # Derived from the two clubs' own match feeds, not from a head-to-head
    # endpoint.
    #
    # SofaScore's event/{id}/h2h/events is gone. It returned 404 for all 87
    # fixtures of the 1 September run, which is why the Head to head button
    # stayed disabled for days while the flag, the config and the payload
    # were all correct: the code ran, asked, and was told no.
    #
    # Intersecting the home side's history with the away side's id needs no
    # request at all beyond the feeds team_form already fetches, so this is
    # both cheaper and immune to that endpoint disappearing again. The limit
    # is honest rather than hidden: it can only see meetings inside the
    # window already pulled for form, so two clubs who last met three seasons
    # ago will show nothing rather than something stale.
    events = [
        e for e in api_meetings(home_id, away_id, before=before)
    ]

    # Guard against reading the future. This feed is "meetings between these
    # two clubs", not "meetings before this one", and the difference only
    # bites where it can do the most damage. Built for an upcoming fixture,
    # every meeting is already in the past and the guard changes nothing.
    # Built against a cache refreshed after the fact - which is what a
    # backtest does - the feed contains the very fixture being predicted,
    # and later in the season its reverse fixture too. A head-to-head sample
    # holding the match's own result is not evidence, it is the answer
    # sheet, and it reports an extraordinary record that means nothing.
    #
    # The default is safe rather than convenient, because the caller most
    # likely to forget `before` is a future backtest, the one caller that
    # cannot afford it. So even when no cutoff is passed, the fixture's own
    # kickoff caps the sample whenever the fixture appears in its own feed
    # carrying a timestamp - in the poisoned-cache case it always does,
    # because that is precisely what being poisoned means. And the fixture
    # itself is dropped by id regardless, since that one needs no timestamp
    # to be wrong.
    cutoff = before
    for e in events:
        if e.get("id") == event_id and e.get("startTimestamp"):
            own = e["startTimestamp"]
            cutoff = own if cutoff is None else min(cutoff, own)
            break
    events = [e for e in events if e.get("id") != event_id]
    if cutoff is not None:
        dated = [e for e in events if e.get("startTimestamp", 0) < cutoff]
        if verbose and len(dated) < len(events):
            print(
                f"  head to head: dropped {len(events) - len(dated)} "
                f"meeting(s) at or after the cutoff"
            )
        events = dated

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

# How many shared opponents two teams need before their ratings may be
# compared. Within a division every pair clears this comfortably: the Premier
# League fixtures checked all shared 18. A cross-division pairing joined only
# by a cup tie scores 0 or 1, which is the case this exists to reject.
MIN_POOL_LINKS = 2

# Set deliberately low while this is being tuned. The pool test is transitive:
# two teams can land in one pool through a chain of other clubs, so the bar
# each *pair* clears is not the bar the pool clears. On real data that made the
# outcome incoherent -- a Championship pair sharing one opponent kept all 11
# projections while another sharing two got none, and Malaga v Deportivo, with
# 22 shared opponents, was rejected outright.
#
# So the pair check below is the one that actually decides a fixture, and this
# constant only governs how the pools are grown. Two is loose on purpose: it
# rejects the pure cup-tie bridge that caused the Hull City bug and little
# else, which is the right trade while the honest tuning is still outstanding.
# See MIN_PAIR_LINKS for the guard that does the real work.

# Shared opponents required between the two sides of a fixture before their
# projection is trusted. Measured directly on the pair, so it means the same
# thing for every fixture, unlike the transitive pool test.
#
# An earlier version required four, on the claim that healthy league pairings
# share 18 to 22 opponents. They cannot: the opponent sets are built from each
# side's last ten matches or so, so the overlap tops out around eleven, and a
# healthy mid-season pair actually sits at 3 to 8. That figure must have been
# counted on something other than the sets this guard sees, and the cost of
# believing it was real: at four, a quarter of Premier League backtest bets
# lost their projection and fell back to raw-record pricing.
#
# Two is the backtested number. On the corrected Premier League replay it
# lifts model coverage from 75% to 91% of settled bets, and the bets it
# recovers price far better under the model (said 74.7%, landed 67.7%) than
# under the raw record they otherwise get (said 83.0% for the same 67.7%).
# The case this guard exists for is untouched: a cross-division pair joined
# only by a cup tie shares 0 or 1 opponents and is still rejected.
MIN_PAIR_LINKS = 2


def rating_pools(records_by_team: dict[int, list[dict]],
                 min_links: int = MIN_POOL_LINKS) -> list[set[int]]:
    """Split teams into groups that can actually be compared with each other.

    The multiplicative fit only means anything within a set of teams measured
    against a common standard. Two teams whose matches never overlap sit on
    separate scales, and nothing in the arithmetic knows that.

    The first version of this asked only whether *a* path existed between two
    teams, using a plain union-find. That was too weak, and it let the exact
    bug it was written for straight through. Ratings are fitted from all 20
    clubs in the division, and each club's record covers every competition it
    played, cup ties included. One FA Cup tie is a path. So Hull City, whose
    league season was entirely in the Championship, was joined to the Premier
    League component through a single cup match and waved through as
    comparable. It projected Ipswich for 6.41 corners against Sunderland's
    3.33 off zero shared opponents, and put Manchester United *below* Hull.

    Existing and being measurable are different things. A single shared
    fixture is a path but it is nowhere near enough to calibrate one division
    against another, so what matters is the *weight* of the connection: two
    teams belong in one pool only if they are joined by at least `min_links`
    distinct shared opponents, directly or through other teams that clear the
    same bar. Edges thinner than that are treated as coincidence, which for a
    cup tie between divisions is exactly what they are.
    """
    ids = list(records_by_team)
    opponents = {
        t: {r.get("opponent_id") for r in records_by_team[t]
            if r.get("opponent_id") is not None}
        for t in ids
    }

    parent = {t: t for t in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Only join two teams when the overlap in who they have played is thick
    # enough to calibrate one against the other. Counting a direct meeting as
    # one link on top of the shared opponents, since playing each other is
    # itself evidence, just not much of it on its own.
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            links = len(opponents[a] & opponents[b])
            if b in opponents[a] or a in opponents[b]:
                links += 1
            if links >= min_links:
                union(a, b)

    pools: dict[int, set[int]] = {}
    for t in ids:
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

    # Who each team has actually played, so a fixture can be judged on the two
    # sides in front of it rather than on the pool they were swept into.
    ratings["opponents"] = {
        str(t): sorted({r.get("opponent_id") for r in records_by_team[t]
                        if r.get("opponent_id") is not None})
        for t in ids
    }
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

    # Refuse if these two sides were never measured against a common standard.
    # A rating is a multiplier relative to an average, so comparing two that
    # were calibrated on different sets of opponents is a category error, not
    # merely a noisy estimate. Better no projection than a confident wrong
    # one: the report already falls back to the raw record and says so.
    #
    # Judged on the pair directly rather than on pool membership. The pool test
    # is transitive, so two teams can share a pool through a chain of other
    # clubs, which made the outcome incoherent on real data: one Championship
    # pair sharing a single opponent kept every projection while another
    # sharing two lost all of them. Counting the opponents these two actually
    # have in common means the same thing for every fixture.
    opponents = ratings.get("opponents") or {}
    mine = set(opponents.get(str(home_id)) or [])
    theirs = set(opponents.get(str(away_id)) or [])
    if mine and theirs:
        links = len(mine & theirs)
        # Having played each other counts, but only for one: it is evidence,
        # and a single cup tie is not much of it.
        if away_id in mine or home_id in theirs:
            links += 1
        if links < MIN_PAIR_LINKS:
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
