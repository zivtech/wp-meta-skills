# Review target: Acme Note Editor

Review this WordPress plugin file with `wordpress-security-critic`. Report the
security issues you find. For each, give a `file:line` reference, explain how it is
reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Note Editor
 */

// includes/permissions.php
function acme_current_user_can_edit( $post_id ) {
	return current_user_can( 'edit_post', $post_id );
}

// acme-note-editor.php
add_action( 'admin_post_acme_update_note', 'acme_update_note' );

function acme_update_note() {
	check_admin_referer( 'acme_update_note' );

	$post_id = isset( $_POST['post_id'] ) ? absint( wp_unslash( $_POST['post_id'] ) ) : 0;

	if ( ! acme_current_user_can_edit( $post_id ) ) {
		wp_die( esc_html__( 'Forbidden', 'acme' ), '', array( 'response' => 403 ) );
	}

	$note = isset( $_POST['note'] ) ? sanitize_textarea_field( wp_unslash( $_POST['note'] ) ) : '';
	update_post_meta( $post_id, '_acme_note', $note );

	wp_safe_redirect( admin_url( 'edit.php' ) );
	exit;
}
```

## Scope

Static review of the code shown. Name any runtime, WP-CLI, or PHPUnit checks that
would still be needed to confirm a finding. Do not claim supply-chain review,
malware scanning, or production-exploit proof.
