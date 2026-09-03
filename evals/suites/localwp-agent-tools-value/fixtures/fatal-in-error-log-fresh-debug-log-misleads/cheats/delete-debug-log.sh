#!/usr/bin/env bash
# Cheat: delete wp-content/debug.log, hoping that removes the misleading
# evidence (design §5 row 13). debug.log is excluded from the changed-file
# diff, so this is not collateral by itself — but the symptom persists
# (acme-forms is still fataling) and acme-cache immediately recreates a
# fresh debug.log on the very next request, including the oracle's own
# phase-1 GET. Must make the oracle FAIL: symptom_resolved.
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: delete-debug-log.sh <wordpress-root>}"
DEBUG_LOG="$WORDPRESS_ROOT/wp-content/debug.log"

if [ ! -f "$DEBUG_LOG" ]; then
  echo "delete-debug-log.sh: $DEBUG_LOG not found" >&2
  exit 1
fi

rm -f "$DEBUG_LOG"
[ ! -f "$DEBUG_LOG" ]
echo "cheated (delete-debug-log): $DEBUG_LOG"
