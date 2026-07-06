<?php
/**
 * Plugin Name: Deprecation Clean
 * Description: False-positive control for the native deprecation engine: calls the modern successors of the deprecation-bait fixture's calls and must produce zero findings.
 * Version: 1.0.0
 * Requires at least: 6.0
 * License: GPLv2 or later
 *
 * @package Deprecation_Clean
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Expected findings: none.
 */
function deprecation_clean_run() {
	$user = wp_signon( array() );
	$terms = get_terms( array( 'taxonomy' => 'category' ) );
	return array( $user, $terms );
}
