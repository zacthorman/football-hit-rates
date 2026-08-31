"""
One command that does the whole gameweek: fetch, rebuild, publish.

    python update.py                 # the lot
    python update.py --dry-run       # say what it would do, touch nothing
    python update.py --no-push       # build locally, do not touch git
    python update.py --only-render   # skip fetching, just rebuild the pages

Meant to be run on a schedule. What it does, in order:

    1. Build each league listed in update.json
    2. Re-render every existing report, so old files pick up new page code
    3. Rebuild the index and drop fixtures that have kicked off
    4. Commit, push, and publish to GitHub Pages

Every step is checked before the next one runs. A failed fetch must not lead
to a published site, because a half-built report looks exactly like a working
one and you would bet off it.

Why this runs on your Mac and not in the cloud: SofaScore is behind Cloudflare,
which is far more suspicious of datacentre IPs than of home broadband. A
scheduled runner on GitHub or any cloud box is likely to be served 403s
forever, and the failure is silent enough to look like "no fixtures this week".
Your own connection already works, so it stays there.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG = ROOT / "update.json"
LOG = ROOT / "update.log"
LOCK = ROOT / ".update.lock"
STATUS = ROOT / ".last_run.json"

# A run is considered overdue after this long. Daily job, so a day and a half
# allows for one missed morning without crying wolf.
STALE_HOURS = 36

DEFAULTS = {
    "leagues": ["Premier League", "Championship", "La Liga", "Serie A",
                "Bundesliga", "Ligue 1"],
    "games": 38,
    "players": True,
    "adjust": True,
    "tiers": True,
    # Without this run.py never fetches previous meetings, DATA.h2h stays
    # empty, and the report disables its own Head to head button. The feature
    # was built and then never switched on.
    "h2h": True,
    # Off by default. It back-fills a new signing's record from his previous
    # club, which costs up to about forty extra requests per fixture, and it
    # is a garnish rather than something the site needs to be correct.
    "newsignings": False,
    # One request per fixture, about ninety a run, five to ten minutes. It
    # buys the official's name and his card rate, which is shown and never
    # priced. Cheap enough to leave on.
    "referee": True,
    "prune": True,
    "push": True,
    # Slower than an interactive run on purpose. Nobody is waiting for this
    # one, and a job that trickles is a job nobody has any reason to block.
    "delay_min": 3.0,
    "delay_max": 6.0,
}


def load_config() -> dict:
    """Settings, with a file written on first run so there is one to edit."""
    if not CONFIG.exists():
        CONFIG.write_text(json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8")
        say(f"wrote {CONFIG.name} with defaults, edit it to change what gets built")
        return dict(DEFAULTS)

    try:
        settings = dict(DEFAULTS)
        settings.update(json.loads(CONFIG.read_text(encoding="utf-8")))
        return settings
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{CONFIG.name} is not valid JSON: {exc}")


def say(message: str) -> None:
    """Print and log at once. A scheduled run has nobody watching the terminal.

    Local time with the offset, not bare UTC. A log stamped 21:02 next to a
    terminal showing 22:02 reads as an hour of silence, and an hour of silence
    on a job like this reads as a hang. It cost a round of debugging once
    already, on a job that was working perfectly.
    """
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    line = f"{stamp}  {message}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def fail(message: str) -> None:
    """Record the failure, push a notification, and stop.

    Every failure path goes through here so none of them can forget to do one
    of the three things. A run that dies without recording it looks identical
    to a run that never started.
    """
    write_status(False, message)
    notify("Football stats update failed", message)
    raise SystemExit(1)


def notify(title: str, message: str) -> None:
    """A macOS notification, best effort.

    This is the point of the whole status mechanism. A scheduled job that
    fails quietly is worse than no job at all, because you carry on trusting
    a site that stopped updating on Tuesday. Pushing the failure at you beats
    remembering to go and look for it.
    """
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification {json.dumps(message)} with title {json.dumps(title)}'],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass          # not a Mac, or notifications are off. Never fatal.


def write_status(ok: bool, message: str) -> None:
    STATUS.write_text(json.dumps({
        "finished": time.time(),
        "when": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "ok": ok,
        "message": message,
    }, indent=2) + "\n", encoding="utf-8")


def show_status() -> None:
    """One screen that answers: is this thing still working?"""
    if not STATUS.exists():
        print("No run has finished yet.")
        return

    data = json.loads(STATUS.read_text(encoding="utf-8"))
    age_hours = (time.time() - data["finished"]) / 3600

    print(f"last run    {data['when']}")
    print(f"            {age_hours:.1f} hours ago")
    print(f"outcome     {'OK' if data['ok'] else 'FAILED'}  {data['message']}")

    if not data["ok"]:
        print("\n  The last run failed and the site was not updated.")
        print("  Look at the end of update.log for the reason.")
    elif age_hours > STALE_HOURS:
        print(f"\n  Nothing has run for {age_hours:.0f} hours, which is too long.")
        print("  Check the schedule is still loaded:")
        print("    launchctl list | grep football")
    else:
        print("\n  Healthy.")

    if LOCK.exists():
        print(f"\n  A run is in progress (pid {LOCK.read_text().strip()}).")


def run(command: list[str], dry: bool, allow_fail: bool = False) -> bool:
    """Run a command, streaming its output into the log as it happens.

    Streaming rather than capturing, which is how this was written first. A
    captured run writes nothing until the command exits, so a three hour fetch
    produced a log that sat frozen on its first line the entire time and gave
    no way to tell a working job from a hung one. For anything that runs
    longer than a few seconds that is the difference between a log and no log.

    PYTHONUNBUFFERED is set for the same reason: without it Python buffers its
    own stdout when it is writing to a pipe rather than a terminal, and the
    output arrives in 8KB lumps regardless of what this function does.
    """
    say("  $ " + " ".join(command))
    if dry:
        return True

    env = dict(os.environ, PYTHONUNBUFFERED="1")
    process = subprocess.Popen(
        command, cwd=ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=1,
    )

    # run.py rewrites its progress counter with \r rather than newlines, which
    # would otherwise arrive as one enormous line. Split on both.
    for raw in process.stdout:
        for line in raw.replace("\r", "\n").splitlines():
            if line.strip():
                say("    " + line.rstrip())

    process.wait()

    if process.returncode != 0 and not allow_fail:
        say(f"  FAILED with exit code {process.returncode}")
        return False
    return True


def run_with_retries(command: list[str], dry: bool,
                     tries: int = 3, delay: int = 15) -> bool:
    """Run a command that needs the network, retrying with backoff.

    Only for steps that are safe to repeat. A push either fails again or lands
    the same commit, so it qualifies; a fetch or a build does not go through
    here because repeating those costs hours.
    """
    for attempt in range(1, tries + 1):
        if run(command, dry):
            return True
        if attempt == tries:
            return False
        say(f"  that step needs the network, retrying in {delay}s "
            f"(attempt {attempt} of {tries})")
        time.sleep(delay)
        delay *= 2
    return False


def python_exe() -> str:
    """The interpreter running this file.

    Uses sys.executable rather than the string "python" on purpose. Under a
    scheduler there is no shell profile and no activated virtualenv, so a bare
    "python" is either missing or the wrong one, and the whole job dies with
    ModuleNotFoundError on curl_cffi.
    """
    return sys.executable


def git_has_changes() -> bool:
    result = subprocess.run(["git", "status", "--porcelain"],
                            cwd=ROOT, capture_output=True, text=True)
    return bool(result.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", dest="dry",
                        help="print the plan, change nothing")
    parser.add_argument("--no-push", action="store_true", dest="no_push",
                        help="build locally, leave git alone")
    parser.add_argument("--only-render", action="store_true", dest="only_render",
                        help="skip fetching, just rebuild pages and index")
    parser.add_argument("--status", action="store_true",
                        help="say whether the last run worked, and when it was")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    # A second run starting while the first is still fetching would fight over
    # the cache and the git index. The lock carries a pid so a stale one from a
    # crashed run can be told apart from a live one.
    #
    # A dry run is exempt: it writes nothing, so refusing to let you look at
    # the plan while a real run is going is just unhelpful.
    if LOCK.exists() and args.dry:
        say("note: a real run is in progress, this dry run changes nothing")
    elif LOCK.exists():
        try:
            pid = int(LOCK.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            raise SystemExit(f"Already running as pid {pid}. Delete {LOCK.name} if that is wrong.")
        except (ValueError, ProcessLookupError):
            say("clearing a stale lock from a run that did not finish")
        except PermissionError:
            raise SystemExit("Already running under another user.")

    if not args.dry:
        LOCK.write_text(str(os.getpid()), encoding="utf-8")

    started = time.time()
    settings = load_config()
    python = python_exe()

    # Passed through the environment rather than as flags, so it applies to
    # every script this launches without each of them needing an option.
    env_note = f"{settings['delay_min']} to {settings['delay_max']}s between fetches"
    os.environ["SOFA_DELAY_MIN"] = str(settings["delay_min"])
    os.environ["SOFA_DELAY_MAX"] = str(settings["delay_max"])

    try:
        say("=" * 62)
        say(f"update starting, python {python}")
        say(f"pacing: {env_note}")

        resume_publish = False
        if STATUS.exists():
            previous = json.loads(STATUS.read_text(encoding="utf-8"))
            gap = (time.time() - previous["finished"]) / 3600
            if not previous["ok"]:
                say(f"note: the previous run failed ({previous['message']})")
                # Only the two push failures leave a complete set of reports
                # on disk. Matched from the start of the message on purpose:
                # "the league build failed, nothing was published" contains the
                # word publish too, and half a report must never reach the site.
                if previous["message"].startswith(
                        ("publish.sh failed", "git failed")):
                    resume_publish = True
            if gap > STALE_HOURS:
                say(f"note: nothing has run for {gap:.0f} hours")

        # 0. Publish what is already on disk, before rebuilding anything.
        #
        #    A run that built every report and then lost the push has hours of
        #    finished work sitting in reports/, and the old behaviour threw it
        #    away and started the fetch from scratch, leaving the site a further
        #    day behind. Yesterday's reports beat no reports.
        #
        #    Not fatal if it fails. The normal publish at the end gets its own
        #    attempt with fresher data.
        if (resume_publish and not args.dry and not args.no_push
                and settings.get("push")):
            stale = sorted((ROOT / "reports").glob("*.html"))
            if stale:
                say(f"the previous run built {len(stale)} report(s) and never "
                    "published them, pushing those first")
                if run(["./publish.sh"], args.dry):
                    say("recovered, the site is serving the previous run's reports")
                else:
                    say("could not publish those, carrying on with the rebuild")

        # 1. Fetch and build. Each league is its own report, so one failing
        #    competition does not take the others down with it.
        if args.only_render:
            say("skipping the fetch, --only-render")
        else:
            leagues = settings["leagues"]
            say(f"building {len(leagues)} league(s): {', '.join(leagues)}")

            command = [python, "run.py", "--leagues", ",".join(leagues),
                       "--games", str(settings["games"]), "--no-open"]
            for flag in ("players", "adjust", "tiers", "h2h", "newsignings",
                         "referee"):
                if settings.get(flag):
                    command.append(f"--{flag}")

            if not run(command, args.dry):
                say("build failed, stopping before anything is published")
                say("if the log above shows repeated 403s, SofaScore is refusing:")
                say("  raise delay_min and delay_max in update.json, and build")
                say("  fewer leagues per run. Cached data still works meanwhile.")
                fail("the league build failed, nothing was published")

        # 2. Re-render, so reports built by older code pick up new page
        #    features. Cheap: the data is already inside each file.
        if not run([python, "rerender.py"], args.dry):
            fail("re-rendering the reports failed")

        # 3. Index. Played fixtures come off the front page here.
        index = [python, "make_index.py"]
        if settings.get("prune"):
            index.append("--prune")
        if not run(index, args.dry):
            fail("rebuilding the index failed")

        # 4. Publish. Only if there is something to publish.
        if args.no_push or not settings.get("push"):
            say("not pushing, --no-push")
        elif args.dry:
            say("  $ git add -A && git commit && git push && ./publish.sh")
        elif not git_has_changes():
            say("no source changes to commit, publishing the site anyway")
            if not run(["./publish.sh"], args.dry):
                fail("publish.sh failed, the site was not updated")
        else:
            stamp = datetime.now(timezone.utc).strftime("%d %b %Y")
            ok = (run(["git", "add", "-A"], args.dry)
                  and run(["git", "commit", "-m", f"Gameweek update {stamp}"], args.dry)
                  and run_with_retries(["git", "push"], args.dry))
            if not ok:
                fail("git failed, the site was not updated")
            # Checked like every other step. This was the one place the return
            # value was thrown away, so a failed publish logged "done" and the
            # site quietly stayed a day behind.
            if not run(["./publish.sh"], args.dry):
                fail("publish.sh failed, the site was not updated")

        elapsed = int(time.time() - started)
        say(f"done in {elapsed}s")
        if not args.dry:
            write_status(True, f"completed in {elapsed}s")

    finally:
        if not args.dry and LOCK.exists():
            LOCK.unlink()


if __name__ == "__main__":
    main()
