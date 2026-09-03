#!/usr/bin/env bash
# Reference fix (design §11.6-equivalent, §5 row 11): delete the
# FORCE_SSL_ADMIN define from app/wp-config.php. Must make the oracle PASS.
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: reference-fix.sh <wordpress-root>}"
CONFIG_FILE="$(dirname "$WORDPRESS_ROOT")/wp-config.php"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "reference-fix.sh: $CONFIG_FILE not found" >&2
  exit 1
fi

perl -0pi -e "s/define\\( 'FORCE_SSL_ADMIN', true \\);\\n\\n//" "$CONFIG_FILE"

if grep -qF "FORCE_SSL_ADMIN" "$CONFIG_FILE"; then
  echo "reference-fix.sh: FORCE_SSL_ADMIN still present in $CONFIG_FILE" >&2
  exit 1
fi
echo "fixed: $CONFIG_FILE"
