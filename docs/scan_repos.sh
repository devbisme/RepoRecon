#!/bin/bash

set -e

# Change to the docs directory for all operations
cd "$(dirname "${BASH_SOURCE[0]}")"

# Define paths
VENV_NAME="reporecon"
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
pyenv shell 3.13.14

# Install/upgrade dependencies
echo "Installing dependencies..."
pip install --upgrade pip > /dev/null
pip install -r ../requirements.txt 2>/dev/null || \
    pip install PyGithub loguru requests html-text 2>/dev/null || true

# Run the scan_repos script
echo "Running scan_repos.py with topics.json..."
python scan_repos.py "$TOPICS_FILE" "$@"

# Push results to GitHub
echo "Committing and pushing results to GitHub..."
git add -A
git commit -m "Topic updates."
git push origin master
echo "Successfully pushed updates to GitHub."
