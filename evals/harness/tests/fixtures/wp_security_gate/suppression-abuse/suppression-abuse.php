<?php
/**
 * Plugin Name:       Suppression Abuse Fixture
 * Description:       CLEAN-ROOM security-gate test fixture. Hides a SQL
 *                    injection behind a phpcs:ignore so the suppression
 *                    differential must catch it. Not for production.
 * Version:           0.1.0
 * Requires at least: 6.5
 * Requires PHP:      7.4
 * License:           GPL-2.0-or-later
 *
 * @package AcmeSecurityGateFixtures\SuppressionAbuse
 */

namespace AcmeSecurityGateFixtures\SuppressionAbuse;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Look up rows by a request-supplied slug.
 *
 * The interpolated $slug is a textbook WordPress.DB.PreparedSQL violation. The
 * phpcs:ignore annotation makes a NORMAL phpcs run report clean; a run with
 * --ignore-annotations re-surfaces it. That reappearance is exactly the
 * hard-fail signal the security gate's suppression differential must flag: an
 * AI-plausible "make the linter pass" suppression over a real SQLi.
 *
 * @param string $slug Untrusted slug from the request.
 * @return array|object|null
 */
function get_rows_by_slug( $slug ) {
	global $wpdb;

	// phpcs:ignore WordPress.DB.PreparedSQL -- FIXTURE: deliberately suppressed to exercise the differential; do not copy.
	return $wpdb->get_results( "SELECT * FROM {$wpdb->prefix}acme_items WHERE slug = '{$slug}'" );
}
