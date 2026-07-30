#!/bin/bash
source ~/.profile
source ~/.bashrc

set -e

# Output the time and date.
date

# Change to the docs directory for all operations
cd "$(dirname "${BASH_SOURCE[0]}")"

# Define paths
TOPICS_FILE="topics.json"

# Check if topics.json exists
if [ ! -f "$TOPICS_FILE" ]; then
    echo "Error: topics.json not found in current directory"
    exit 1
fi

# Set Python version to 3.13 using pyenv
echo "Setting Python version to 3.13 with pyenv..."
eval "$(pyenv init --path)"
eval "$(pyenv init -)"
pyenv shell 3.13

# Install/upgrade dependencies
echo "Installing dependencies..."
pip install --upgrade pip > /dev/null
pip install -r ../requirements.txt 2>/dev/null || \
    pip install PyGithub loguru requests html-text 2>/dev/null || true

# Run the scan_repos script
echo "Running scan_repos.py with topics.json..."
python scan_repos.py "$TOPICS_FILE" "$@"

# Push results to GitHub.
#
# The scan output is deliberately NOT committed to master. It is ~100 MB of
# regenerated, near-incompressible JSON per run, and committing it is what grew
# .git to 19 GB. publish.sh rebuilds the gh-pages branch as a single parentless
# commit instead, so the published history is never more than one snapshot deep.
REPO_ROOT="$(git rev-parse --show-toplevel)"

# Commit source changes only. The generated JSON is gitignored, so this picks up
# real edits (a hand-tweaked topics.json, code changes) and nothing else.
if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
    echo "Committing source changes to master..."
    git -C "$REPO_ROOT" add -A
    git -C "$REPO_ROOT" commit -m "Topic updates."
    git -C "$REPO_ROOT" push origin master
else
    echo "No source changes to commit."
fi

# Publish the freshly generated scan output to the branch GitHub Pages serves.
echo "Publishing site to gh-pages..."
"$REPO_ROOT/publish.sh"
echo "Successfully published updates to GitHub."
