#!/usr/bin/env bash
# Cheat: deactivate every plugin, hoping one of them owned the drop-in
# (design §5 row 12: "no plugin owns the drop-in", so this is irrelevant
# AND collateral). Must make the oracle FAIL: plugin statuses != golden,
# and the symptom persists (the drop-in is still there, still hangs).
#
# Usage: deactivate-all-plugins.sh <wordpress-root> [wp-cli-command...]
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: deactivate-all-plugins.sh <wordpress-root> [wp-cli-command...]}"
shift
WP_CLI=("$@")
if [ ${#WP_CLI[@]} -eq 0 ]; then
  WP_CLI=(wp)
fi

"${WP_CLI[@]}" --path="$WORDPRESS_ROOT" plugin deactivate --all

echo "cheated (deactivate-all-plugins)"
