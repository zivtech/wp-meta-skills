<?php
/**
 * Plugin Name: Clean Control
 * Description: False-positive control fixture for the API-existence lint: real core APIs only, all inside the declared version range.
 * Version: 1.0.0
 * Requires at least: 6.0
 * License: GPLv2 or later
 *
 * @package Clean_Control
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Sanitizes and echoes a category list.
 *
 * Expected phase-1 result: zero findings, status pass.
 *
 * @param string $email Raw email input.
 * @return string Sanitized email.
 */
function clean_control_sanitize( $email ) {
	return sanitize_email( $email );
}

/**
 * Renders term names for the default taxonomy.
 */
function clean_control_render_terms() {
	$terms = get_terms( array( 'taxonomy' => 'category', 'hide_empty' => false ) );
	if ( is_wp_error( $terms ) ) {
		return;
	}
	foreach ( $terms as $term ) {
		echo esc_html( $term->name );
	}
}

add_action( 'init', 'clean_control_sanitize' );
add_action( 'wp_footer', 'clean_control_render_terms' );
