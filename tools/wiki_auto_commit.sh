#!/usr/bin/env bash
# Auto-commit wiki changes daily
set -e

cd /home/bog/wiki-seo || exit 0

# Check if there are changes
if ! git status --porcelain | grep -q .; then
    exit 0  # No changes, silent exit
fi

# Count changes
CHANGES=$(git status --porcelain | wc -l)
FILES=$(git status --porcelain | awk '{print $NF}' | tr '\n' ', ')

# Commit and push
git add -A
git commit -m "auto(wiki): daily commit — $(date +%Y-%m-%d)

Files changed: $FILES"
git push origin main 2>/dev/null

echo "✅ Auto-committed $CHANGES changed files to wiki"
