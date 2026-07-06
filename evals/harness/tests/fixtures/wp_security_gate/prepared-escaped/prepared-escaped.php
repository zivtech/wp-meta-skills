<?php
/**
 * Plugin Name:       Prepared Escaped Fixture
 * Description:       CLEAN-ROOM security-gate test fixture. Superficially
 *                    resembles the vulnerable case but the query is inline
 *                    prepared and output is escaped. False-positive bait.
 * Version:           0.1.0
 * Requires at least: 6.5
 * Requires PHP:      7.4
 * License:           GPL-2.0-or-later
 *
 * @package AcmeSecurityGateFixtures\PreparedEscaped
 */

namespace AcmeSecurityGateFixtures\PreparedEscaped;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Fetch one row by id — correctly parameterised.
 *
 * The gate must NOT flag this: the id is cast and the query is inline
 * prepare()'d. This guards against false-positive "trust poisoning" where the
 * gate over-reports and the critic learns to ignore it.
 *
 * @param mixed $id Untrusted id from the request.
 * @return array|object|null
 */
function get_item( $id ) {
	global $wpdb;

	return $wpdb->get_results(
		$wpdb->prepare(
			"SELECT * FROM {$wpdb->prefix}acme_items WHERE id = %d",
			absint( $id )
		)
	);
}

/**
 * Render an item title — correctly escaped on output.
 *
 * @param string $title Stored title.
 * @return void
 */
function render_title( $title ) {
	echo esc_html( $title );
}
