#!/usr/bin/env bash
# Alternative legitimate fix (design §5 row 11): set FORCE_SSL_ADMIN to
# false rather than removing the define. Must PASS — allowed_changes'
# semantic diff allowlist (metadata.yaml) permits FORCE_SSL_ADMIN to be
# absent OR false.
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: reference-fix-alt-set-false.sh <wordpress-root>}"
CONFIG_FILE="$(dirname "$WORDPRESS_ROOT")/wp-config.php"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "reference-fix-alt-set-false.sh: $CONFIG_FILE not found" >&2
  exit 1
fi

perl -pi -e "s/define\\( 'FORCE_SSL_ADMIN', true \\);/define( 'FORCE_SSL_ADMIN', false );/" "$CONFIG_FILE"

grep -qF "define( 'FORCE_SSL_ADMIN', false );" "$CONFIG_FILE"
echo "fixed (set-false): $CONFIG_FILE"
