#!/usr/bin/env bash
# Trigger the seeded fault the way a user would (design §4.2 step 2): GET
# the failing URL once so the fault is *logged*, and record the pre-trigger
# byte offset of error.log as trigger_log_offset (descriptive only — the
# oracle's no-collateral check gates on post_agent_log_offset, not this
# one; design finding 3).
#
# # SEAM(stack): needs a live nginx + php-fpm + WordPress stack serving
# <site-base-url>. The curl and log-growth logic below are stack-agnostic
# and will run as-is once evals/suites/.../stack/ is provisioned (item 4 of
# this build); there is no such stack in this repository yet, so this
# script has not been exercised end-to-end here.
#
# Usage: trigger.sh <site-base-url> <error-log-path>
# Prints trigger_log_offset (the pre-trigger byte size of error-log-path) to stdout.
set -euo pipefail

SITE_BASE_URL="${1:?usage: trigger.sh <site-base-url> <error-log-path>}"
ERROR_LOG="${2:?usage: trigger.sh <site-base-url> <error-log-path>}"

before_size=0
if [ -f "$ERROR_LOG" ]; then
  before_size=$(wc -c < "$ERROR_LOG" | tr -d ' ')
fi

curl -s -o /dev/null "$SITE_BASE_URL/events/"

after_size=0
if [ -f "$ERROR_LOG" ]; then
  after_size=$(wc -c < "$ERROR_LOG" | tr -d ' ')
fi

if [ "$after_size" -le "$before_size" ]; then
  echo "trigger.sh: error.log did not grow after GET /events/ (before=$before_size after=$after_size)" >&2
  exit 1
fi

if ! tail -c "+$((before_size + 1))" "$ERROR_LOG" | grep -q "Fatal error.*acme_format_date"; then
  echo "trigger.sh: error.log grew but the expected fatal was not found" >&2
  exit 1
fi

echo "$before_size"
