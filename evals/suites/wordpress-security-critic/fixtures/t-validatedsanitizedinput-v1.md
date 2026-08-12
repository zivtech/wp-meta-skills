# Review target: Acme Support Widget

Review this WordPress plugin file with `wordpress-security-critic`. Report the
security issues you find. For each, give a `file:line` reference, explain how it is
reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Support Widget
 * Description: Save the support contact note shown in the admin help widget.
 */

add_action( 'admin_post_acme_save_support_note', 'acme_save_support_note' );

function acme_save_support_note() {
	if ( ! current_user_can( 'manage_options' ) ) {
		wp_die( esc_html__( 'You are not allowed to do that.', 'acme' ), 403 );
	}

	check_admin_referer( 'acme_support_note' );

	update_option( 'acme_support_contact_note', $_POST['support_note'] );

	wp_safe_redirect( admin_url( 'options-general.php?page=acme-support&updated=1' ) );
	exit;
}
```

## Scope

Static review of the code shown. Name any runtime, WP-CLI, or PHPUnit checks that
would still be needed to confirm a finding. Do not claim supply-chain review,
malware scanning, or production-exploit proof.
