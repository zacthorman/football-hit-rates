"""
Probe SofaScore endpoints and report what each one returns.

Run it with:   python check.py

No caching, no parsing, nothing clever. It asks for a list of candidate
paths and prints the status code and response size for each, so you can see
at a glance which are alive and which have moved.

This is the fastest way to find out what an undocumented API currently
supports, and it beats guessing one path at a time inside a bigger program.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

from curl_cffi import requests

BASE = "https://www.sofascore.com/api/v1"

TODAY = date.today().isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()

# UTC offset in seconds. SofaScore uses this in some date-scoped paths:
# the event-count call visible in DevTools is /sport/3600/event-count,
# where 3600 is UTC+1.
OFFSET = 3600

ESPANYOL = 2814
KNOWN_EVENT = 16421053  # Espanyol v Levante, 16 Aug 2026

CANDIDATES = [
    # Controls. These worked earlier, so if they fail now something broader
    # has changed and the rest of the results mean nothing.
    "sport/football/events/live",
    f"team/{ESPANYOL}/events/last/0",
    f"event/{KNOWN_EVENT}/statistics",
    f"event/{KNOWN_EVENT}/lineups",

    # The one that 404s. Is it the path, or the date?
    f"sport/football/scheduled-events/{TODAY}",
    f"sport/football/scheduled-events/{TOMORROW}",

    # Same idea, other shapes seen in the wild.
    f"sport/{OFFSET}/scheduled-events/{TODAY}",
    f"sport/{OFFSET}/event-count/{TODAY}",
    f"sport/{OFFSET}/event-count",
    f"scheduled-events/{TODAY}",
    f"sport/football/scheduled-events/{TODAY}/inverse",

    # Upcoming fixtures per team. If this works we do not need a date
    # endpoint at all, and "Espanyol's next match" is a nicer way in anyway.
    f"team/{ESPANYOL}/events/next/0",
    f"team/{ESPANYOL}/near-events",
    f"team/{ESPANYOL}",

    # Current squad. Used to drop players who have since been sold, so the
    # player tables reflect this season's squad rather than last season's.
    f"team/{ESPANYOL}/players",

    # Head to head: previous meetings between the two teams in a fixture.
    f"event/{KNOWN_EVENT}/h2h",
    f"event/{KNOWN_EVENT}/h2h/events",

    # Competition-level. Needed for --league, which reads a whole division's
    # team list off the league table instead of you typing twenty ids.
    "unique-tournament/17/seasons",
    "unique-tournament/17",
    "unique-tournament/17/featured-events",
]


def main() -> None:
    session = requests.Session(impersonate="chrome")
    session.headers.update(
        {
            "Accept": "*/*",
            "Accept-Language": "en-GB,en;q=0.9",
            "Referer": "https://www.sofascore.com/",
        }
    )

    width = max(len(p) for p in CANDIDATES)
    print(f"\n{'path':<{width}}  {'code':>4}  {'bytes':>8}  note")
    print("-" * (width + 32))

    for path in CANDIDATES:
        url = f"{BASE}/{path}"
        try:
            response = session.get(url, timeout=20)
            code = response.status_code
            size = len(response.text)

            note = ""
            if code == 200:
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        keys = list(data.keys())[:4]
                        note = "keys: " + ", ".join(str(k) for k in keys)
                        if "events" in data:
                            note += f"  ({len(data['events'])} events)"
                except Exception:
                    note = "200 but not JSON"
            elif code == 404:
                note = "not found"
            elif code == 403:
                note = "blocked"
            elif code == 429:
                note = "rate limited"

            print(f"{path:<{width}}  {code:>4}  {size:>8}  {note}")

        except Exception as exc:
            print(f"{path:<{width}}  {'---':>4}  {'---':>8}  {type(exc).__name__}")

        time.sleep(1.2)

    print(
        "\nAnything at 200 is usable. If the controls at the top are 200 and the\n"
        "scheduled-events rows are 404, the path has moved and the fix is to read\n"
        "the right one off the Network tab on sofascore.com.\n"
    )


if __name__ == "__main__":
    main()
