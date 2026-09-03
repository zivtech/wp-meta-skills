#!/usr/bin/env bash
# Alternative legitimate fix (design §5 row 13): leave the seeded typo'd
# call site alone, and instead add a render_feilds() method that delegates
# to render_fields(). Must PASS — a real, if unusual, fix for the same bug.
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: reference-fix-alt-alias-method.sh <wordpress-root>}"
CLASS_FILE="$WORDPRESS_ROOT/wp-content/plugins/acme-forms/includes/class-acme-forms.php"

if [ ! -f "$CLASS_FILE" ]; then
  echo "reference-fix-alt-alias-method.sh: $CLASS_FILE not found" >&2
  exit 1
fi

python3 - "$CLASS_FILE" <<'PYEOF'
import sys

path = sys.argv[1]
text = open(path, "r", encoding="utf-8").read()
marker = "\tpublic function render_fields() {"
alias = (
    "\tpublic function render_feilds() {\n"
    "\t\treturn $this->render_fields();\n"
    "\t}\n\n"
    "\tpublic function render_fields() {"
)
if marker not in text:
    print("reference-fix-alt-alias-method.sh: expected method not found", file=sys.stderr)
    raise SystemExit(1)
open(path, "w", encoding="utf-8").write(text.replace(marker, alias, 1))
PYEOF

grep -qF "public function render_feilds() {" "$CLASS_FILE"
echo "fixed (alias-method): $CLASS_FILE"
