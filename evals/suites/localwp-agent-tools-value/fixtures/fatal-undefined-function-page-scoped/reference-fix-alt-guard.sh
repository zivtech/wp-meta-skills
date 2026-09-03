#!/usr/bin/env bash
# Alternative legitimate fix (design §11.6): guard the require with
# function_exists so it always loads formatting.php regardless of context,
# without touching the is_admin() conditional itself. Must PASS.
set -euo pipefail

SITE_ROOT="${1:?usage: reference-fix-alt-guard.sh <wordpress-root>}"
PLUGIN_FILE="$SITE_ROOT/wp-content/plugins/acme-events/acme-events.php"

if [ ! -f "$PLUGIN_FILE" ]; then
  echo "reference-fix-alt-guard.sh: $PLUGIN_FILE not found" >&2
  exit 1
fi

perl -0pi -e "s/if \\( is_admin\\(\\) \\) \\{\n\trequire_once __DIR__ \\. '\\/includes\\/formatting\\.php';\n\\}/if ( ! function_exists( 'acme_format_date' ) ) {\n\trequire_once __DIR__ . '\\/includes\\/formatting.php';\n}/" "$PLUGIN_FILE"

grep -qF "if ( ! function_exists( 'acme_format_date' ) ) {" "$PLUGIN_FILE"
echo "fixed (guard): $PLUGIN_FILE"
