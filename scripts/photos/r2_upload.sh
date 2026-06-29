#!/usr/bin/env bash
# Upload all photo derivatives to the R2 bucket, preserving the <slug>/<file> structure
# so the public URL == photo_base + the manifest's relative tier path.
# Parallel (-P 8) because each `wrangler` invocation pays node startup cost.
# Idempotent in effect: puts overwrite, so re-running is safe (re-uploads everything).
set -uo pipefail

BUCKET="${1:-gautamiyer-photos}"
ROOT="$(cd "$(dirname "$0")/../../.photo-build/derivatives" && pwd)"
cd "$ROOT"

total=$(find . -type f \( -name '*.webp' -o -name '*.avif' \) | wc -l | tr -d ' ')
echo "Uploading $total files to r2://$BUCKET ..."

find . -type f \( -name '*.webp' -o -name '*.avif' \) | sed 's|^\./||' | \
  xargs -P 8 -I{} bash -c '
    f="$1"; bucket="$2"
    case "$f" in
      *.avif) ct=image/avif;;
      *.webp) ct=image/webp;;
      *)      ct=application/octet-stream;;
    esac
    if npx wrangler r2 object put "$bucket/$f" --file="$f" --content-type="$ct" --remote >/dev/null 2>&1; then
      echo "ok $f"
    else
      echo "FAIL $f"
    fi
  ' _ {} "$BUCKET"

echo "done."
