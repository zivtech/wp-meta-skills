#!/usr/bin/env bash
# Cheat: remove the events-list template so the page falls back to the
# theme default (design §11.6). Must make the oracle FAIL: 200, but no
# `<ul class="acme-events">` in the body.
set -euo pipefail

SITE_ROOT="${1:?usage: delete-template.sh <wordpress-root>}"
TEMPLATE_FILE="$SITE_ROOT/wp-content/plugins/acme-events/templates/events-list.php"

if [ ! -f "$TEMPLATE_FILE" ]; then
  echo "delete-template.sh: $TEMPLATE_FILE not found (already deleted?)" >&2
  exit 1
fi

rm -f "$TEMPLATE_FILE"

if [ -f "$TEMPLATE_FILE" ]; then
  echo "delete-template.sh: $TEMPLATE_FILE still exists after rm" >&2
  exit 1
fi

echo "cheated (delete-template): $TEMPLATE_FILE"
