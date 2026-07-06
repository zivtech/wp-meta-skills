<?php
/**
 * Plugin Name: Version Range Guarded
 * Description: Control fixture for the API-existence lint: the same WordPress 6.1.0 call as version-range-bait, made safe with a function_exists() guard.
 * Version: 1.0.0
 * Requires at least: 6.0
 * License: GPLv2 or later
 *
 * @package Version_Range_Guarded
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Resolves the template hierarchy for a slug on WordPress 6.1+.
 *
 * Expected phase-1 result: zero findings — wp-compat respects the
 * function_exists() guard through real scope analysis.
 *
 * @param string $slug Template slug.
 * @return array Template hierarchy.
 */
function version_range_guarded_hierarchy( $slug ) {
	if ( function_exists( 'get_template_hierarchy' ) ) {
		return get_template_hierarchy( $slug );
	}
	return array( 'index.php' );
}
