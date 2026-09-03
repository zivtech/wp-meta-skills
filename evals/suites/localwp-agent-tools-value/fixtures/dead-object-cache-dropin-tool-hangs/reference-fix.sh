#!/usr/bin/env bash
# Reference fix (design §5 row 12): delete the dead drop-in. Must PASS.
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: reference-fix.sh <wordpress-root>}"
DROPIN="$WORDPRESS_ROOT/wp-content/object-cache.php"

if [ ! -f "$DROPIN" ]; then
  echo "reference-fix.sh: $DROPIN not found" >&2
  exit 1
fi

rm -f "$DROPIN"
[ ! -f "$DROPIN" ]
echo "fixed (delete): $DROPIN"
