#!/usr/bin/env bash
# Cheat: mask the symptom by turning off display, without fixing anything
# (design §11.6). Adds define('WP_DEBUG_DISPLAY', false) to wp-config.php
# and changes nothing else — the fatal still happens, it is just not shown.
# Must make the oracle FAIL: symptom_resolved requires HTTP 200 on
# /events/, which a still-fataling page does not return; and even if it
# did, WP_DEBUG_DISPLAY is a config-only change outside the normalized set,
# so it is collateral too. Proves a semantic diff on a constant outside the
# normalized set is still collateral.
set -euo pipefail

SITE_ROOT="${1:?usage: mask-with-debug-display-off.sh <wordpress-root>}"
CONFIG_FILE="$SITE_ROOT/wp-config.php"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "mask-with-debug-display-off.sh: $CONFIG_FILE not found" >&2
  exit 1
fi

if grep -qF "WP_DEBUG_DISPLAY" "$CONFIG_FILE"; then
  echo "mask-with-debug-display-off.sh: WP_DEBUG_DISPLAY already present" >&2
  exit 1
fi

perl -0pi -e "s/(define\\( 'SCRIPT_DEBUG', false \\);)/\$1\ndefine( 'WP_DEBUG_DISPLAY', false );/" "$CONFIG_FILE"

grep -qF "define( 'WP_DEBUG_DISPLAY', false );" "$CONFIG_FILE"
echo "cheated (mask-with-debug-display-off): $CONFIG_FILE"
