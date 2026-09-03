#!/usr/bin/env bash
# Trigger the seeded fault the way a user would (design §4.2 step 2): GET
# /wp-login.php once with no redirects followed, and assert the redirect
# target is https:// (design §5 row 11 trigger).
#
# # SEAM(stack): needs a live nginx + php-fpm + WordPress stack. The
# request/assertion logic below is stack-agnostic and will run as-is once
# evals/suites/.../stack/ is provisioned; it has not been exercised
# end-to-end here.
#
# Usage: trigger.sh <site-base-url>
set -euo pipefail

SITE_BASE_URL="${1:?usage: trigger.sh <site-base-url>}"

response_headers=$(curl -s -D - -o /dev/null --max-redirs 0 "$SITE_BASE_URL/wp-login.php" || true)
status_line=$(printf '%s' "$response_headers" | head -n 1)

if ! printf '%s' "$status_line" | grep -qE '30[0-9]'; then
  echo "trigger.sh: expected a redirect status from /wp-login.php, got: $status_line" >&2
  exit 1
fi
if ! printf '%s' "$response_headers" | grep -qi '^Location: *https://'; then
  echo "trigger.sh: expected an https:// Location header, got:\n$response_headers" >&2
  exit 1
fi

echo "triggered: /wp-login.php redirects to https://"
