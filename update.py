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

DEFAULTS = {
    "leagues": ["Premier League", "Championship", "LaLiga", "Serie A",
                "Bundesliga", "Ligue 1"],
    "games": 38,
    "players": True,
    "adjust": True,
    "tiers": True,
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
    """Print and log at once. A scheduled run has nobody watching the terminal."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp}  {message}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def run(command: list[str], dry: bool, allow_fail: bool = False) -> bool:
    """Run a command, log what happened, and say whether it worked."""
    say("  $ " + " ".join(command))
    if dry:
        return True

    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    output = (result.stdout or "") + (result.stderr or "")

    for line in output.strip().splitlines()[-25:]:
        say("    " + line)

    if result.returncode != 0 and not allow_fail:
        say(f"  FAILED with exit code {result.returncode}")
        return False
    return True


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
    args = parser.parse_args()

    # A second run starting while the first is still fetching would fight over
    # the cache and the git index. The lock carries a pid so a stale one from a
    # crashed run can be told apart from a live one.
    if LOCK.exists():
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

        # 1. Fetch and build. Each league is its own report, so one failing
        #    competition does not take the others down with it.
        if args.only_render:
            say("skipping the fetch, --only-render")
        else:
            leagues = settings["leagues"]
            say(f"building {len(leagues)} league(s): {', '.join(leagues)}")

            command = [python, "run.py", "--leagues", ",".join(leagues),
                       "--games", str(settings["games"]), "--no-open"]
            for flag in ("players", "adjust", "tiers"):
                if settings.get(flag):
                    command.append(f"--{flag}")

            if not run(command, args.dry):
                say("build failed, stopping before anything is published")
                say("if the log above shows repeated 403s, SofaScore is refusing:")
                say("  raise delay_min and delay_max in update.json, and build")
                say("  fewer leagues per run. Cached data still works meanwhile.")
                raise SystemExit(1)

        # 2. Re-render, so reports built by older code pick up new page
        #    features. Cheap: the data is already inside each file.
        if not run([python, "rerender.py"], args.dry):
            raise SystemExit(1)

        # 3. Index. Played fixtures come off the front page here.
        index = [python, "make_index.py"]
        if settings.get("prune"):
            index.append("--prune")
        if not run(index, args.dry):
            raise SystemExit(1)

        # 4. Publish. Only if there is something to publish.
        if args.no_push or not settings.get("push"):
            say("not pushing, --no-push")
        elif args.dry:
            say("  $ git add -A && git commit && git push && ./publish.sh")
        elif not git_has_changes():
            say("no source changes to commit, publishing the site anyway")
            run(["./publish.sh"], args.dry)
        else:
            stamp = datetime.now(timezone.utc).strftime("%d %b %Y")
            ok = (run(["git", "add", "-A"], args.dry)
                  and run(["git", "commit", "-m", f"Gameweek update {stamp}"], args.dry)
                  and run(["git", "push"], args.dry))
            if ok:
                run(["./publish.sh"], args.dry)
            else:
                say("git failed, the site was not updated")
                raise SystemExit(1)

        say(f"done in {int(time.time() - started)}s")

    finally:
        if not args.dry and LOCK.exists():
            LOCK.unlink()


if __name__ == "__main__":
    main()
