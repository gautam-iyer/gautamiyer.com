#!/usr/bin/env bash
# Upload a SPECIFIC list of derivative paths (relative to .photo-build/derivatives)
# to R2, with retry-once per file (works around wrangler's occasional silent drop
# under parallelism). Usage:  upload_targeted.sh <path-list-file> [bucket]
set -uo pipefail
LIST="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"   # absolutize BEFORE cd
BUCKET="${2:-gautamiyer-photos}"
ROOT="$(cd "$(dirname "$0")/../../.photo-build/derivatives" && pwd)"
cd "$ROOT"

total=$(grep -c . "$LIST")
echo "Uploading $total files to r2://$BUCKET (retry-once) ..."

cat "$LIST" | xargs -P 8 -I{} bash -c '
  f="$1"; bucket="$2"
  case "$f" in
    *.avif) ct=image/avif;;
    *.webp) ct=image/webp;;
    *)      ct=application/octet-stream;;
  esac
  put(){ npx wrangler r2 object put "$bucket/$f" --file="$f" --content-type="$ct" --remote >/dev/null 2>&1; }
  if put || put; then echo "ok $f"; else echo "FAIL $f"; fi
' _ {} "$BUCKET" | tee /tmp/upload_targeted.out | grep -c '^ok' >/dev/null

fails=$(grep -c '^FAIL' /tmp/upload_targeted.out || true)
oks=$(grep -c '^ok' /tmp/upload_targeted.out || true)
echo "done. ok=$oks fail=$fails"
[ "$fails" = "0" ]
