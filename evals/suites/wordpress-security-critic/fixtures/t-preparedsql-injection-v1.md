# Review target: Acme Order Lookup

Review this WordPress plugin file with `wordpress-security-critic`. Report the
security issues you find. For each, give a `file:line` reference, explain how it is
reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Order Lookup
 * Description: Let a customer look up their order status by order reference.
 */

add_action( 'template_redirect', 'acme_handle_order_lookup' );

function acme_handle_order_lookup() {
	if ( empty( $_GET['acme_order_ref'] ) ) {
		return;
	}

	global $wpdb;

	$order_ref = sanitize_text_field( wp_unslash( $_GET['acme_order_ref'] ) );

	$row = $wpdb->get_row(
		"SELECT status, shipped_at FROM {$wpdb->prefix}acme_orders WHERE order_ref = '$order_ref'"
	);

	if ( $row ) {
		wp_send_json_success( array( 'status' => $row->status ) );
	}

	wp_send_json_error( 'not_found', 404 );
}
```

## Scope

Static review of the code shown. Name any runtime, WP-CLI, or PHPUnit checks that
would still be needed to confirm a finding. Do not claim supply-chain review,
malware scanning, or production-exploit proof.
