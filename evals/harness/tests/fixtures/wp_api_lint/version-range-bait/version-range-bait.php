<?php
/**
 * Plugin Name: Version Range Bait
 * Description: Deterministic fixture for the API-existence lint: declares Requires at least 6.0 but calls a WordPress 6.1.0 function unconditionally.
 * Version: 1.0.0
 * Requires at least: 6.0
 * License: GPLv2 or later
 *
 * @package Version_Range_Bait
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Resolves the template hierarchy for a slug.
 *
 * Expected phase-1 finding: version_range for get_template_hierarchy
 * (introduced in 6.1.0, declared minimum 6.0).
 *
 * @param string $slug Template slug.
 * @return array Template hierarchy.
 */
function version_range_bait_hierarchy( $slug ) {
	return get_template_hierarchy( $slug );
}
