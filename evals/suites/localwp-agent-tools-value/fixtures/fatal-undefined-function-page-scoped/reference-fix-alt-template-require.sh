#!/usr/bin/env bash
# Alternative legitimate fix (design §11.6): leave the seeded is_admin()
# guard in acme-events.php in place, and instead require formatting.php
# directly from the template that actually needs it. Must PASS the oracle
# — it is a real, if slightly different, fix for the same bug.
set -euo pipefail

SITE_ROOT="${1:?usage: reference-fix-alt-template-require.sh <wordpress-root>}"
TEMPLATE_FILE="$SITE_ROOT/wp-content/plugins/acme-events/templates/events-list.php"

if [ ! -f "$TEMPLATE_FILE" ]; then
  echo "reference-fix-alt-template-require.sh: $TEMPLATE_FILE not found" >&2
  exit 1
fi

if grep -qF "require_once __DIR__ . '/../includes/formatting.php';" "$TEMPLATE_FILE"; then
  echo "reference-fix-alt-template-require.sh: already applied" >&2
  exit 1
fi

perl -0pi -e "s/defined\\( 'ABSPATH' \\) \\|\\| exit;\\n\\nget_header\\(\\);/defined( 'ABSPATH' ) || exit;\n\nrequire_once __DIR__ . '\\/..\\/includes\\/formatting.php';\n\nget_header();/" "$TEMPLATE_FILE"

grep -qF "require_once __DIR__ . '/../includes/formatting.php';" "$TEMPLATE_FILE"
echo "fixed (template-require): $TEMPLATE_FILE"
