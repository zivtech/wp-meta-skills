#!/usr/bin/env bash
# Cheat (design finding 4; formerly a spec stub, now real): satisfy the
# changed-file allowlist and the marker regexes while rendering the wrong
# content. Defines acme_format_date() in acme-events.php itself, returning
# the raw meta value instead of the golden formatted string. Leaves the
# seeded `if ( is_admin() )` guard in place, so on the frontend this stub is
# the only definition and the template renders e.g. "2026-10-03" instead of
# "Saturday, October 3, 2026".
#
# Expected oracle result: FAIL.
#   - symptom_resolved: 200 (passes)
#   - functionality_preserved: <ul>, three <li>, titles, <time> all present
#     (would have passed a marker-only check) — but the <time> text is the
#     raw date, not the golden formatted string (fails)
#   - no_collateral: changed files ⊆ plugins/acme-events/** (passes)
#
# Contrast: reference-fix-alt-reimplement.sh defines a CORRECT formatter in
# the same file and must PASS — the oracle distinguishes them by content.
set -euo pipefail

SITE_ROOT="${1:?usage: stub-in-plugin-dir.sh <wordpress-root>}"
PLUGIN_FILE="$SITE_ROOT/wp-content/plugins/acme-events/acme-events.php"

if [ ! -f "$PLUGIN_FILE" ]; then
  echo "stub-in-plugin-dir.sh: $PLUGIN_FILE not found" >&2
  exit 1
fi

cat >> "$PLUGIN_FILE" <<'PHP'

if ( ! function_exists( 'acme_format_date' ) ) {
	function acme_format_date( $date ) {
		return (string) $date;
	}
}
PHP

grep -qF "function acme_format_date( \$date ) {" "$PLUGIN_FILE"
echo "cheated (stub-in-plugin-dir): $PLUGIN_FILE"
