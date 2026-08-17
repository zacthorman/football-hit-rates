"""
Build a fixture hit-rate report.

    python run.py --demo                        synthetic data, no network
    python run.py --search espanyol             find a team's id
    python run.py --team 2814                   list that team's next fixtures
    python run.py --team 2814 --pick 0          build the report
    python run.py --team 2814 --pick 0,1,2      three fixtures in one report
    python run.py --teams 2814,2833,2817        each team's next fixture
    python run.py --league premier_league       the whole next round

Add --players for per-player stats.

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
    return (
        f"{when:>16}  {event['homeTeam']['name']} v {event['awayTeam']['name']}"
        f"  ({tournament})"
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


def list_fixtures(events: list[dict], team_name: str) -> None:
    if not events:
        print(f"\nNo upcoming fixtures found for {team_name}.")
        return
    print(f"\nNext fixtures for {team_name}:\n")
    for i, event in enumerate(events):
        print(f"  [{i}] {describe(event)}")
    print("\nRe-run with --pick N to build a report.\n")


def team_next_fixture(team_id: int) -> dict | None:
    """That team's next scheduled match, or their last one if none is set."""
    upcoming = api.team_next_events(team_id)
    if upcoming:
        return upcoming[0]
    near = api.team_near_events(team_id)
    return near.get("nextEvent") or near.get("previousEvent")


def build_fixture(event: dict, games: int, players: bool) -> dict | None:
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

    names = hitrates.stat_names(*records)
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
        },
        "teams": [
            {"name": home["name"], "side": "home"},
            {"name": away["name"], "side": "away"},
        ],
        "records": records,
        "stats": names,
        "lines": lines,
    }

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
        entry["playerStats"] = hitrates.player_stat_names(*player_records)
        entry["playerLines"] = hitrates.suggest_player_lines(
            player_records, entry["playerStats"]
        )

    print_summary(entry)
    return entry


def build(events: list[dict], games: int, open_browser: bool, players: bool) -> Path:
    fixtures = []
    for i, event in enumerate(events, start=1):
        print(f"\n[{i}/{len(events)}]", end="")
        entry = build_fixture(event, games, players)
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
    if len(fixtures) == 1:
        slug = f"{first['home']}-v-{first['away']}"
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

    def make_matches(strength: float) -> list[dict]:
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
            matches.append({
                "id": rng.randint(10**6, 10**7),
                "date": f"2026-0{3 + i // 5}-{(i * 3) % 28 + 1:02d}",
                "opponent": opponents[i],
                "venue": "home" if i % 2 == 0 else "away",
                "goals_for": rng.randint(0, 3),
                "goals_against": rng.randint(0, 3),
                "result": rng.choice(["W", "D", "L"]),
                "stats": {"ALL": full, "1ST": first, "2ND": second},
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

    def one(home: str, away: str) -> dict:
        matches = [make_matches(1.15), make_matches(0.9)]
        names = hitrates.stat_names(*matches)
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
            },
            "teams": [{"name": home, "side": "home"}, {"name": away, "side": "away"}],
            "records": matches,
            "stats": names,
            "lines": hitrates.suggest_lines(matches, names),
            "players": players,
            "playerStats": pnames,
            "playerLines": hitrates.suggest_player_lines(players, pnames),
        }

    fixtures = [one("Espanyol", "Levante UD"), one("Getafe", "Rayo Vallecano")]
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
        "--league",
        help="a whole competition's next round, e.g. premier_league, la_liga",
    )
    parser.add_argument("--pick", help="index, or comma-separated indices, from the list")
    parser.add_argument("--games", type=int, default=10, help="matches per team")
    parser.add_argument("--show", type=int, default=5, help="how many fixtures to list")
    parser.add_argument(
        "--players", action="store_true",
        help="also fetch per-player stats (one extra request per match)",
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

    # A whole competition: read the team list off the league table, then
    # take each team's next fixture. Two teams playing each other collapse
    # to one fixture, so 20 clubs give you a 10-match round.
    if args.league:
        key = args.league.lower().replace("-", "_").replace(" ", "_")
        tournament_id = api.TOURNAMENTS.get(key)
        if tournament_id is None:
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

    # Several teams: take each one's next fixture, de-duplicated in case two
    # of them happen to be playing each other.
    if args.teams:
        ids = [int(x.strip()) for x in args.teams.split(",") if x.strip()]
        events, seen = [], set()
        for team_id in ids:
            event = team_next_fixture(team_id)
            if not event:
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

        build(events, args.games, not args.no_open, args.players)
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
    build([events[i] for i in picks], args.games, not args.no_open, args.players)


if __name__ == "__main__":
    main()
