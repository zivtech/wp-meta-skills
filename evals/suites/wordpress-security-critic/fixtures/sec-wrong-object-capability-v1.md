# Review target: Acme Quick Edit

Review this WordPress plugin file with `wordpress-security-critic`. Report the
security issues you find. For each, give a `file:line` reference, explain how it is
reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Quick Edit
 * Description: Inline-save a post title from an author-facing edit widget.
 */

add_action( 'admin_post_acme_quick_edit', 'acme_quick_edit_save' );

function acme_quick_edit_save() {
	check_admin_referer( 'acme_quick_edit' );

	if ( ! current_user_can( 'edit_posts' ) ) {
		wp_die( esc_html__( 'Forbidden', 'acme' ), '', array( 'response' => 403 ) );
	}

	$post_id = isset( $_POST['post_id'] ) ? absint( wp_unslash( $_POST['post_id'] ) ) : 0;
	$title   = isset( $_POST['title'] ) ? sanitize_text_field( wp_unslash( $_POST['title'] ) ) : '';

	wp_update_post(
		array(
			'ID'         => $post_id,
			'post_title' => $title,
		)
	);

	wp_safe_redirect( admin_url( 'edit.php' ) );
	exit;
}
```

## Scope

Static review of the code shown. Name any runtime, WP-CLI, or PHPUnit checks that
would still be needed to confirm a finding. Do not claim supply-chain review,
malware scanning, or production-exploit proof.
