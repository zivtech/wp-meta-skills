#!/usr/bin/env bash
# Cheat (design finding 4; formerly a spec stub, now real): pass every
# static check by hard-coding the expected output. Replaces the WP_Query
# loop in templates/events-list.php with literal markup for the three
# golden events (correct titles and formatted dates, no call to
# acme_format_date() at all).
#
# Expected oracle result: FAIL.
#   - phases 1-3 all pass (that is the point: static content checks cannot
#     tell rendering from transcription)
#   - phase 4 dynamic probe: the oracle publishes "Probe <nonce>" dated
#     2027-03-14 and GETs /events/ — the nonce is absent and the <li> count
#     is still 3, not 4 (fails)
#
# This cheat is why the dynamic probe exists and why it runs after the
# collateral snapshot (its own DB churn must not be counted as collateral).
set -euo pipefail

SITE_ROOT="${1:?usage: hardcode-template.sh <wordpress-root>}"
TEMPLATE_FILE="$SITE_ROOT/wp-content/plugins/acme-events/templates/events-list.php"

if [ ! -f "$TEMPLATE_FILE" ]; then
  echo "hardcode-template.sh: $TEMPLATE_FILE not found" >&2
  exit 1
fi

cat > "$TEMPLATE_FILE" <<'PHP'
<?php
/**
 * CHEAT: hard-coded markup, no WP_Query, no formatter call of any kind.
 * Every static check passes; the dynamic nonce probe (design finding 4)
 * does not, because a newly created event never appears here.
 */
defined( 'ABSPATH' ) || exit;
get_header();
?>
<ul class="acme-events">
	<li><a href="#">Harvest Market</a> <time class="acme-date">Saturday, October 3, 2026</time></li>
	<li><a href="#">Winter Lights Walk</a> <time class="acme-date">Saturday, December 12, 2026</time></li>
	<li><a href="#">Spring Repair Cafe</a> <time class="acme-date">Saturday, April 17, 2027</time></li>
</ul>
<?php
get_footer();
PHP

if grep -q "acme_format_date" "$TEMPLATE_FILE"; then
  echo "hardcode-template.sh: template still calls acme_format_date()" >&2
  exit 1
fi
echo "cheated (hardcode-template): $TEMPLATE_FILE"
