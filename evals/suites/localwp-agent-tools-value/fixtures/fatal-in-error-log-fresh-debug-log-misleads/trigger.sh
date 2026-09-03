#!/usr/bin/env bash
# Trigger the seeded fault the way a user would (design §4.2 step 2, §5 row
# 13): GET /contact/ once, then assert error.log grew with the fatal AND
# that debug.log's mtime ends up newer than error.log's (the trap must be
# armed — design's assert_mtime_order).
#
# # SEAM(stack): needs a live nginx + php-fpm + WordPress stack. Not
# exercised end-to-end here.
#
# Usage: trigger.sh <site-base-url> <error-log-path> <debug-log-path>
set -euo pipefail

SITE_BASE_URL="${1:?usage: trigger.sh <site-base-url> <error-log-path> <debug-log-path>}"
ERROR_LOG="${2:?usage: trigger.sh <site-base-url> <error-log-path> <debug-log-path>}"
DEBUG_LOG="${3:?usage: trigger.sh <site-base-url> <error-log-path> <debug-log-path>}"

before_size=0
[ -f "$ERROR_LOG" ] && before_size=$(wc -c < "$ERROR_LOG" | tr -d ' ')

curl -s -o /dev/null "$SITE_BASE_URL/contact/"

after_size=0
[ -f "$ERROR_LOG" ] && after_size=$(wc -c < "$ERROR_LOG" | tr -d ' ')
if [ "$after_size" -le "$before_size" ]; then
  echo "trigger.sh: error.log did not grow after GET /contact/" >&2
  exit 1
fi
if ! tail -c "+$((before_size + 1))" "$ERROR_LOG" | grep -q "Fatal error.*render_feilds"; then
  echo "trigger.sh: error.log grew but the expected fatal was not found" >&2
  exit 1
fi

error_mtime=$(stat -f '%m' "$ERROR_LOG" 2>/dev/null || stat -c '%Y' "$ERROR_LOG")
debug_mtime=$(stat -f '%m' "$DEBUG_LOG" 2>/dev/null || stat -c '%Y' "$DEBUG_LOG")
if [ "$debug_mtime" -lt "$error_mtime" ]; then
  echo "trigger.sh: debug.log ($debug_mtime) is not newer than error.log ($error_mtime) — trap not armed" >&2
  exit 1
fi

echo "$before_size"
