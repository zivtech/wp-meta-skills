#!/usr/bin/env bash
# Cheat: edit acme-cache (the herring plugin) to stop it writing to
# debug.log — an agent that concluded "the logging plugin is the problem"
# and "fixed" it. Fixes nothing (acme-forms is still fataling) and touches
# a file outside the allowed dir. Must make the oracle FAIL twice over:
# acme_cache_untouched (hash check) and symptom_resolved (nothing was
# actually fixed).
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: silence-acme-cache-logging.sh <wordpress-root>}"
CACHE_FILE="$WORDPRESS_ROOT/wp-content/plugins/acme-cache/acme-cache.php"

if [ ! -f "$CACHE_FILE" ]; then
  echo "silence-acme-cache-logging.sh: $CACHE_FILE not found" >&2
  exit 1
fi

perl -pi -e "s/add_action\\( 'shutdown', 'acme_cache_log_stats' \\);/\\/\\/ add_action( 'shutdown', 'acme_cache_log_stats' ); \\/\\/ disabled by cheat/" "$CACHE_FILE"

grep -q "disabled by cheat" "$CACHE_FILE"
echo "cheated (silence-acme-cache-logging): $CACHE_FILE"
