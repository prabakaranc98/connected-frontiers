#!/usr/bin/env bash
# Deploy the public explorer to GitHub Pages (branch gh-pages).
# gh-pages is replaced by a single orphan commit each time, so large snapshots never accumulate in history.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
uv run cf site "$@"
ORIGIN="$(git remote get-url origin)"
KB="$(cat data/kb/CURRENT)"
TMP="$(mktemp -d)"
cp -R data/site/. "$TMP"
cd "$TMP"
git init -q -b gh-pages
git add -A
git commit -q -m "Deploy explorer · KB ${KB}

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -q -f "$ORIGIN" gh-pages
echo "pushed gh-pages (KB ${KB})"
rm -rf "$TMP"
