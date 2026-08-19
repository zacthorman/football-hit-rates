"""
Log picks before kickoff, settle them from results, report honestly.

    python track.py add --event 14083629 --team 2814 --stat "Total shots" \
                        --line 12.5 --side over --price 1.95
    python track.py settle
    python track.py report

Why this exists, and why it comes before anything you might sell.

You have no evidence yet that any of this beats the market. Nobody does after
a few weeks. The only way to find out is to write picks down before the match
with the price you could actually have got, settle them from the result rather
than from memory, and count. Everything else is opinion.

Three rules are enforced rather than suggested, because a record that can be
quietly tidied is worth nothing:

  * a pick cannot be logged once the match has kicked off
  * settlement reads the result from the API, so a loser cannot be dropped
  * the model's numbers at the time are stored, so you can later ask whether
    its signal predicted anything at all

If you ever advertise this in the UK, the ASA requires claims about winners
to be recorded with a demonstrably independent body BEFORE the event. This
file is not that. It is your own record, which is the thing you need first to
find out whether there is anything worth advertising.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

import hitrates
import sofascore_api as api

PICKS = Path(__file__).parent / "picks.json"


def load() -> list[dict]:
    if not PICKS.exists():
        return []
    return json.loads(PICKS.read_text())


def save(picks: list[dict]) -> None:
    PICKS.write_text(json.dumps(picks, indent=2))


def now() -> float:
    return datetime.now(tz=timezone.utc).timestamp()


def add(args) -> None:
    event = api.get_json(f"event/{args.event}", max_age_hours=1)
    event = (event or {}).get("event", event or {})
    if not event.get("id"):
        raise SystemExit(f"Could not find event {args.event}")

    kickoff = event.get("startTimestamp", 0)
    if kickoff and kickoff <= now():
        raise SystemExit(
            "That match has already started.\n"
            "Picks logged after kickoff prove nothing, so this refuses to record one."
        )

    home = event.get("homeTeam", {})
    away = event.get("awayTeam", {})
    if args.team not in (home.get("id"), away.get("id")):
        raise SystemExit(
            f"Team {args.team} is not in this fixture "
            f"({home.get('id')} {home.get('name')} v {away.get('id')} {away.get('name')})"
        )

    team_name = home.get("name") if args.team == home.get("id") else away.get("name")

    pick = {
        "logged_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "event_id": event["id"],
        "fixture": f"{home.get('name')} v {away.get('name')}",
        "kickoff": kickoff,
        "team_id": args.team,
        "team": team_name,
        "stat": args.stat,
        "period": args.period,
        "line": args.line,
        "side": args.side,
        "price": args.price,
        "stake": args.stake,
        "model_rate": args.rate,
        "model_need": args.need,
        "model_proj": args.proj,
        "result": None,
        "value": None,
        "profit": None,
    }

    picks = load()
    picks.append(pick)
    save(picks)

    print(f"Logged: {team_name} {args.side} {args.line} {args.stat} at {args.price}")
    print(f"  {pick['fixture']}, kickoff in "
          f"{(kickoff - now()) / 3600:.1f} hours")
    print(f"  {len(picks)} pick(s) on record")


def settle(args) -> None:
    picks = load()
    if not picks:
        raise SystemExit("Nothing logged yet.")

    settled = 0
    for pick in picks:
        if pick["result"] is not None:
            continue
        if pick["kickoff"] and pick["kickoff"] > now():
            continue

        raw = api.event_statistics(pick["event_id"])
        stats = hitrates.extract_match_stats(raw)
        if not stats:
            continue

        event = api.get_json(f"event/{pick['event_id']}", max_age_hours=1) or {}
        event = event.get("event", event)
        if event.get("status", {}).get("type") != "finished":
            continue

        is_home = event.get("homeTeam", {}).get("id") == pick["team_id"]
        index = 0 if is_home else 1

        bucket = stats.get(pick["period"], {})
        if pick["stat"] not in bucket:
            print(f"  {pick['fixture']}: '{pick['stat']}' not reported, left open")
            continue

        value = bucket[pick["stat"]][index]
        won = value > pick["line"] if pick["side"] == "over" else value < pick["line"]

        pick["value"] = value
        pick["result"] = "win" if won else "lose"
        pick["profit"] = round(
            pick["stake"] * (pick["price"] - 1) if won else -pick["stake"], 2
        )
        settled += 1
        print(f"  {pick['team']} {pick['side']} {pick['line']} {pick['stat']}: "
              f"{value} -> {pick['result']} ({pick['profit']:+.2f})")

    save(picks)
    print(f"\nSettled {settled}. {sum(1 for p in picks if p['result'] is None)} still open.")


def report(args) -> None:
    picks = [p for p in load() if p["result"] is not None]
    if not picks:
        raise SystemExit("Nothing settled yet. Run: python track.py settle")

    n = len(picks)
    staked = sum(p["stake"] for p in picks)
    profit = sum(p["profit"] for p in picks)
    wins = sum(1 for p in picks if p["result"] == "win")
    roi = profit / staked

    returns = [p["profit"] / p["stake"] for p in picks]
    sd = statistics.stdev(returns) if n > 1 else 0.0
    margin = 1.96 * sd / math.sqrt(n) if n > 1 else float("inf")

    print(f"\n{n} settled pick(s)")
    print(f"  strike rate   {wins}/{n}  ({wins / n * 100:.0f}%)")
    print(f"  staked        {staked:.2f}")
    print(f"  profit        {profit:+.2f}")
    print(f"  ROI           {roi * 100:+.1f}%")

    if n > 1:
        lo, hi = (roi - margin) * 100, (roi + margin) * 100
        print(f"  95% interval  {lo:+.1f}% to {hi:+.1f}%")
        print()
        if lo > 0:
            print("  The interval clears zero. That is real evidence of an edge,")
            print("  though it is still only evidence about the bets you actually made.")
        elif hi < 0:
            print("  The interval is entirely below zero. This is losing money,")
            print("  and more samples will not rescue it.")
        else:
            print("  The interval spans zero, so this is consistent with having no")
            print("  edge at all. That is the expected answer at this sample size,")
            print("  and it is not a reason to stop, only a reason not to sell yet.")

        # How many bets before the answer means anything?
        if sd > 0:
            needed = math.ceil((1.96 * sd / max(abs(roi), 0.02)) ** 2)
            print(f"\n  At this variance, about {needed} settled bets would be needed")
            print(f"  for a {abs(roi) * 100:.0f}% ROI to be distinguishable from luck.")

    # Did the model's own signal predict anything?
    priced = [p for p in picks if p.get("model_need") and p.get("price")]
    if len(priced) >= 10:
        cleared = [p for p in priced if p["price"] >= p["model_need"]]
        missed = [p for p in priced if p["price"] < p["model_need"]]
        print("\n  Split by whether the price cleared the model's Need figure:")
        for label, group in (("cleared", cleared), ("did not", missed)):
            if not group:
                continue
            g_staked = sum(p["stake"] for p in group)
            g_profit = sum(p["profit"] for p in group)
            print(f"    {label:8} {len(group):3} bets  "
                  f"ROI {g_profit / g_staked * 100:+6.1f}%")
        print("  If those two are similar, the model is not adding anything yet.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add", help="log a pick before kickoff")
    a.add_argument("--event", type=int, required=True)
    a.add_argument("--team", type=int, required=True, help="team id")
    a.add_argument("--stat", required=True)
    a.add_argument("--line", type=float, required=True)
    a.add_argument("--side", choices=["over", "under"], default="over")
    a.add_argument("--price", type=float, required=True, help="decimal odds")
    a.add_argument("--stake", type=float, default=1.0)
    a.add_argument("--period", default="ALL", choices=list(hitrates.PERIODS))
    a.add_argument("--rate", type=float, help="the hit rate the report showed")
    a.add_argument("--need", type=float, help="the Need price the report showed")
    a.add_argument("--proj", type=float, help="the projection the report showed")
    a.set_defaults(func=add)

    s = sub.add_parser("settle", help="settle finished picks from results")
    s.set_defaults(func=settle)

    r = sub.add_parser("report", help="honest running record")
    r.set_defaults(func=report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
