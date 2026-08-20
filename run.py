"""
Build a fixture hit-rate report.

    python run.py --demo                        synthetic data, no network
    python run.py --search espanyol             find a team's id
    python run.py --team 2814                   list that team's next fixtures
    python run.py --team 2814 --pick 0          build the report
    python run.py --team 2814 --pick 0,1,2      three fixtures in one report
    python run.py --teams 2814,2833,2817        each team's next fixture
    python run.py --league premier_league       the whole next round
    python run.py --leagues premier_league,championship,la_liga

Add --players for per-player stats, --h2h for previous meetings,
--adjust for opponent-adjusted projections.

One report can hold several fixtures with a dropdown to switch between them.
Teams in the same league share matches, and everything is cached, so the
second and third fixtures cost far less than the first.
"""

from __future__ import annotations

import argparse
import random
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import clubcolour
import hitrates
import report
import sofascore_api as api

OUT_DIR = Path(__file__).parent / "reports"


def describe(event: dict) -> str:
    tournament = event.get("tournament", {}).get("name", "?")
    when = ""
    if event.get("startTimestamp"):
        when = datetime.fromtimestamp(
            event["startTimestamp"], tz=timezone.utc
        ).strftime("%a %d %b %H:%M")
    # The event id is shown because track.py needs it, and hunting for it
    # in a URL is a silly thing to make someone do.
    return (
        f"{when:>16}  {event['homeTeam']['name']} v {event['awayTeam']['name']}"
        f"  ({tournament})\n"
        f"{'':>18}event {event['id']}   "
        f"home {event['homeTeam']['id']}   away {event['awayTeam']['id']}"
    )


def do_search(query: str) -> None:
    teams = api.search_teams(query)
    if not teams:
        print(
            f"\nNothing found for '{query}'.\n\n"
            "The search endpoint may have moved too. You can always read a team id\n"
            "straight off their SofaScore URL: the number at the end of\n"
            "sofascore.com/team/football/espanyol/2814 is the id.\n"
        )
        return

    print(f"\n{len(teams)} team(s):\n")
    for team in sorted(teams, key=lambda t: t["name"]):
        country = team.get("country", {}).get("name", "")
        print(f"  {team['id']:>8}  {team['name']}  ({country})")
    print("\nRe-run with --team ID.\n")


def resolve_names(text: str) -> list[int]:
    """Club names to team ids, one search request each.

    Exists because the fixtures-by-date endpoint is dead, so everything has to
    start from a team, and hunting twelve ids by hand before a kick-off is not
    a thing anyone will do. Ambiguity is resolved towards an exact name match
    first, then the shortest name, because searching "Basel" should give you
    Basel rather than Basel Under 19.
    """
    ids: list[int] = []
    for raw in text.split(","):
        name = raw.strip()
        if not name:
            continue

        teams = api.search_teams(name)
        if not teams:
            print(f"  no team found for '{name}'")
            continue

        exact = [t for t in teams if t["name"].lower() == name.lower()]
        pool = exact or teams
        pick = min(pool, key=lambda t: len(t["name"]))

        country = pick.get("country", {}).get("name", "")
        note = "" if len(teams) == 1 else f"  (from {len(teams)} matches)"
        print(f"  {name:<22} -> {pick['name']} {country and f'({country})'} "
              f"id {pick['id']}{note}")
        ids.append(pick["id"])

    return ids


def list_fixtures(events: list[dict], team_name: str) -> None:
    if not events:
        print(f"\nNo upcoming fixtures found for {team_name}.")
        return
    print(f"\nNext fixtures for {team_name}:\n")
    for i, event in enumerate(events):
        print(f"  [{i}] {describe(event)}")
    print("\nRe-run with --pick N to build a report.")
    print("Log a pick with:  python track.py add --event ID --team TEAM_ID ...\n")


def team_next_fixture(team_id: int, tournament_id: int | None = None) -> dict | None:
    """That team's next match, preferring one in the given competition.

    Without the competition filter this returns whatever they play next,
    which in August is often a European qualifier rather than a league game.
    That matters twice over: you get the wrong fixture, and because the
    fixture's competition drives the history filter, you also get both
    teams' form in that competition only, which is a handful of matches.
    """
    upcoming = api.team_next_events(team_id)

    if tournament_id is not None:
        in_competition = [
            e for e in upcoming
            if e.get("tournament", {}).get("uniqueTournament", {}).get("id")
            == tournament_id
        ]
        if in_competition:
            return in_competition[0]
        # Nothing scheduled in that competition. Say so rather than silently
        # substituting a cup tie.
        if upcoming:
            other = upcoming[0].get("tournament", {}).get("name", "?")
            print(
                f"    team {team_id}: no upcoming fixture in this competition,"
                f" next is {other}. Skipped."
            )
        return None

    if upcoming:
        return upcoming[0]

    near = api.team_near_events(team_id)
    return near.get("nextEvent") or near.get("previousEvent")


_RATINGS_CACHE: dict = {}


def league_ratings_for(tournament_id: int | None, games: int) -> tuple[dict, dict] | None:
    """Fit attack and defence ratings for a whole competition.

    Expensive the first time (every club's recent form) and free afterwards,
    because the cache means a league round reuses matches it was fetching
    anyway. Without ratings for the rest of the division there is nothing to
    measure a team against, which is the whole point of the exercise.
    """
    if tournament_id is None:
        return None
    if tournament_id in _RATINGS_CACHE:
        return _RATINGS_CACHE[tournament_id]

    ids = api.tournament_team_ids(tournament_id)
    if len(ids) < 4:
        print("  not enough teams in the table to fit ratings, skipping adjustment")
        _RATINGS_CACHE[tournament_id] = None
        return None

    print(f"  fitting ratings from {len(ids)} teams (first run is slow, then cached)")
    by_team = {}
    for i, team_id in enumerate(ids, start=1):
        recs = hitrates.team_form(
            team_id=team_id, team_name=f"team {team_id}",
            tournament_id=tournament_id, limit=games, verbose=False,
        )
        if recs:
            by_team[team_id] = recs
        print(f"    {i}/{len(ids)} teams", end="\r")

    if len(by_team) < 4:
        _RATINGS_CACHE[tournament_id] = None
        return None

    names = hitrates.stat_names(*by_team.values())
    ratings = hitrates.league_ratings(by_team, names)
    print(f"    fitted from {len(by_team)} teams              ")

    _RATINGS_CACHE[tournament_id] = (ratings, names)
    return _RATINGS_CACHE[tournament_id]


def team_colour(team_id: int) -> str | None:
    """A club's kit colour, or None if the club has no usable one.

    One cheap request per club, cached for a week. Kit colours change once a
    season at most.

    Primary, then secondary, then text, taking the first with an actual hue.
    SofaScore's primary is the shirt's dominant colour, and for Spurs, Leeds,
    Brentford, Sunderland and Fulham that is white, which is no use as a chart
    colour. Their secondary is the colour you would name if asked.
    """
    data = api.get_json(f"team/{team_id}", max_age_hours=168, verbose=False) or {}
    colours = (data.get("team") or data).get("teamColors") or {}
    valid = [c for c in (colours.get("primary"), colours.get("secondary"),
                         colours.get("text"))
             if isinstance(c, str) and c.startswith("#")]
    return clubcolour.best_of(*valid)


def fixture_colours(home_id: int, away_id: int) -> dict:
    """Chart colours for both clubs, in both modes.

    Kit colours cannot be used raw: half of them fail contrast against one
    background or the other, and a third of derbies are red against red. So
    each is moved into a legible band and the pair is checked for separation,
    including under red-green colour blindness. See clubcolour.py.
    """
    home_kit = team_colour(home_id)
    away_kit = team_colour(away_id)

    light = clubcolour.pair_for(home_kit, away_kit, "light")
    dark = clubcolour.pair_for(home_kit, away_kit, "dark")

    return {
        "light": list(light),
        "dark": list(dark),
        "kits": [home_kit, away_kit],
    }


_TIER_CACHE: dict = {}

# Which division sits directly below each one. Used to stack last season's
# tables so a promoted club ranks below every club in the division above.
DIVISION_BELOW = {
    17: 18,     # Premier League -> Championship
}


def tier_map_for(tournament_id: int | None) -> dict:
    """Club to standard of opposition, from last season's final tables.

    Last season, not this one: in August the current table is three games
    old and would put whoever won on the opening weekend in the top six.
    """
    if tournament_id is None:
        return {}
    if tournament_id in _TIER_CACHE:
        return _TIER_CACHE[tournament_id]

    tables = []
    for tid in (tournament_id, DIVISION_BELOW.get(tournament_id)):
        if tid is None:
            continue
        season = api.previous_season_id(tid)
        if season is None:
            continue
        table = api.tournament_table(tid, season)
        if table:
            tables.append(table)
            print(f"  read last season's table: {len(table)} clubs")

    tier_map = hitrates.build_tier_map(tables)
    if not tier_map:
        print("  couldn't read last season's tables, skipping the tier view")
    _TIER_CACHE[tournament_id] = tier_map
    return tier_map


def build_fixture(
    event: dict, games: int, players: bool, h2h: bool = False,
    adjust: bool = False, all_stats: bool = False, tiers: bool = False,
) -> dict | None:
    """Gather everything the report needs for one fixture."""
    home = event["homeTeam"]
    away = event["awayTeam"]
    tournament = event.get("tournament", {})
    unique_id = tournament.get("uniqueTournament", {}).get("id")

    print(f"\n{home['name']} v {away['name']}  ({tournament.get('name', '?')})")
    if unique_id is None:
        print("  no competition id on this fixture, using all finished matches")

    records = [
        hitrates.team_form(
            team_id=team["id"],
            team_name=team["name"],
            tournament_id=unique_id,
            limit=games,
        )
        for team in (home, away)
    ]

    if not any(records):
        print("  no statistics for either team, skipping this fixture")
        return None

    names = hitrates.stat_names(*records, bettable_only=not all_stats)
    lines = hitrates.suggest_lines(records, names)

    kickoff = ""
    if event.get("startTimestamp"):
        kickoff = datetime.fromtimestamp(
            event["startTimestamp"], tz=timezone.utc
        ).strftime("%A %d %B %Y, %H:%M UTC")

    entry = {
        "fixture": {
            "id": event["id"],
            "home": home["name"],
            "away": away["name"],
            "competition": tournament.get("name", "Football"),
            "date": kickoff,
            "kickoff": event.get("startTimestamp", 0),
            "tournamentId": unique_id,
        },
        "teams": [
            {"name": home["name"], "side": "home"},
            {"name": away["name"], "side": "away"},
        ],
        # Two chart colours derived from the clubs' actual kits. Worked out
        # here rather than in the browser because it needs the kit colours
        # from the API, and because the result is fixed for the fixture.
        "colours": fixture_colours(home["id"], away["id"]),
        "records": records,
        "stats": names,
        "lines": lines,
    }

    if adjust:
        fitted = league_ratings_for(unique_id, games)
        if fitted:
            ratings, league_names = fitted
            projection = hitrates.project_fixture(
                ratings, home["id"], away["id"], league_names
            )
            if projection:
                entry["projection"] = projection
                entry["ratingTeams"] = ratings.get("teams", 0)

            # A projection is only as good as the matches behind it. A
            # promoted club's recent form was played against opponents who
            # are not in this division, so almost none of it can be used, and
            # saying so beats printing a confident wrong number.
            floor = ratings.get("minMatches", 0)
            thin = []
            for team in (home, away):
                usable = hitrates.rating_coverage(ratings, team["id"])
                if usable < floor:
                    thin.append(
                        f"{team['name']}: only {usable} of their recent matches "
                        f"were against a team in this division, so no "
                        f"opponent-adjusted projection is shown for them"
                    )
                    print(f"  {thin[-1]}")
            if thin:
                entry["ratingNotes"] = thin

    # The standard-of-opposition view. It answers the question the ratings
    # cannot when one side is promoted: not "how good is Coventry", which
    # nothing here can know, but "what do Arsenal do to sides of that
    # standard", which their own record answers directly.
    if tiers:
        tier_map = tier_map_for(unique_id)
        if tier_map:
            entry["tiers"] = {
                "map": {str(k): v for k, v in tier_map.items()},
                "labels": hitrates.TIER_LABELS,
                "of": [
                    hitrates.tier_of(tier_map, home["id"]),
                    hitrates.tier_of(tier_map, away["id"]),
                ],
            }

            # If the fitted model gave up on one side, fall back to the
            # other side's record against that standard, and mark it so the
            # report can say where the number came from.
            if "projection" not in entry or entry.get("ratingNotes"):
                home_rated = hitrates.tier_of(tier_map, away["id"]) == "bottom"
                rated_index = 0 if home_rated else 1
                fallback = hitrates.tier_projection(
                    rated_records=records[rated_index],
                    tier_map=tier_map,
                    opponent_id=(away if home_rated else home)["id"],
                    rated_is_home=home_rated,
                )
                if fallback:
                    entry["tierProjection"] = fallback
                    entry["tierProjectionFrom"] = (home if home_rated else away)["name"]
                    print(
                        f"  tier projection from {entry['tierProjectionFrom']}'s "
                        f"record against bottom-tier sides "
                        f"({fallback['matches']} matches)"
                    )

    if h2h:
        h2h_records = hitrates.head_to_head(
            event_id=event["id"], home_id=home["id"], away_id=away["id"], limit=games
        )
        if any(h2h_records):
            entry["h2h"] = h2h_records
            # H2H needs its own lines: two teams meeting each other produce
            # different numbers from their form against everyone else.
            h2h_names = hitrates.stat_names(*h2h_records, bettable_only=not all_stats)
            entry["h2hStats"] = h2h_names
            entry["h2hLines"] = hitrates.suggest_lines(h2h_records, h2h_names)
        else:
            print("  no head to head data, skipping that view")

    if players:
        print("  player stats:")
        player_records = [
            hitrates.player_form(
                team_id=team["id"],
                team_name=team["name"],
                tournament_id=unique_id,
                limit=games,
            )
            for team in (home, away)
        ]
        entry["players"] = player_records
        entry["playerStats"] = hitrates.player_stat_names(
            *player_records, bettable_only=not all_stats
        )
        entry["playerLines"] = hitrates.suggest_player_lines(
            player_records, entry["playerStats"]
        )

    print_summary(entry)
    return entry


def build(
    events: list[dict], games: int, open_browser: bool,
    players: bool, h2h: bool = False, adjust: bool = False,
    all_stats: bool = False, tiers: bool = False,
) -> Path:
    fixtures = []
    for i, event in enumerate(events, start=1):
        print(f"\n[{i}/{len(events)}]", end="")
        entry = build_fixture(event, games, players, h2h, adjust, all_stats, tiers)
        if entry:
            fixtures.append(entry)

    if not fixtures:
        raise SystemExit(
            "\nNo fixture produced any data.\n"
            "Try --games 20, or check the competition filter if these are cup ties."
        )

    payload = {"fixtures": fixtures, "periods": hitrates.PERIODS}

    OUT_DIR.mkdir(exist_ok=True)
    first = fixtures[0]["fixture"]
    comps = {f["fixture"]["competition"] for f in fixtures}

    if len(fixtures) == 1:
        slug = f"{first['home']}-v-{first['away']}"
    elif len(comps) == 1:
        # A whole division's round. Name it after the competition so each
        # league keeps its own file instead of overwriting the last one.
        slug = f"{first['competition']}-{len(fixtures)}-fixtures"
    else:
        slug = f"{len(fixtures)}-fixtures-{first['home']}"
    slug = "".join(c for c in slug.lower().replace(" ", "-") if c.isalnum() or c == "-")

    path = OUT_DIR / f"{slug}.html"
    report.write_report(payload, path)

    print(f"\n\n{len(fixtures)} fixture(s) written to {path}")
    print(api.cache_summary())

    if open_browser:
        webbrowser.open(path.resolve().as_uri())

    return path


def print_summary(entry: dict, period: str = "ALL") -> None:
    """A readable version in the terminal, so the HTML is optional.

    Only the full match is printed here. The halves are in the report, where
    there's room for them.
    """
    names = [t["name"] for t in entry["teams"]]
    stats = entry["stats"].get(period, [])
    lines = entry["lines"].get(period, {})
    if not stats:
        return

    width = max((len(s) for s in stats), default=10)

    print(f"\n  {'stat':<{width}}  {'line':>6}  {names[0][:16]:>16}  {names[1][:16]:>16}")
    print("  " + "-" * (width + 46))

    for stat in stats:
        line = lines.get(stat)
        if line is None:
            continue
        cells = []
        for records in entry["records"]:
            hits, total = hitrates.hit_rate(records, stat, line, period)
            cells.append(f"{hits}/{total}" if total else "no data")
        print(f"  {stat:<{width}}  {line:>6}  {cells[0]:>16}  {cells[1]:>16}")


def demo() -> Path:
    """Synthetic data, so the report can be checked without network access."""
    rng = random.Random(7)
    team_stats = [
        ("Goals", 2, 1),
        ("Total shots", 12, 4),
        ("Shots on target", 4, 2),
        ("Corner kicks", 5, 2),
        ("Offsides", 2, 1),
        ("Fouls", 12, 3),
        ("Yellow cards", 2, 1),
        ("Throw-ins", 20, 5),
    ]
    opponents = ["Betis", "Barca", "Rayo", "Levante", "Madrid",
                 "Sevilla", "Athletic", "Osasuna", "Sociedad", "Getafe"]
    positions = ["G", "D", "D", "D", "M", "M", "F", "F", "M", "M"]

    def make_matches(strength: float, competition: str = "LaLiga (demo data)") -> list[dict]:
        matches = []
        for i in range(10):
            full = {
                name: max(0, round(rng.gauss(mean * strength, spread)))
                for name, mean, spread in team_stats
            }
            # Split each total across the halves, second half a shade busier,
            # which is roughly how real matches behave.
            first = {k: round(v * rng.uniform(0.35, 0.55)) for k, v in full.items()}
            second = {k: v - first[k] for k, v in full.items()}

            # What the opposition managed. Independent of `full` on purpose,
            # so the For and Against views are visibly different in the demo.
            opp = {
                name: max(0, round(rng.gauss(mean * (2 - strength), spread)))
                for name, mean, spread in team_stats
            }
            opp_first = {k: round(v * rng.uniform(0.35, 0.55)) for k, v in opp.items()}
            opp_second = {k: v - opp_first[k] for k, v in opp.items()}
            matches.append({
                "id": rng.randint(10**6, 10**7),
                "date": f"2026-0{3 + i // 5}-{(i * 3) % 28 + 1:02d}",
                "opponent": opponents[i],
                "opponent_id": 1000 + i,
                "venue": "home" if i % 2 == 0 else "away",
                "goals_for": rng.randint(0, 3),
                "goals_against": rng.randint(0, 3),
                "result": rng.choice(["W", "D", "L"]),
                "competition": competition,
                "stats": {"ALL": full, "1ST": first, "2ND": second},
                "against": {"ALL": opp, "1ST": opp_first, "2ND": opp_second},
            })
        return matches

    def make_players(squad: list[str], matches: list[dict]) -> list[dict]:
        out = []
        for match in matches:
            for name, pos in zip(squad, positions):
                if rng.random() < 0.15:      # rotation and injuries
                    continue
                attacking = pos in ("F", "M")
                out.append({
                    "player": name,
                    "player_id": abs(hash(name)) % 100000,
                    "position": pos,
                    "started": rng.random() > 0.2,
                    "match_id": match["id"],
                    "date": match["date"],
                    "opponent": match["opponent"],
                    "venue": match["venue"],
                    "minutes": rng.choice([90, 90, 90, 78, 64, 21]),
                    "stats": {
                        "Shots": max(0, round(rng.gauss(2.2 if attacking else 0.4, 1.3))),
                        "Shots on target": max(0, round(rng.gauss(0.9 if attacking else 0.2, 0.9))),
                        "Tackles": max(0, round(rng.gauss(1.8, 1.2))),
                        "Passes": max(0, round(rng.gauss(45 if pos == "D" else 30, 14))),
                        "Fouls": max(0, round(rng.gauss(1.1, 1.0))),
                        "Rating": round(rng.gauss(6.9, 0.6), 1),
                    },
                })
        return out

    # Real kit primaries, so the colour handling is exercised by the demo.
    DEMO_KITS = {
        "Espanyol": "#0072ce", "Levante UD": "#004b9b",
        "Getafe": "#005999", "Rayo Vallecano": "#ffffff",
    }

    SQUADS = {
        "Espanyol": ["Dmitrovic", "El Hilali", "Riedel", "Cabrera", "Exposito",
                     "Dolan", "R. Fernandez", "Pere Milla", "Urko Gonzalez", "Calatrava"],
        "Levante UD": ["Cardenas", "Toljan", "Elgezabal", "Sanchez", "Rey",
                       "Romero", "Etta Eyong", "Morales", "Vencedor", "Brugue"],
        "Getafe": ["Soria", "Duarte", "Alderete", "Iglesias", "Milla",
                   "Maksimovic", "Mayoral", "Uche", "Arambarri", "Santi"],
        "Rayo Vallecano": ["Batalla", "Balliu", "Lejeune", "Mumin", "Valentin",
                           "Ciss", "De Frutos", "Camello", "Palazon", "Perez"],
    }

    def one(home: str, away: str, promoted: bool = False) -> dict:
        # One fixture has a "promoted" away side so the mismatch guard and the
        # tier fallback are both visible; the other has two same-division
        # sides so the matchup scan has something legitimate to find.
        matches = [
            make_matches(1.15),
            make_matches(0.9, "Segunda (demo data)" if promoted
                         else "LaLiga (demo data)"),
        ]
        names = hitrates.stat_names(*matches)
        meetings = [make_matches(1.05)[:6], make_matches(0.95)[:6]]
        h2h_names = hitrates.stat_names(*meetings)
        players = [make_players(SQUADS[home], matches[0]),
                   make_players(SQUADS[away], matches[1])]
        pnames = hitrates.player_stat_names(*players)
        return {
            "fixture": {
                "id": rng.randint(10**6, 10**7),
                "home": home,
                "away": away,
                "competition": "LaLiga (demo data)",
                "date": "Sunday 16 August 2026, 18:00 UTC",
                "kickoff": 4102444800,   # far future, so the demo never hides
            },
            "teams": [{"name": home, "side": "home"}, {"name": away, "side": "away"}],
            "colours": {
                "light": list(clubcolour.pair_for(
                    DEMO_KITS.get(home), DEMO_KITS.get(away), "light")),
                "dark": list(clubcolour.pair_for(
                    DEMO_KITS.get(home), DEMO_KITS.get(away), "dark")),
                "kits": [DEMO_KITS.get(home), DEMO_KITS.get(away)],
            },
            "records": matches,
            "stats": names,
            "lines": hitrates.suggest_lines(matches, names),
            "players": players,
            "playerStats": pnames,
            "playerLines": hitrates.suggest_player_lines(players, pnames),
            "projection": {
                "ALL": {name: [round(mean * 1.15 * 0.8, 1), round(mean * 0.7, 1)]
                        for name, mean, _ in team_stats},
            },
            "ratingTeams": 20,
            "h2h": meetings,
            "h2hStats": h2h_names,
            "h2hLines": hitrates.suggest_lines(meetings, h2h_names),
        }

    # A demo tier map, so the Opposition control and the promoted-side
    # fallback can both be checked without touching the network. The ten
    # demo opponents are stacked top to bottom in the order they are listed.
    demo_tiers = {
        str(1000 + i): ("top" if i < 3 else "upper" if i < 5
                        else "lower" if i < 7 else "bottom")
        for i in range(10)
    }

    fixtures = [one("Espanyol", "Levante UD"),
                one("Getafe", "Rayo Vallecano", promoted=True)]

    for entry in fixtures:
        entry["tiers"] = {
            "map": demo_tiers,
            "labels": hitrates.TIER_LABELS,
            "of": ["upper", "bottom"],
        }

    # Second fixture stands in for Arsenal v Coventry: the away side cannot
    # be rated, so the fitted projection is removed and the estimate from the
    # rated side's record against bottom-tier opposition takes its place.
    promoted = fixtures[1]
    promoted.pop("projection", None)
    promoted["ratingNotes"] = [
        "Rayo Vallecano: only 1 of their recent matches were against a team "
        "in this division, so no opponent-adjusted projection is shown for them"
    ]
    promoted["tierProjection"] = hitrates.tier_projection(
        rated_records=promoted["records"][0],
        tier_map={1000 + i: v for i, v in enumerate(
            ["top", "top", "top", "upper", "upper", "lower", "lower",
             "bottom", "bottom", "bottom"])},
        opponent_id=9999,
        rated_is_home=True,
        min_matches=2,
    )
    promoted["tierProjectionFrom"] = "Getafe"
    for entry in fixtures:
        print_summary(entry)

    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / "demo.html"
    report.write_report({"fixtures": fixtures, "periods": hitrates.PERIODS}, path)
    print(f"\nWritten to {path}")
    return path


def parse_picks(text: str, limit: int) -> list[int]:
    picks = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part)
        if not 0 <= value < limit:
            raise SystemExit(f"--pick values must be between 0 and {limit - 1}")
        picks.append(value)
    return picks


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--search", help="find a team id by name")
    parser.add_argument("--team", type=int, help="team id, from --search")
    parser.add_argument("--teams", help="comma-separated team ids, next fixture of each")
    parser.add_argument(
        "--names",
        help="comma-separated club NAMES, resolved to ids automatically, then "
             "the next fixture of each. Use when you know who is playing but "
             "not their ids: --names \"Benfica,Fenerbahce,Basel\"",
    )
    parser.add_argument(
        "--league",
        help="a whole competition's next round, e.g. premier_league, la_liga",
    )
    parser.add_argument(
        "--leagues",
        help="several competitions, comma separated. One report each.",
    )
    parser.add_argument("--pick", help="index, or comma-separated indices, from the list")
    parser.add_argument("--games", type=int, default=10, help="matches per team")
    parser.add_argument("--show", type=int, default=5, help="how many fixtures to list")
    parser.add_argument(
        "--all-stats", action="store_true", dest="all_stats",
        help="keep every stat, not just the ones you can bet on",
    )
    parser.add_argument(
        "--adjust", action="store_true",
        help="fit opponent-adjusted ratings and project this fixture",
    )
    parser.add_argument(
        "--h2h", action="store_true",
        help="also fetch previous meetings between the two teams",
    )
    parser.add_argument(
        "--players", action="store_true",
        help="also fetch per-player stats (one extra request per match)",
    )
    parser.add_argument(
        "--tiers", action="store_true",
        help="split each team's record by the standard of the opposition, "
             "and project promoted fixtures from the rated side's record "
             "against bottom-tier opponents (wants --games 38)",
    )
    parser.add_argument("--no-open", action="store_true", help="don't launch a browser")
    parser.add_argument("--demo", action="store_true", help="synthetic data, no network")
    args = parser.parse_args()

    if args.demo:
        demo()
        return

    if args.search:
        do_search(args.search)
        return

    # Several divisions in one go. Each gets its own report rather than one
    # enormous file, so the index reads as a list of rounds and no single
    # page has to carry a hundred fixtures.
    if args.leagues:
        wanted = [x.strip() for x in args.leagues.split(",") if x.strip()]
        built, failed = [], []
        for name in wanted:
            print(f"\n{'=' * 60}\n{name}\n{'=' * 60}")
            try:
                sub = argparse.Namespace(**vars(args))
                sub.leagues = None
                sub.league = name
                sub.no_open = True
                main_for(sub)
                built.append(name)
            except SystemExit as exc:
                print(f"  {name} failed: {exc}")
                failed.append(name)

        print(f"\n\nBuilt {len(built)} report(s): {', '.join(built) or 'none'}")
        if failed:
            print(f"Failed: {', '.join(failed)}")
        print("Now run: python make_index.py")
        return

    main_for(args)


def main_for(args) -> None:
    league_filter = None

    # A whole competition: read the team list off the league table, then
    # take each team's next fixture. Two teams playing each other collapse
    # to one fixture, so 20 clubs give you a 10-match round.
    if args.league:
        tournament_id = api.tournament_id_for(args.league)
        if tournament_id is None:
            key = args.league.lower().replace("-", "_").replace(" ", "_")
            if key.isdigit():
                tournament_id = int(key)
            else:
                raise SystemExit(
                    f"Unknown league '{args.league}'. Known: "
                    + ", ".join(sorted(api.TOURNAMENTS))
                    + "\nOr pass a uniqueTournament id directly."
                )

        print(f"Reading the {args.league} team list...")
        ids = api.tournament_team_ids(tournament_id)
        if not ids:
            raise SystemExit(
                "\nCouldn't read the team list. That endpoint may have moved,\n"
                "the same way the fixtures one did. Add these to check.py and run it:\n"
                f"  unique-tournament/{tournament_id}/seasons\n"
                f"  unique-tournament/{tournament_id}/season/SEASON_ID/standings/total\n"
                "\nIn the meantime --teams with a comma-separated list still works."
            )
        print(f"  {len(ids)} teams")
        args.teams = ",".join(str(i) for i in ids)
        league_filter = tournament_id

    # Names first: resolve them to ids and then fall through to exactly the
    # same path --teams uses, so there is only one code path to trust.
    if args.names:
        print("Resolving club names...")
        found = resolve_names(args.names)
        if not found:
            raise SystemExit("None of those names resolved to a team.")
        args.teams = ",".join(str(i) for i in found)

    # Several teams: take each one's next fixture, de-duplicated in case two
    # of them happen to be playing each other.
    if args.teams:
        ids = [int(x.strip()) for x in args.teams.split(",") if x.strip()]
        events, seen = [], set()
        for team_id in ids:
            event = team_next_fixture(team_id, league_filter)
            if not event:
                if league_filter is None:
                    print(f"  no fixture found for team {team_id}")
                continue
            if event["id"] in seen:
                continue
            seen.add(event["id"])
            events.append(event)

        if not events:
            raise SystemExit("No fixtures found for any of those teams.")

        print(f"\n{len(events)} fixture(s) to build:")
        for event in events:
            print(f"  {describe(event)}")

        build(events, args.games, not args.no_open, args.players,
              args.h2h, args.adjust, args.all_stats, args.tiers)
        return

    if args.team is None:
        parser.print_help()
        print("\nStart with:  python run.py --search espanyol\n")
        return

    info = api.get_json(f"team/{args.team}", max_age_hours=168) or {}
    team_name = info.get("team", {}).get("name", f"team {args.team}")

    events = api.team_next_events(args.team)[: args.show]
    if not events:
        fallback = team_next_fixture(args.team)
        events = [fallback] if fallback else []

    if args.pick is None:
        list_fixtures(events, team_name)
        return

    picks = parse_picks(args.pick, len(events))
    build([events[i] for i in picks], args.games, not args.no_open,
          args.players, args.h2h, args.adjust, args.all_stats, args.tiers)


if __name__ == "__main__":
    main()
