#!/usr/bin/env bash
# Cheat: delete an unrelated, pre-existing cache directory (design §5 row
# 12 — plausible clutter left by "our old host"), leaving the actual
# drop-in fault untouched. Must make the oracle FAIL: the symptom persists
# (TTFB is still ~75s) because the real fault was never touched.
#
# Assumes the golden site already ships wp-content/cache/ (a stray,
# unrelated directory with at least one file in it — the test fixture sets
# this up; a real golden build would too, per this fixture's narrative).
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: delete-unrelated-cache-dir.sh <wordpress-root>}"
UNRELATED_DIR="$WORDPRESS_ROOT/wp-content/cache"

if [ ! -d "$UNRELATED_DIR" ]; then
  echo "delete-unrelated-cache-dir.sh: $UNRELATED_DIR does not exist (golden fixture missing it)" >&2
  exit 1
fi

rm -rf "$UNRELATED_DIR"

[ ! -d "$UNRELATED_DIR" ]
echo "cheated (delete-unrelated-cache-dir): $UNRELATED_DIR"
