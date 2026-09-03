#!/usr/bin/env bash
# Seed the fault for fixture dead-object-cache-dropin-tool-hangs (design §5
# row 12): install the stale object-cache.php drop-in. Nothing else changes
# — no plugin owns it, no wp-config constant references it.
#
# Usage: seed.sh <wordpress-root>
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: seed.sh <wordpress-root>}"
DROPIN_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/dropin/object-cache.php"
DROPIN_TARGET="$WORDPRESS_ROOT/wp-content/object-cache.php"

if [ -f "$DROPIN_TARGET" ]; then
  echo "seed.sh: $DROPIN_TARGET already exists" >&2
  exit 1
fi

mkdir -p "$(dirname "$DROPIN_TARGET")"
cp "$DROPIN_SOURCE" "$DROPIN_TARGET"

[ -f "$DROPIN_TARGET" ]
echo "seeded: $DROPIN_TARGET"
