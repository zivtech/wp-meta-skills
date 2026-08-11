# Review target: Acme Member Search

Review this WordPress plugin file with `wordpress-security-critic`. Report the
security issues you find. For each, give a `file:line` reference, explain how it is
reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Member Search
 */

add_action( 'admin_post_acme_member_search', 'acme_member_search' );

function acme_member_search() {
	check_admin_referer( 'acme_member_search' );

	global $wpdb;

	$term = isset( $_POST['term'] ) ? sanitize_text_field( wp_unslash( $_POST['term'] ) ) : '';

	$rows = $wpdb->get_results(
		$wpdb->prepare(
			"SELECT ID, display_name FROM {$wpdb->users} WHERE display_name LIKE %s",
			'%' . $term . '%'
		)
	);

	set_transient( 'acme_member_search_last', wp_list_pluck( $rows, 'ID' ), MINUTE_IN_SECONDS );

	wp_safe_redirect( admin_url( 'users.php?page=acme-search' ) );
	exit;
}
```

## Scope

Static review of the code shown. Name any runtime, WP-CLI, or PHPUnit checks that
would still be needed to confirm a finding. Do not claim supply-chain review,
malware scanning, or production-exploit proof.
