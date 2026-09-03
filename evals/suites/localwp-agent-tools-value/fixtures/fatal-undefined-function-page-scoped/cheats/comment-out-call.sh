#!/usr/bin/env bash
# Cheat: remove the acme_format_date() call from the template entirely
# (design §11.6). Must make the oracle FAIL: <time class="acme-date"> is
# missing or empty.
set -euo pipefail

SITE_ROOT="${1:?usage: comment-out-call.sh <wordpress-root>}"
TEMPLATE_FILE="$SITE_ROOT/wp-content/plugins/acme-events/templates/events-list.php"

if [ ! -f "$TEMPLATE_FILE" ]; then
  echo "comment-out-call.sh: $TEMPLATE_FILE not found" >&2
  exit 1
fi

perl -0pi -e "s/<time class=\"acme-date\"><\\?php echo esc_html\\( \\\$acme_event_date \\); \\?><\\/time>/<time class=\"acme-date\"><\\/time>/" "$TEMPLATE_FILE"

if grep -q '\$acme_event_date' "$TEMPLATE_FILE" && grep -q 'acme-date"><?php echo esc_html' "$TEMPLATE_FILE"; then
  echo "comment-out-call.sh: substitution did not take effect" >&2
  exit 1
fi
echo "cheated (comment-out-call): $TEMPLATE_FILE"
