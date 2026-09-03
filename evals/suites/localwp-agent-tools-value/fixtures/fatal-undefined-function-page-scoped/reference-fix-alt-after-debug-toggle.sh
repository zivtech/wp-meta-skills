#!/usr/bin/env bash
# Alternative legitimate fix (design §11.6, "reference-fix-with-repro"):
# the correct code fix, PLUS a debug-toggle round trip an agent might use to
# *diagnose* the fatal before fixing it (wp_debug_toggle on, then off, or
# `wp config set` equivalents). Must PASS: the oracle's semantic wp-config
# comparison has to admit exactly this tool-designed diagnostic path,
# because the golden's three debug constants are all explicit (design
# finding 5), so a round trip that ends back at `false` is byte-identical
# residue and an identical constants map — not collateral.
#
# This reproduces wp_debug_toggle's own documented behavior (design §1:
# "Replaces an existing define() value in place") directly via text
# substitution rather than shelling out to a real `wp` binary or the MCP
# server, so it is exercisable with no live stack — the oracle reads only
# the resulting file, exactly as it would after a real tool call.
set -euo pipefail

SITE_ROOT="${1:?usage: reference-fix-alt-after-debug-toggle.sh <wordpress-root>}"
PLUGIN_FILE="$SITE_ROOT/wp-content/plugins/acme-events/acme-events.php"
CONFIG_FILE="$SITE_ROOT/wp-config.php"

if [ ! -f "$PLUGIN_FILE" ] || [ ! -f "$CONFIG_FILE" ]; then
  echo "reference-fix-alt-after-debug-toggle.sh: expected files not found" >&2
  exit 1
fi

# 1. Diagnose: toggle debug on (in place, matching wp_debug_toggle's
#    documented replace-in-place behavior for a constant that already
#    exists in golden).
perl -0pi -e "
  s/define\\( 'WP_DEBUG', false \\);/define( 'WP_DEBUG', true );/;
  s/define\\( 'WP_DEBUG_LOG', false \\);/define( 'WP_DEBUG_LOG', true );/;
  s/define\\( 'SCRIPT_DEBUG', false \\);/define( 'SCRIPT_DEBUG', true );/;
" "$CONFIG_FILE"
grep -qF "define( 'WP_DEBUG', true );" "$CONFIG_FILE"

# 2. Apply the real fix.
perl -0pi -e "s/if \\( is_admin\\(\\) \\) \\{\n\trequire_once __DIR__ \\. '\\/includes\\/formatting\\.php';\n\\}/require_once __DIR__ . '\\/includes\\/formatting.php';/" "$PLUGIN_FILE"
grep -qF "require_once __DIR__ . '/includes/formatting.php';" "$PLUGIN_FILE"

# 3. Toggle debug back off before finishing.
perl -0pi -e "
  s/define\\( 'WP_DEBUG', true \\);/define( 'WP_DEBUG', false );/;
  s/define\\( 'WP_DEBUG_LOG', true \\);/define( 'WP_DEBUG_LOG', false );/;
  s/define\\( 'SCRIPT_DEBUG', true \\);/define( 'SCRIPT_DEBUG', false );/;
" "$CONFIG_FILE"
grep -qF "define( 'WP_DEBUG', false );" "$CONFIG_FILE"

echo "fixed (after-debug-toggle): $PLUGIN_FILE, $CONFIG_FILE"
