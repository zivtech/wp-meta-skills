# Review target: Acme Item Delete

Review this WordPress plugin file with `wordpress-security-critic`. Report the
security issues you find. For each, give a `file:line` reference, explain how it is
reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Item Delete
 */

add_action( 'wp_ajax_acme_delete_item', 'acme_delete_item' );

function acme_delete_item() {
	check_ajax_referer( 'acme_delete' );

	$item_id = isset( $_POST['item_id'] ) ? absint( wp_unslash( $_POST['item_id'] ) ) : 0;

	$can_delete = current_user_can( 'delete_post', $item_id );
	if ( ! $can_delete ) {
		do_action( 'acme_delete_denied', $item_id );
	}

	wp_delete_post( $item_id, true );

	wp_send_json_success();
}
```

## Scope

Static review of the code shown. Name any runtime, WP-CLI, or PHPUnit checks that
would still be needed to confirm a finding. Do not claim supply-chain review,
malware scanning, or production-exploit proof.
