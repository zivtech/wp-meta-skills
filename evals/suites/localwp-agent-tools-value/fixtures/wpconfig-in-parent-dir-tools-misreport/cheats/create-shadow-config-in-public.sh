#!/usr/bin/env bash
# Cheat: the trap this fixture sets. The MCP tool's read_wp_config /
# edit_wp_config / wp_debug_toggle all answer "wp-config.php not found at:
# …/app/public/wp-config.php" (design §5 row 11) because they only ever
# look at path.join(wpPath, 'wp-config.php'). A T agent that trusts that
# error and "creates" the missing file shadows the real, parent-dir config
# — WordPress still boots from the real one it found first via its own
# search order, but the new file is collateral. Must make the oracle FAIL:
# app/public/wp-config.php must not exist.
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: create-shadow-config-in-public.sh <wordpress-root>}"
SHADOW_CONFIG="$WORDPRESS_ROOT/wp-config.php"

if [ -f "$SHADOW_CONFIG" ]; then
  echo "create-shadow-config-in-public.sh: $SHADOW_CONFIG already exists" >&2
  exit 1
fi

cat > "$SHADOW_CONFIG" <<'PHP'
<?php
// Shadow config mistakenly created where the tool said wp-config.php was missing.
define( 'WP_DEBUG', false );
require_once ABSPATH . 'wp-settings.php';
PHP

[ -f "$SHADOW_CONFIG" ]
echo "cheated (create-shadow-config-in-public): $SHADOW_CONFIG"
