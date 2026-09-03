#!/usr/bin/env bash
# Reference fix (design §5 row 13): correct the method name typo. Must PASS.
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: reference-fix.sh <wordpress-root>}"
CLASS_FILE="$WORDPRESS_ROOT/wp-content/plugins/acme-forms/includes/class-acme-forms.php"

if [ ! -f "$CLASS_FILE" ]; then
  echo "reference-fix.sh: $CLASS_FILE not found" >&2
  exit 1
fi

perl -pi -e 's/render_feilds\(\)/render_fields()/g' "$CLASS_FILE"

if grep -q "render_feilds" "$CLASS_FILE"; then
  echo "reference-fix.sh: typo still present in $CLASS_FILE" >&2
  exit 1
fi
echo "fixed: $CLASS_FILE"
