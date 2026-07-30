#!/usr/bin/env bash
#
# Publish docs/ to the gh-pages branch as a single parentless commit.
#
# The branch is destroyed and rebuilt on every run, so its history is always
# exactly one commit deep. That is the point: the scan regenerates ~100 MB of
# near-incompressible JSON each time, and committing that onto a normal branch
# is what grew .git to 19 GB.
#
# Nothing here touches the working tree, the index, or HEAD -- the commit is
# assembled off to the side with a scratch index.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

BRANCH=gh-pages

STAGE=$(mktemp -d)
IDX=$(mktemp -u)                  # index must live outside STAGE or it gets committed
trap 'rm -rf "$STAGE" "$IDX"' EXIT

# Site assets, flattened to the branch root.
cp docs/index.html docs/app.js docs/styles.css "$STAGE"/
cp docs/favicon.ico docs/favicon16.png docs/favicon32.png docs/favicon48.png \
   docs/logo.png docs/logo.svg docs/info.png docs/loading51.gif "$STAGE"/

# Generated scan results, plus topics.json (config, but app.js fetches it too).
cp docs/*.json "$STAGE"/

touch "$STAGE/.nojekyll"

# Hash the payload into a tree without disturbing the real index.
GIT_INDEX_FILE="$IDX" git --work-tree="$STAGE" add -A
TREE=$(GIT_INDEX_FILE="$IDX" git write-tree)

# No -p, so the commit has no parent and carries no history.
COMMIT=$(git commit-tree "$TREE" -m "Publish site $(date -u +%Y-%m-%dT%H:%M:%SZ)")

git update-ref "refs/heads/$BRANCH" "$COMMIT"
git push --force origin "$BRANCH"

echo "Published $(du -sh "$STAGE" | cut -f1) to $BRANCH ($COMMIT)"
