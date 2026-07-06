<?php
/**
 * Plugin Name: API Hallucination Bait
 * Description: Deterministic fixture for the API-existence lint: calls one nonexistent core function and hooks one nonexistent core action.
 * Version: 1.0.0
 * Requires at least: 6.0
 * License: GPLv2 or later
 *
 * @package API_Hallucination_Bait
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Sanitizes a submitted email with a hallucinated core function.
 *
 * Expected phase-1 finding: unknown_function wp_sanitize_email_address with a
 * did-you-mean suggestion of sanitize_email.
 *
 * @param string $email Raw email input.
 * @return string Sanitized email.
 */
function api_hallucination_bait_sanitize( $email ) {
	return wp_sanitize_email_address( $email );
}

/**
 * Registers styles from a self-defined callback.
 */
function api_hallucination_bait_enqueue() {
	wp_enqueue_style( 'api-hallucination-bait', plugins_url( 'style.css', __FILE__ ), array(), '1.0.0' );
}

// Nonexistent core action (near wp_enqueue_scripts). Phase 1 does not detect
// unknown hook names; the phase-2 hooks database must turn this into an
// unknown_hook finding. Until then this line documents the known gap.
add_action( 'wp_enqueue_script_loader', 'api_hallucination_bait_enqueue' );
