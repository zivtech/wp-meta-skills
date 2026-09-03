#!/usr/bin/env bash
# Alternative legitimate fix (design §5 row 11): `wp config set
# FORCE_SSL_ADMIN false --raw` — proves WP-CLI resolves the parent-dir
# wp-config.php even though the MCP tool's own read_wp_config/edit_wp_config
# report "not found" for the same file (design's core adversarial point for
# this fixture). Must PASS.
#
# Usage: reference-fix-alt-wp-config-set.sh <wordpress-root> [wp-cli-command...]
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: reference-fix-alt-wp-config-set.sh <wordpress-root> [wp-cli-command...]}"
shift
WP_CLI=("$@")
if [ ${#WP_CLI[@]} -eq 0 ]; then
  WP_CLI=(wp)
fi

"${WP_CLI[@]}" --path="$WORDPRESS_ROOT" config set FORCE_SSL_ADMIN false --raw

echo "fixed (wp-config-set): FORCE_SSL_ADMIN=false via WP-CLI"
