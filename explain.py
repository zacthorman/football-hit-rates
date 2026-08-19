"""
Show the working behind a projection.

    python explain.py --event 16391149 --stat "Corner kicks"

A projection is four numbers multiplied together, so when one looks wrong the
fastest way to find out why is to print all four rather than argue about the
result. This prints the league average, both teams' fitted ratings, how many
matches each rating was fitted from, and the arithmetic.

Ratings fitted from too few matches are the usual culprit, and they are also
the ones that look most confident, because a number carries no memory of how
much data produced it.
"""

from __future__ import annotations

import argparse

import hitrates
import run as runner
import sofascore_api as api


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", type=int, required=True)
    parser.add_argument("--stat", default="Corner kicks")
    parser.add_argument("--period", default="ALL")
    parser.add_argument("--games", type=int, default=10)
    args = parser.parse_args()

    event = api.get_json(f"event/{args.event}", max_age_hours=1) or {}
    event = event.get("event", event)
    if not event.get("id"):
        raise SystemExit(f"Could not find event {args.event}")

    home, away = event["homeTeam"], event["awayTeam"]
    tid = event.get("tournament", {}).get("uniqueTournament", {}).get("id")

    print(f"\n{home['name']} v {away['name']}")
    print(f"{args.stat}, {hitrates.PERIODS.get(args.period, args.period)}\n")

    fitted = runner.league_ratings_for(tid, args.games)
    if not fitted:
        raise SystemExit("No ratings could be fitted for this competition.")
    ratings, names = fitted

    stat = args.stat
    per = args.period
    league = ratings["average"].get(per, {}).get(stat)
    home_base = ratings["home"].get(per, {}).get(stat)
    away_base = ratings["away"].get(per, {}).get(stat)

    if league is None:
        raise SystemExit(
            f"'{stat}' is not in the fitted set. Available:\n  "
            + ", ".join(sorted(ratings["average"].get(per, {})))
        )

    print(f"League average per team per match : {league:.2f}")
    print(f"  when at home                    : {home_base:.2f}")
    print(f"  when away                       : {away_base:.2f}\n")

    for team, label in ((home, "HOME"), (away, "AWAY")):
        tid_s = str(team["id"])
        att = ratings["attack"].get(tid_s, {}).get(per, {}).get(stat)
        dfn = ratings["defence"].get(tid_s, {}).get(per, {}).get(stat)

        records = hitrates.team_form(
            team_id=team["id"], team_name=team["name"],
            tournament_id=tid, limit=args.games, verbose=False,
        )
        mine = [r["stats"][per][stat] for r in records if stat in r["stats"].get(per, {})]
        theirs = [
            r["against"][per][stat] for r in records
            if stat in r.get("against", {}).get(per, {})
        ]

        # How many of those matches were against sides that are in the fitted
        # pool? Only those can contribute to a rating.
        pool = set(int(x) for x in ratings["attack"])
        usable = sum(1 for r in records if r.get("opponent_id") in pool)

        print(f"{label}: {team['name']}")
        print(f"  raw average for      {sum(mine)/len(mine):.2f}" if mine else "  no data")
        print(f"  raw average against  {sum(theirs)/len(theirs):.2f}" if theirs else "")
        print(f"  attack rating        {att if att is None else f'{att:.2f}'}")
        print(f"  defence rating       {dfn if dfn is None else f'{dfn:.2f}'}")
        print(f"  matches in sample    {len(records)}")
        print(f"  of those, usable     {usable}   "
              f"{'<-- too few to fit a rating' if usable < 4 else ''}")
        comps = {}
        for r in records:
            comps[r.get("competition", "?")] = comps.get(r.get("competition", "?"), 0) + 1
        print(f"  competitions         {', '.join(f'{v} {k}' for k, v in comps.items())}")
        print()

    ha = ratings["attack"].get(str(home["id"]), {}).get(per, {}).get(stat)
    hd = ratings["defence"].get(str(home["id"]), {}).get(per, {}).get(stat)
    aa = ratings["attack"].get(str(away["id"]), {}).get(per, {}).get(stat)
    ad = ratings["defence"].get(str(away["id"]), {}).get(per, {}).get(stat)

    if None in (ha, hd, aa, ad):
        print("At least one rating is missing, so no projection is produced.")
        return

    print("The arithmetic:")
    print(f"  {home['name']:<22} = {home_base:.2f} (home base)"
          f" x {ha:.2f} (their attack) x {ad:.2f} (opponent defence)"
          f" = {home_base * ha * ad:.2f}")
    print(f"  {away['name']:<22} = {away_base:.2f} (away base)"
          f" x {aa:.2f} (their attack) x {hd:.2f} (opponent defence)"
          f" = {away_base * aa * hd:.2f}")
    print("\nIf either rating sits near 1.00 with few usable matches, that is not")
    print("a measurement, it is the model saying 'exactly average' because it has")
    print("nothing to go on.")


if __name__ == "__main__":
    main()
