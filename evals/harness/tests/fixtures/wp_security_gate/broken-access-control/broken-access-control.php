<?php
/**
 * Plugin Name:       Broken Access Control Fixture
 * Description:       CLEAN-ROOM security-gate test fixture. State-changing REST
 *                    route with an open permission_callback. Documents the
 *                    deterministic blind spot: sniffs are silent, the critic
 *                    must catch it. Not for production.
 * Version:           0.1.0
 * Requires at least: 6.5
 * Requires PHP:      7.4
 * License:           GPL-2.0-or-later
 *
 * @package AcmeSecurityGateFixtures\BrokenAccessControl
 */

namespace AcmeSecurityGateFixtures\BrokenAccessControl;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

add_action( 'rest_api_init', __NAMESPACE__ . '\\register_routes' );

/**
 * Register a state-changing route with NO real authorization.
 *
 * `'permission_callback' => '__return_true'` on a POST that mutates data is a
 * broken-access-control vulnerability. WPCS/PHPCS security sniffs are SILENT on
 * this — it is semantic, not mechanical. The gate therefore reports `pass`
 * here, and this fixture proves the gate does not falsely claim to cover the
 * hole: the exploitability judgment belongs to wordpress-security-critic.
 *
 * @return void
 */
function register_routes() {
	register_rest_route(
		'acme/v1',
		'/items',
		array(
			'methods'             => 'POST',
			'callback'            => __NAMESPACE__ . '\\create_item',
			'permission_callback' => '__return_true',
		)
	);
}

/**
 * Create an item (body intentionally omitted — fixture documents the auth hole
 * only, carries no exploit payload).
 *
 * @param \WP_REST_Request $request Request.
 * @return \WP_REST_Response
 */
function create_item( $request ) {
	return new \WP_REST_Response( array( 'created' => true ), 201 );
}
