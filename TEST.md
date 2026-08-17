# Scraping test

Everything here uses what you've already built. Your notebook should still have `data`, `df`, `lineups` and `players` in memory. If not, Restart Kernel and Run All first.

No looking things up until you've had a proper go. Getting it wrong and reading the error is the point.

---

## Part 1: Read the code (no computer)

Answer these in your head or in a markdown cell. Answers at the bottom, don't peek.

**1.** Why does `players.shape` have no brackets but `players.head()` does?

**2.** These two lines both try to get a player's tackles:

```python
stats["totalTackle"]
stats.get("totalTackle", 0)
```

When does the first one fail, and what does the second one do instead?

**3.** What do each of these give you from a list of 245 matches?

```python
data["events"][:10]
data["events"][-3:]
data["events"][0]
data["events"][10:20]
```

**4.** In your table-building cell, why is `rows = []` written above the `for` loop rather than inside it? What would happen if you moved it inside?

**5.** What does `impersonate="chrome"` actually change about the request, and why does that matter?

**6.** Look at this. It runs without error but is wrong. Why?

```python
for match in data["events"]:
    rows = []
    rows.append(match["homeTeam"]["name"])
print(len(rows))
```

---

## Part 2: Navigate the data (one or two lines each)

**7.** Print the competition name of the 50th live match.

**8.** Count how many of the 245 live matches are in the Premier League. Print the number.

**9.** From your `players` table, print the single highest rating.

**10.** From `players`, show only the players who played more than 60 minutes.

**11.** Print the name of every player in `lineups` who was a substitute.
*Hint: there's a key on each player entry that tells you this directly.*

**12.** Print the name of the away team in the match you fetched lineups for.
*Careful. This one has a trap in it. If you find yourself stuck, that's the lesson.*

---

## Part 3: Build something

**13.** Add a column to `players` called `shot_accuracy`, being shots on target divided by shots, as a percentage rounded to the nearest whole number. Players with zero shots should show `0`, not an error and not `NaN`.

**14.** Save `players` to a CSV whose filename includes the match id, so `players_16421053.csv`.

**15.** Write a function called `get_lineups` that takes a match id and returns the parsed lineups JSON. Then use it to fetch a different match.

You haven't been shown functions yet. The shape is:

```python
def function_name(argument):
    # do something
    return result
```

**16.** Turn your flattening code into a function `lineups_to_table(lineups)` that takes the raw JSON and returns a DataFrame. Test it on two different matches.

*This one matters most. It's the step that turns "code that works once" into "code you can loop 10 times".*

---

## Part 4: Find it yourself

No hints. Use DevTools exactly as you did before.

**17.** Find the endpoint that returns a team's recent matches. Espanyol's team id is `2814`, and it's in your lineups data if you look. Fetch it and print the 10 most recent opponents.

**18.** Find the endpoint for a match's shotmap. Fetch it for your match and print how many shots had an xG above 0.1.

**19.** Find out how to get a single player's season statistics. Print the total shots for any player from your table this season.

---

## Part 5: The real thing

**20.** Using 17 and 16 together, build a table of every player's stats across Espanyol's last 10 matches. One row per player per match.

Requirements:

- a `time.sleep()` of at least 1 second between requests
- skip any match that fails rather than crashing the whole loop
- print progress as it goes, so you can see it working

**21.** From that table, calculate each player's hit rate for **2 or more shots**: the number of matches they hit it, out of matches they played, as a percentage. Show only players who started at least 5 of the 10.

That's the thing you actually wanted. If you get to 21 unaided, you don't need me for the scraping side any more.

---

## Marking

- **Part 1 only:** you can read code but not yet write it. Normal at this stage.
- **Through Part 2:** you understand the data structures. This is the real hurdle and most people stop before it.
- **Through Part 3:** you can write reusable code. This is the point where Claude Code becomes useful to you rather than a replacement for you.
- **Through Part 4:** you can extend to any endpoint without being told how, which means any site, not just this one.
- **Through Part 5:** you've built a working data pipeline.

---

## Answers to Part 1

Don't read until you've tried.

**1.** `shape` is an attribute, a stored value. `head()` is a method, it runs and does something. Brackets mean "call this". Writing `players.head` without brackets prints a description of the method rather than running it, which is a common confusion.

**2.** The first raises a `KeyError` whenever the player has no `totalTackle` key, which is most goalkeepers and anyone who didn't make a tackle. The second returns `0` instead. Use `[]` when a missing key means something is broken; use `.get()` when it legitimately might not be there.

**3.** First ten. Last three. The first one on its own (a dict, not a list). Items 11 through 20, because slices include the start and exclude the end.

**4.** It has to persist across every iteration. Move it inside and it resets to empty each time round, so you end up with one item.

**5.** It makes curl_cffi perform the TLS handshake the way Chrome does. Anti-bot systems fingerprint that handshake before any HTTP is sent, so a stock Python client is identifiable and blockable before it says a word. Worth remembering that this particular endpoint turned out not to need it, and that protection is set per route, not per site.

**6.** `rows = []` is inside the loop, so it's wiped on every iteration. It prints `1`, not 245. Same trap as question 4, which is why it's in here twice.
