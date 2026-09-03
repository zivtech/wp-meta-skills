#!/usr/bin/env bash
# Seed the fault for fixture fatal-in-error-log-fresh-debug-log-misleads
# (design §5 row 13): rename the `render_fields()` call in the shortcode
# handler to `render_feilds()` (typo) — the class has no such method, so
# calling it fatals with "Call to undefined method Acme_Forms::render_feilds()".
#
# Uses python3 for a literal (non-regex) replacement rather than a perl/bash
# escaping chain — the call site contains a `$` in `$instance`, which is
# fragile to shell-quote correctly for a regex engine and not worth the risk
# for a one-line literal substitution.
#
# Usage: seed.sh <wordpress-root>
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: seed.sh <wordpress-root>}"
CLASS_FILE="$WORDPRESS_ROOT/wp-content/plugins/acme-forms/includes/class-acme-forms.php"

if [ ! -f "$CLASS_FILE" ]; then
  echo "seed.sh: $CLASS_FILE not found" >&2
  exit 1
fi

python3 - "$CLASS_FILE" <<'PYEOF'
import sys

path = sys.argv[1]
text = open(path, "r", encoding="utf-8").read()
needle = "return $instance->render_fields();"
replacement = "return $instance->render_feilds();"
if needle not in text:
    print("seed.sh: golden call site not found (already seeded, or golden drifted)", file=sys.stderr)
    raise SystemExit(1)
open(path, "w", encoding="utf-8").write(text.replace(needle, replacement, 1))
PYEOF

grep -qF 'return $instance->render_feilds();' "$CLASS_FILE"
echo "seeded: $CLASS_FILE"
