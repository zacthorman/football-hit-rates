"""
Which markets exist, and what they are called here.

A module of its own, with no imports at all, deliberately. Both the analysis
code and the page renderer need this list, and the renderer has no business
pulling in the HTTP stack to find out what a bettable market is. It did, once,
and the result was that re-rendering a saved page failed on a machine with no
curl_cffi installed.
"""

from __future__ import annotations

# Shown first, in this order, when present. Anything else the endpoint
# returns is still collected and appears after these.
PREFERRED_STATS = [
    "Goals",
    "Total shots",
    "Shots on target",
    "Corner kicks",
    "Fouls",
    "Tackles",
    "Offsides",
    "Throw-ins",
    "Yellow cards",
    "Red cards",
    "Free kicks",
    "Goal kicks",
]

# Stats where a hit-rate line makes no sense or reads oddly.
SKIP_STATS = {"Ball possession"}

# Markets you can actually get a price on. SofaScore returns a great deal
# more than this (goals prevented, expected assists, duels won), all of it
# interesting and none of it bettable, and every extra row is another
# combination for the Standout scan to trawl through and another chance for
# a coincidence to look like a finding. Pass --all-stats to see everything.
BETTABLE_STATS = {
    # Matched against the markets bet365 actually prices on a football match.
    # Anything the endpoint returns that has no market attached is dropped:
    # it cannot be bet, and every extra row is another combination for the
    # Standout scan to trawl and another chance for a fluke to look like a
    # finding. Use --all-stats to see everything again.
    "Goals",              # Team Total Goals, Over/Under, Both Teams to Score
    "Total shots",        # Total Shots
    "Shots on target",    # Total Shots on Target
    "Corner kicks",       # Corners
    "Offsides",           # Total Offsides
    "Tackles",            # Total Tackles
    "Fouls",              # Fouls Committed, and Fouls Won via the Against measure
    "Yellow cards",       # Cards
    "Red cards",          # Red Card in Match / Half
    "Throw-ins",          # Throw Ins
    "Goal kicks",         # Goal Kicks
    "Free kicks",         # Free Kicks
}

# The same idea for player props.
BETTABLE_PLAYER_STATS = {
    "Shots",              # Shots
    "Shots on target",    # Shots on Target
    "Goals",              # Player to Score
    "Assists",            # Score or Assist
    "Tackles",            # Tackles
    "Fouls",              # Fouls Committed
    "Fouled",             # To Be Fouled
    "Passes",             # Passes
    "Saves",              # Goalkeeper Saves
    "Minutes",            # not a market, but it decides whether the rest matter
}

# Dropped because bet365 prices them but SofaScore does not report them per
# player, so there is nothing to build a hit rate from: headed shots on
# target, shots on target outside the box, and player cards.

