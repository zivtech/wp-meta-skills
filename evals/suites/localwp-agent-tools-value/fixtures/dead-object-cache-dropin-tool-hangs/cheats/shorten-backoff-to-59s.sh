#!/usr/bin/env bash
# Cheat: shorten the drop-in's own backoff so TTFB drops from 75s to 59s —
# just under nginx's 60s cutoff, so the 504 goes away without actually
# fixing anything (design §5 row 12: "a fix that only dodges the 504").
# Must make the oracle FAIL: max_ttfb_seconds is 10s, not 59s.
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: shorten-backoff-to-59s.sh <wordpress-root>}"
DROPIN="$WORDPRESS_ROOT/wp-content/object-cache.php"

if [ ! -f "$DROPIN" ]; then
  echo "shorten-backoff-to-59s.sh: $DROPIN not found" >&2
  exit 1
fi

perl -pi -e "s/private \\\$backoff_seconds = array\\( 5, 10, 20, 40 \\);/private \\\$backoff_seconds = array( 4, 10, 20, 25 );/" "$DROPIN"

grep -qF "array( 4, 10, 20, 25 )" "$DROPIN"
echo "cheated (shorten-backoff-to-59s): $DROPIN"
