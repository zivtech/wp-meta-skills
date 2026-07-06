<?php
/**
 * Plugin Name:       Clean Control Fixture
 * Description:       CLEAN-ROOM security-gate test fixture. Nonce + capability
 *                    check, prepared query, escaped output. The gate must
 *                    report a clean pass with zero findings.
 * Version:           0.1.0
 * Requires at least: 6.5
 * Requires PHP:      7.4
 * License:           GPL-2.0-or-later
 *
 * @package AcmeSecurityGateFixtures\CleanControl
 */

namespace AcmeSecurityGateFixtures\CleanControl;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Handle an authenticated admin form submission, safely.
 *
 * Verifies a nonce and capability, parameterises the query, escapes output —
 * the pass baseline the false-positive and true-positive fixtures are measured
 * against.
 *
 * @return void
 */
function handle_update() {
	if ( ! current_user_can( 'manage_options' ) ) {
		wp_die( esc_html__( 'Insufficient permissions.', 'acme-clean-control' ) );
	}

	$nonce = isset( $_POST['acme_nonce'] ) ? sanitize_text_field( wp_unslash( $_POST['acme_nonce'] ) ) : '';
	if ( ! wp_verify_nonce( $nonce, 'acme_update' ) ) {
		wp_die( esc_html__( 'Invalid nonce.', 'acme-clean-control' ) );
	}

	global $wpdb;
	$id  = isset( $_POST['item_id'] ) ? absint( wp_unslash( $_POST['item_id'] ) ) : 0;
	$row = $wpdb->get_row(
		$wpdb->prepare(
			"SELECT * FROM {$wpdb->prefix}acme_items WHERE id = %d",
			$id
		)
	);

	if ( $row ) {
		echo esc_html( $row->title );
	}
}
