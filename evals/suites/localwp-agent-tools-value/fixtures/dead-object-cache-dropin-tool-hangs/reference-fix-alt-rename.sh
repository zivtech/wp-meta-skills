#!/usr/bin/env bash
# Alternative legitimate fix (design §5 row 12): rename the drop-in so
# WordPress no longer loads it as object-cache.php, without destroying the
# evidence. Must PASS — allowed_changes.file_may_be_deleted also allows a
# renamed copy, as long as the new name is not itself object-cache.php.
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: reference-fix-alt-rename.sh <wordpress-root>}"
DROPIN="$WORDPRESS_ROOT/wp-content/object-cache.php"
DISABLED="$WORDPRESS_ROOT/wp-content/object-cache.php.disabled"

if [ ! -f "$DROPIN" ]; then
  echo "reference-fix-alt-rename.sh: $DROPIN not found" >&2
  exit 1
fi

mv "$DROPIN" "$DISABLED"
[ ! -f "$DROPIN" ] && [ -f "$DISABLED" ]
echo "fixed (rename): $DISABLED"
