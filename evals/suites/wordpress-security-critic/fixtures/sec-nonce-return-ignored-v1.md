# Review target: Acme Settings Saver

Review this WordPress plugin file with `wordpress-security-critic`. Report the
security issues you find. For each, give a `file:line` reference, explain how it is
reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Settings Saver
 */

add_action( 'admin_post_acme_save_settings', 'acme_save_settings' );

function acme_save_settings() {
	if ( ! current_user_can( 'manage_options' ) ) {
		wp_die( esc_html__( 'Forbidden', 'acme' ), '', array( 'response' => 403 ) );
	}

	$nonce = isset( $_POST['acme_nonce'] ) ? sanitize_text_field( wp_unslash( $_POST['acme_nonce'] ) ) : '';
	wp_verify_nonce( $nonce, 'acme_save_settings' );

	$value = isset( $_POST['acme_value'] ) ? sanitize_text_field( wp_unslash( $_POST['acme_value'] ) ) : '';
	update_option( 'acme_value', $value );

	wp_safe_redirect( admin_url( 'options-general.php?page=acme' ) );
	exit;
}
```

## Scope

Static review of the code shown. Name any runtime, WP-CLI, or PHPUnit checks that
would still be needed to confirm a finding. Do not claim supply-chain review,
malware scanning, or production-exploit proof.
