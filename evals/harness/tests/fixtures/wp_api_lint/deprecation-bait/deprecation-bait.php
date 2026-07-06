<?php
/**
 * Plugin Name: Deprecation Bait
 * Description: Deterministic fixture for the API lint's native deprecation engine: calls two long-deprecated core functions whose findings must name the exact successors.
 * Version: 1.0.0
 * Requires at least: 6.0
 * License: GPLv2 or later
 *
 * @package Deprecation_Bait
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Expected findings: deprecated_api wp_login (2.5.0, use wp_signon()) and
 * deprecated_api get_all_category_ids (4.0.0, use get_terms()).
 */
function deprecation_bait_run() {
	wp_login( 'admin', 'secret' );
	$ids = get_all_category_ids();
	return $ids;
}
