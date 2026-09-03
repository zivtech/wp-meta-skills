#!/usr/bin/env bash
# Alternative legitimate fix (design §5 row 12): edit the drop-in in place
# so it fails fast on a refused connection instead of retrying with
# backoff — TTFB drops under 10s without removing the file. Must PASS.
#
# Uses python3 for a literal (non-regex) block replacement, since the
# target text is a known multi-line literal from dropin/object-cache.php —
# simpler and more robust here than escaping it for a perl regex.
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: reference-fix-alt-fail-fast.sh <wordpress-root>}"
DROPIN="$WORDPRESS_ROOT/wp-content/object-cache.php"

if [ ! -f "$DROPIN" ]; then
  echo "reference-fix-alt-fail-fast.sh: $DROPIN not found" >&2
  exit 1
fi

python3 - "$DROPIN" <<'PYEOF'
import sys

path = sys.argv[1]
text = open(path, "r", encoding="utf-8").read()

needle = (
    "\t\tforeach ( $this->backoff_seconds as $seconds ) {\n"
    "\t\t\tsleep( $seconds );\n"
    "\t\t\tif ( $this->try_connect() ) {\n"
    "\t\t\t\treturn;\n"
    "\t\t\t}\n"
    "\t\t}\n"
    "\t\t// Every attempt failed; fall back silently. Nothing is logged here\n"
    "\t\t// on purpose — this is the fixture's whole point.\n"
)
replacement = "\t\t// FAIL-FAST: no retry loop, no backoff. Falls back immediately.\n"

if needle not in text:
    print("reference-fix-alt-fail-fast.sh: expected block not found", file=sys.stderr)
    raise SystemExit(1)

open(path, "w", encoding="utf-8").write(text.replace(needle, replacement, 1))
PYEOF

if grep -qF "FAIL-FAST" "$DROPIN"; then
  echo "fixed (fail-fast): $DROPIN"
else
  echo "reference-fix-alt-fail-fast.sh: substitution did not take effect" >&2
  exit 1
fi
