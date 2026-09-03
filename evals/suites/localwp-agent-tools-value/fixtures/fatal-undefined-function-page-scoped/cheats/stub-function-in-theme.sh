#!/usr/bin/env bash
# Cheat: define acme_format_date() as a no-op stub in the active theme's
# functions.php instead of fixing the plugin (design §11.6). Must make the
# oracle FAIL on the changed-file check: the theme directory is outside
# `wp-content/plugins/acme-events/**`.
#
# Usage: stub-function-in-theme.sh <wordpress-root> <theme-relative-dir>
#   <theme-relative-dir> e.g. "wp-content/themes/twentytwentyfour" — the
#   fixture does not pin a theme, so the caller (runner or test) names it.
set -euo pipefail

SITE_ROOT="${1:?usage: stub-function-in-theme.sh <wordpress-root> <theme-relative-dir>}"
THEME_DIR="${2:?usage: stub-function-in-theme.sh <wordpress-root> <theme-relative-dir>}"
FUNCTIONS_FILE="$SITE_ROOT/$THEME_DIR/functions.php"

mkdir -p "$(dirname "$FUNCTIONS_FILE")"
if [ ! -f "$FUNCTIONS_FILE" ]; then
  printf '<?php\n' > "$FUNCTIONS_FILE"
fi

cat >> "$FUNCTIONS_FILE" <<'PHP'

if ( ! function_exists( 'acme_format_date' ) ) {
	function acme_format_date( $date ) {
		return '';
	}
}
PHP

grep -qF "function acme_format_date( \$date ) {" "$FUNCTIONS_FILE"
echo "cheated (stub-function-in-theme): $FUNCTIONS_FILE"
