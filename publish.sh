#!/usr/bin/env bash
#
# Publish the reports to GitHub Pages without growing the repo.
#
#     ./publish.sh
#
# The problem this solves: a league report is about 3.5 MB, and committing a
# fresh one every gameweek writes 3.5 MB into git history that can never be
# reclaimed. Six leagues across a season is the better part of a gigabyte of
# history, for files that can be regenerated from the cache in seconds.
#
# So the built site does not live in main's history at all. This script
# force-pushes it to a gh-pages branch as a single commit, replacing whatever
# was there. main keeps only source, and stays small forever.
#
# The force-push is deliberate and safe: everything on gh-pages is generated
# output. Never put anything you cannot rebuild on that branch.

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SRC"

if [ ! -d reports ] || [ -z "$(ls -A reports/*.html 2>/dev/null)" ]; then
  echo "No reports to publish. Build some first:"
  echo "  python run.py --league premier_league --adjust"
  exit 1
fi

REMOTE="$(git remote get-url origin)"
echo "Publishing to ${REMOTE}"

python make_index.py

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

cp index.html "$STAGE"/
cp -R reports "$STAGE"/
# Stops GitHub running the site through Jekyll, which it has no need to do
# and which is the piece that failed during the outage.
touch "$STAGE"/.nojekyll

cd "$STAGE"
git init -q
git checkout -q -b gh-pages
git add -A
git -c user.name="publish.sh" -c user.email="publish@local" \
    commit -q -m "Publish $(date -u '+%Y-%m-%d %H:%M UTC')"
git remote add origin "$REMOTE"
git push -f -q origin gh-pages

COUNT=$(ls reports/*.html | wc -l | tr -d ' ')
SIZE=$(du -sh reports | cut -f1)
echo "Published ${COUNT} report(s), ${SIZE}, to the gh-pages branch."
echo
echo "One-time setup: Settings > Pages > Source: Deploy from a branch"
echo "                Branch: gh-pages   Folder: / (root)"
