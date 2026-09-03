<?php
/**
 * Contact page template (design §5 row 13). Renders the acme_contact_form
 * shortcode — a real do_shortcode() call, so the dynamic probe's option
 * change (design finding 4) actually has to flow through PHP to show up.
 */

defined( 'ABSPATH' ) || exit;

get_header();
echo do_shortcode( '[acme_contact_form]' );
get_footer();
