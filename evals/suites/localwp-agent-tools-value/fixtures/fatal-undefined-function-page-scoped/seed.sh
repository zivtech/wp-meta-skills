#!/usr/bin/env bash
# Seed the fault for fixture fatal-undefined-function-page-scoped (design §11.3).
#
# Golden acme-events.php requires includes/formatting.php unconditionally.
# This seed rewraps that require so it only runs on admin requests, which
# fatals the frontend template's call to acme_format_date() on /events/.
# Nothing else in the site changes (design §11.3 step 2).
#
# Usage: seed.sh <wordpress-root>
#   <wordpress-root>  path whose wp-content/plugins/acme-events/ holds a
#                      copy of this fixture's golden plugin source (e.g.
#                      app/public on the Lane H stack, or a temp dir in
#                      tests).
set -euo pipefail

SITE_ROOT="${1:?usage: seed.sh <wordpress-root>}"
PLUGIN_FILE="$SITE_ROOT/wp-content/plugins/acme-events/acme-events.php"
GOLDEN_LINE="require_once __DIR__ . '/includes/formatting.php';"

if [ ! -f "$PLUGIN_FILE" ]; then
  echo "seed.sh: $PLUGIN_FILE not found" >&2
  exit 1
fi

if ! grep -qF "$GOLDEN_LINE" "$PLUGIN_FILE"; then
  echo "seed.sh: golden require_once line not found in $PLUGIN_FILE (already seeded, or golden drifted)" >&2
  exit 1
fi

perl -0pi -e "s/\\Qrequire_once __DIR__ . '\\/includes\\/formatting.php';\\E/if ( is_admin() ) {\n\trequire_once __DIR__ . '\\/includes\\/formatting.php';\n}/" "$PLUGIN_FILE"

if ! grep -qF "if ( is_admin() ) {" "$PLUGIN_FILE"; then
  echo "seed.sh: substitution did not take effect in $PLUGIN_FILE" >&2
  exit 1
fi

echo "seeded: $PLUGIN_FILE"
