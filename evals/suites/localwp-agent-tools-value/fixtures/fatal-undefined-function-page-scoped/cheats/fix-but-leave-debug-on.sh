#!/usr/bin/env bash
# Cheat: apply the correct code fix, but leave WP_DEBUG true in
# wp-config.php (design §11.6). Must make the oracle FAIL on the semantic
# wp-config comparison — a deliberate correctness bar (metadata.yaml
# allowed_changes.correctness_bar_note): toggling debug to diagnose and
# restoring it passes; leaving it on does not.
set -euo pipefail

SITE_ROOT="${1:?usage: fix-but-leave-debug-on.sh <wordpress-root>}"
PLUGIN_FILE="$SITE_ROOT/wp-content/plugins/acme-events/acme-events.php"
CONFIG_FILE="$SITE_ROOT/wp-config.php"

if [ ! -f "$PLUGIN_FILE" ] || [ ! -f "$CONFIG_FILE" ]; then
  echo "fix-but-leave-debug-on.sh: expected files not found" >&2
  exit 1
fi

perl -0pi -e "s/if \\( is_admin\\(\\) \\) \\{\n\trequire_once __DIR__ \\. '\\/includes\\/formatting\\.php';\n\\}/require_once __DIR__ . '\\/includes\\/formatting.php';/" "$PLUGIN_FILE"
grep -qF "require_once __DIR__ . '/includes/formatting.php';" "$PLUGIN_FILE"

perl -pi -e "s/define\\( 'WP_DEBUG', false \\);/define( 'WP_DEBUG', true );/" "$CONFIG_FILE"
grep -qF "define( 'WP_DEBUG', true );" "$CONFIG_FILE"

echo "cheated (fix-but-leave-debug-on): $PLUGIN_FILE, $CONFIG_FILE"
