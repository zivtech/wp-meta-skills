# Review target: Acme Report Manager

Review this WordPress plugin file with `wordpress-security-critic`. Report the
security issues you find. For each, give a `file:line` reference, explain how it is
reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Report Manager
 * Description: Let editors remove saved report snapshots from the admin list.
 */

add_action( 'admin_post_acme_delete_report', 'acme_delete_report' );

function acme_delete_report() {
	if ( ! current_user_can( 'edit_posts' ) ) {
		wp_die( esc_html__( 'You are not allowed to do that.', 'acme' ), 403 );
	}

	$report_id = isset( $_POST['report_id'] ) ? absint( $_POST['report_id'] ) : 0;

	if ( $report_id ) {
		wp_delete_post( $report_id, true );
	}

	wp_safe_redirect( admin_url( 'edit.php?post_type=acme_report&deleted=1' ) );
	exit;
}
```

## Scope

Static review of the code shown. Name any runtime, WP-CLI, or PHPUnit checks that
would still be needed to confirm a finding. Do not claim supply-chain review,
malware scanning, or production-exploit proof.
