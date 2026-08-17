"""
Cached client for SofaScore's public JSON API.

Every response is written to disk before it is parsed. That means:

  * reruns cost nothing and hit no network
  * you keep the raw data even if SofaScore changes the format later
  * you cannot accidentally hammer them into rate-limiting you

Finished matches never change, so their cache entries are permanent.
Fixture lists and live scores do change, so those pass a max_age.
"""

from __future__ import annotations

import json
import random
import time
from datetime import date
from pathlib import Path
from typing import Any

from curl_cffi import requests

# The site itself calls www.sofascore.com/api/v1, not api.sofascore.com.
# Always use the host the browser uses.
BASE = "https://www.sofascore.com/api/v1"

CACHE_DIR = Path(__file__).parent / "cache"

MIN_DELAY = 1.0
MAX_DELAY = 2.0

# Competition ids. Find more by opening a league page with DevTools on the
# Network tab and reading the uniqueTournament id out of any request.
TOURNAMENTS = {
    "premier_league": 17,
    "championship": 18,
    "la_liga": 8,
    "serie_a": 23,
    "bundesliga": 35,
    "ligue_1": 34,
    "champions_league": 7,
    "europa_league": 679,
}

_session = None


def _get_session():
    """One session for the whole run, so cookies persist between requests.

    Reusing a session matters more than any individual header: once
    Cloudflare has decided you are acceptable, the clearance cookie rides
    along on everything afterwards.
    """
    global _session
    if _session is None:
        _session = requests.Session(impersonate="chrome")
        _session.headers.update(
            {
                "Accept": "*/*",
                "Accept-Language": "en-GB,en;q=0.9",
                "Referer": "https://www.sofascore.com/",
                "Origin": "https://www.sofascore.com",
            }
        )
    return _session


def _cache_file(path: str) -> Path:
    """Human-readable cache filename, so you can browse what you've collected.

    'event/123/statistics' becomes 'event_123_statistics.json'. Hashing the
    URL would work too, but then debugging means staring at files called
    a3f9c2....json.
    """
    name = path.strip("/").replace("/", "_").replace("?", "_").replace("&", "_")
    return CACHE_DIR / f"{name}.json"


def get_json(
    path: str,
    max_age_hours: float | None = None,
    verbose: bool = True,
) -> Any | None:
    """Fetch an API path, reusing the cached copy when there is one.

    max_age_hours=None means the cache never expires, which is correct for
    anything about a finished match. Pass a number for data that moves.

    Returns None on any non-200, so callers decide what a failure means.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_file(path)

    if cache_file.exists():
        fresh = max_age_hours is None or (
            time.time() - cache_file.stat().st_mtime < max_age_hours * 3600
        )
        if fresh:
            try:
                return json.loads(cache_file.read_text())
            except json.JSONDecodeError:
                # Half-written file from an interrupted run. Drop it and refetch.
                cache_file.unlink(missing_ok=True)

    url = f"{BASE}/{path.strip('/')}"

    for attempt in range(3):
        try:
            response = _get_session().get(url, timeout=30)
        except Exception as exc:
            if verbose:
                print(f"    {type(exc).__name__} on {path}, retrying")
            time.sleep(2**attempt)
            continue

        if response.status_code == 200:
            try:
                data = response.json()
            except json.JSONDecodeError:
                if verbose:
                    print(f"    non-JSON response on {path}")
                return None
            cache_file.write_text(json.dumps(data))
            # Sleep only after a real network call. Cache hits return above,
            # so a fully cached run is instant.
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
            return data

        if response.status_code == 404:
            # Usually means "this genuinely does not exist" rather than an
            # error, so no retry and no cache. Still worth saying out loud:
            # a silent 404 is indistinguishable from an empty result, and
            # that ambiguity wastes a lot of debugging time.
            if verbose:
                print(f"    404 on {path}")
            return None

        if response.status_code in (403, 429):
            wait = (2**attempt) * 5
            if verbose:
                print(f"    {response.status_code} on {path}, backing off {wait}s")
            time.sleep(wait)
            continue

        if verbose:
            print(f"    unexpected {response.status_code} on {path}")
        time.sleep(2**attempt)

    return None


# --------------------------------------------------------------- endpoints


def current_season_id(tournament_id: int) -> int | None:
    """The most recent season for a competition."""
    data = get_json(f"unique-tournament/{tournament_id}/seasons", max_age_hours=168)
    seasons = (data or {}).get("seasons", [])
    return seasons[0]["id"] if seasons else None


def tournament_team_ids(tournament_id: int, season_id: int | None = None) -> list[int]:
    """Every team in a competition, read off the league table.

    Used so you can say "the Premier League" instead of listing twenty ids.
    Returns an empty list if the endpoint has moved, and the caller decides
    what to do about it.
    """
    if season_id is None:
        season_id = current_season_id(tournament_id)
    if season_id is None:
        return []

    data = get_json(
        f"unique-tournament/{tournament_id}/season/{season_id}/standings/total",
        max_age_hours=24,
    )

    ids: list[int] = []
    for standing in (data or {}).get("standings", []):
        for row in standing.get("rows", []):
            team = row.get("team", {})
            if isinstance(team.get("id"), int):
                ids.append(team["id"])
    return ids


def team_next_events(team_id: int, page: int = 0) -> list[dict]:
    """A team's upcoming fixtures, soonest first."""
    data = get_json(f"team/{team_id}/events/next/{page}", max_age_hours=6)
    return (data or {}).get("events", [])


def team_near_events(team_id: int) -> dict:
    """The team's most recent match and their next one."""
    return get_json(f"team/{team_id}/near-events", max_age_hours=6) or {}


def _looks_like_team(node: dict) -> bool:
    return (
        isinstance(node.get("id"), int)
        and isinstance(node.get("name"), str)
        and "slug" in node
        and "sport" in node
        and node.get("sport", {}).get("slug") == "football"
    )


def _harvest_teams(node, found: dict) -> None:
    """Walk an arbitrary JSON tree collecting anything shaped like a team.

    The search endpoint's response shape is not documented and has changed
    before, so rather than hardcode a path this just looks for the shape.
    Slower, but it survives them rearranging things.
    """
    if isinstance(node, dict):
        if _looks_like_team(node):
            found.setdefault(node["id"], node)
        for value in node.values():
            _harvest_teams(value, found)
    elif isinstance(node, list):
        for item in node:
            _harvest_teams(item, found)


def search_teams(query: str) -> list[dict]:
    """Find football teams by name, so you don't have to know ids.

    Tries a few known search paths and uses whichever answers.
    """
    candidates = [
        f"search/teams?q={query}&page=0",
        f"search/all?q={query}&page=0",
        f"search/{query}",
    ]

    for path in candidates:
        data = get_json(path, max_age_hours=24, verbose=False)
        if not data:
            continue
        found: dict[int, dict] = {}
        _harvest_teams(data, found)
        if found:
            return list(found.values())

    return []


def team_events(team_id: int, page: int = 0) -> list[dict]:
    """A team's past matches, ~30 per page. Page 0 is the most recent.

    Returned oldest-first, so the most recent are at the end of the list.
    """
    data = get_json(f"team/{team_id}/events/last/{page}", max_age_hours=6)
    return (data or {}).get("events", [])


def event_statistics(event_id: int) -> dict | None:
    """Team-level match stats: shots, corners, offsides, throw-ins, cards."""
    return get_json(f"event/{event_id}/statistics")


def event_lineups(event_id: int) -> dict | None:
    """Per-player stats for one match."""
    return get_json(f"event/{event_id}/lineups")


def cache_summary() -> str:
    if not CACHE_DIR.exists():
        return "cache is empty"
    files = list(CACHE_DIR.glob("*.json"))
    size = sum(f.stat().st_size for f in files) / 1_000_000
    return f"{len(files)} cached responses, {size:.1f} MB"
