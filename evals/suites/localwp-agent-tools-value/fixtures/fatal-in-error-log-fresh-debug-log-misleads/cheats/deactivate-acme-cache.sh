#!/usr/bin/env bash
# Cheat: deactivate the herring plugin instead of fixing acme-forms
# (design §5 row 13). Must make the oracle FAIL: plugin_list_matches_golden
# (acme-cache's status changed) — and the real symptom is untouched.
#
# Usage: deactivate-acme-cache.sh <wordpress-root> [wp-cli-command...]
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: deactivate-acme-cache.sh <wordpress-root> [wp-cli-command...]}"
shift
WP_CLI=("$@")
[ ${#WP_CLI[@]} -eq 0 ] && WP_CLI=(wp)

"${WP_CLI[@]}" --path="$WORDPRESS_ROOT" plugin deactivate acme-cache
echo "cheated (deactivate-acme-cache)"
