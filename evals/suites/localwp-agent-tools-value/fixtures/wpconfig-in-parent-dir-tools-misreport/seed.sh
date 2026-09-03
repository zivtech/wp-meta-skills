#!/usr/bin/env bash
# Seed the fault for fixture wpconfig-in-parent-dir-tools-misreport
# (design §5 row 11): insert `define( 'FORCE_SSL_ADMIN', true );` into
# app/wp-config.php (the parent-dir config, NOT app/public/wp-config.php,
# which must not exist). Nothing else changes.
#
# Usage: seed.sh <wordpress-root>
#   <wordpress-root> is app/public; wp-config.php is one level up (app/).
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: seed.sh <wordpress-root>}"
CONFIG_FILE="$(dirname "$WORDPRESS_ROOT")/wp-config.php"
SHADOW_CONFIG="$WORDPRESS_ROOT/wp-config.php"

if [ -f "$SHADOW_CONFIG" ]; then
  echo "seed.sh: $SHADOW_CONFIG must not exist for this fixture (golden invariant violated)" >&2
  exit 1
fi
if [ ! -f "$CONFIG_FILE" ]; then
  echo "seed.sh: $CONFIG_FILE not found" >&2
  exit 1
fi
if grep -qF "FORCE_SSL_ADMIN" "$CONFIG_FILE"; then
  echo "seed.sh: FORCE_SSL_ADMIN already present in $CONFIG_FILE" >&2
  exit 1
fi

perl -pi -e "s/(\\/\\* That's all, stop editing! Happy publishing\\. \\*\\/)/define( 'FORCE_SSL_ADMIN', true );\n\n\$1/" "$CONFIG_FILE"

grep -qF "define( 'FORCE_SSL_ADMIN', true );" "$CONFIG_FILE"
echo "seeded: $CONFIG_FILE"
