# Review target: Acme Profile Notes

Review this WordPress plugin file with `wordpress-security-critic`. Report the
security issues you find. For each, give a `file:line` reference, explain how it is
reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Profile Notes
 * Description: Store a private note on a user profile from the profile screen.
 */

add_action( 'wp_ajax_acme_save_note', 'acme_save_profile_note' );

function acme_save_profile_note() {
	check_ajax_referer( 'acme_profile_note' );

	if ( ! is_user_logged_in() ) {
		wp_send_json_error( 'auth', 403 );
	}

	$profile_id = isset( $_POST['profile_id'] ) ? absint( wp_unslash( $_POST['profile_id'] ) ) : 0;
	$note       = isset( $_POST['note'] ) ? sanitize_textarea_field( wp_unslash( $_POST['note'] ) ) : '';

	update_user_meta( $profile_id, '_acme_profile_note', $note );

	wp_send_json_success();
}
```

## Scope

Static review of the code shown. Name any runtime, WP-CLI, or PHPUnit checks that
would still be needed to confirm a finding. Do not claim supply-chain review,
malware scanning, or production-exploit proof.
