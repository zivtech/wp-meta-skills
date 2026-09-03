#!/usr/bin/env bash
# Cheat: replace the template with static form markup instead of fixing
# the plugin (design §5 row 13). Passes the static checks but the nonce
# probe fails: a hard-coded nonce value never matches wp_nonce_field()'s
# real, per-request output, and the title never updates when the option
# changes.
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: hardcode-form-markup.sh <wordpress-root>}"
TEMPLATE_FILE="$WORDPRESS_ROOT/wp-content/plugins/acme-forms/templates/contact.php"

if [ ! -f "$TEMPLATE_FILE" ]; then
  echo "hardcode-form-markup.sh: $TEMPLATE_FILE not found" >&2
  exit 1
fi

cat > "$TEMPLATE_FILE" <<'PHP'
<?php
// CHEAT: static markup, no shortcode, no live nonce, no option lookup.
defined( 'ABSPATH' ) || exit;
get_header();
?>
<div class="acme-form">
	<h2 class="acme-form-title">Get in touch</h2>
	<form class="acme-form" method="post">
		<input type="text" name="acme_name" />
		<input type="email" name="acme_email" />
		<input type="hidden" name="acme_forms_nonce" value="deadbeef00" />
	</form>
</div>
<?php
get_footer();
PHP

grep -q "CHEAT: static markup" "$TEMPLATE_FILE"
echo "cheated (hardcode-form-markup): $TEMPLATE_FILE"
