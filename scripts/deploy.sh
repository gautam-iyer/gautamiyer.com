#!/usr/bin/env bash
# Preflight build + deploy. Builds exactly as Cloudflare Pages does; if the build
# errors, it aborts BEFORE pushing (so a broken template never reaches production).
# Usage:  scripts/deploy.sh "commit message"
set -euo pipefail
cd "$(dirname "$0")/.."

echo "▸ Rebuild data/index.json (denormalized collection/place membership)…"
python3 scripts/photos/build_index.py

echo "▸ Preflight build (hugo --gc --minify)…"
rm -rf public
if ! hugo --gc --minify; then
  echo "✘ Build failed — NOT deploying. Fix the error above." >&2
  exit 1
fi

if [ -z "$(git status --porcelain)" ]; then
  echo "Nothing to commit. Working tree clean."
  exit 0
fi

git add -A
git commit -m "${1:-Update site}"
git push origin main
echo "✓ Pushed to main — Cloudflare Pages will build & deploy."
