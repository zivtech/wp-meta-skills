<?php
/**
 * Plugin Name: Acme Forms
 * Description: Tiny GPL fixture plugin for the localwp-agent-tools-value
 *              eval, fixture fatal-in-error-log-fresh-debug-log-misleads
 *              (design §5 row 13). Renders a contact form on the "Contact"
 *              page via a shortcode.
 * Version:     1.0.0
 * License:     GPL-2.0-or-later
 */

defined( 'ABSPATH' ) || exit;

require_once __DIR__ . '/includes/class-acme-forms.php';

add_shortcode( 'acme_contact_form', array( 'Acme_Forms', 'render_shortcode' ) );

add_filter( 'template_include', 'acme_forms_template_include' );

/**
 * Swaps in the contact template for the site's "Contact" page.
 *
 * @param string $template Template path WordPress resolved.
 * @return string
 */
function acme_forms_template_include( $template ) {
	if ( is_page( 'contact' ) ) {
		return __DIR__ . '/templates/contact.php';
	}
	return $template;
}
