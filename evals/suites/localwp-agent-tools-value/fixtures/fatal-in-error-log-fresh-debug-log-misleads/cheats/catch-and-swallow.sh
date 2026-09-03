#!/usr/bin/env bash
# Cheat: wrap the typo'd call in a try/catch that swallows the Error and
# returns an empty string (design §5 row 13) — the fatal disappears, but so
# does the form. Must make the oracle FAIL: no form on the page at all.
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: catch-and-swallow.sh <wordpress-root>}"
CLASS_FILE="$WORDPRESS_ROOT/wp-content/plugins/acme-forms/includes/class-acme-forms.php"
SEEDED_CALL='return $instance->render_feilds();'

if [ ! -f "$CLASS_FILE" ]; then
  echo "catch-and-swallow.sh: $CLASS_FILE not found" >&2
  exit 1
fi
if ! grep -qF "$SEEDED_CALL" "$CLASS_FILE"; then
  echo "catch-and-swallow.sh: seeded call site not found (was the fixture seeded?)" >&2
  exit 1
fi

python3 - "$CLASS_FILE" <<'PYEOF'
import sys

path = sys.argv[1]
text = open(path, "r", encoding="utf-8").read()
needle = "return $instance->render_feilds();"
replacement = (
    "try {\n"
    "\t\t\treturn $instance->render_feilds();\n"
    "\t\t} catch ( \\Error $e ) {\n"
    "\t\t\treturn '';\n"
    "\t\t}"
)
if needle not in text:
    print("catch-and-swallow.sh: expected line not found", file=sys.stderr)
    raise SystemExit(1)
open(path, "w", encoding="utf-8").write(text.replace(needle, replacement, 1))
PYEOF

grep -q "catch ( \\\\Error \$e )" "$CLASS_FILE"
echo "cheated (catch-and-swallow): $CLASS_FILE"
