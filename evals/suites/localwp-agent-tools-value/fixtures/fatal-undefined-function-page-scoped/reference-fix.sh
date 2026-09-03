#!/usr/bin/env bash
# Reference fix: restore the unconditional require_once (design §11.6).
# Must make the oracle `pass`. This is the fix a correct agent would find
# by reading acme-events.php.
set -euo pipefail

SITE_ROOT="${1:?usage: reference-fix.sh <wordpress-root>}"
PLUGIN_FILE="$SITE_ROOT/wp-content/plugins/acme-events/acme-events.php"

if [ ! -f "$PLUGIN_FILE" ]; then
  echo "reference-fix.sh: $PLUGIN_FILE not found" >&2
  exit 1
fi

perl -0pi -e "s/if \\( is_admin\\(\\) \\) \\{\n\trequire_once __DIR__ \\. '\\/includes\\/formatting\\.php';\n\\}/require_once __DIR__ . '\\/includes\\/formatting.php';/" "$PLUGIN_FILE"

if grep -qF "if ( is_admin() ) {" "$PLUGIN_FILE"; then
  echo "reference-fix.sh: seeded guard is still present in $PLUGIN_FILE" >&2
  exit 1
fi
grep -qF "require_once __DIR__ . '/includes/formatting.php';" "$PLUGIN_FILE"

echo "fixed: $PLUGIN_FILE"
