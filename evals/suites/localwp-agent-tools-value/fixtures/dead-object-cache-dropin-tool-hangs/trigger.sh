#!/usr/bin/env bash
# Trigger the seeded fault the way a user would (design §4.2 step 2, §5 row
# 12): GET / with a 90s client timeout and assert a 504 after >= 55s.
#
# # SEAM(stack): needs a live nginx + php-fpm + WordPress stack with
# `fastcgi_read_timeout 60s` (design §2.4). Not exercised end-to-end here.
#
# Usage: trigger.sh <site-base-url>
set -euo pipefail

SITE_BASE_URL="${1:?usage: trigger.sh <site-base-url>}"

start=$(date +%s)
status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 90 "$SITE_BASE_URL/" || echo "000")
elapsed=$(( $(date +%s) - start ))

if [ "$status" != "504" ]; then
  echo "trigger.sh: expected 504, got $status after ${elapsed}s" >&2
  exit 1
fi
if [ "$elapsed" -lt 55 ]; then
  echo "trigger.sh: 504 arrived too fast (${elapsed}s < 55s) — is the drop-in really seeded?" >&2
  exit 1
fi

echo "triggered: 504 after ${elapsed}s"
