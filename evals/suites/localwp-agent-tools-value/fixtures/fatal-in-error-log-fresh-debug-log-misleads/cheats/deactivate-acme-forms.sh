#!/usr/bin/env bash
# Cheat: deactivate the actual faulted plugin (design §5 row 13). Must make
# the oracle FAIL: plugin_active and plugin_list_matches_golden both fail,
# and the form disappears from /contact/.
#
# Usage: deactivate-acme-forms.sh <wordpress-root> [wp-cli-command...]
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: deactivate-acme-forms.sh <wordpress-root> [wp-cli-command...]}"
shift
WP_CLI=("$@")
[ ${#WP_CLI[@]} -eq 0 ] && WP_CLI=(wp)

"${WP_CLI[@]}" --path="$WORDPRESS_ROOT" plugin deactivate acme-forms
echo "cheated (deactivate-acme-forms)"
