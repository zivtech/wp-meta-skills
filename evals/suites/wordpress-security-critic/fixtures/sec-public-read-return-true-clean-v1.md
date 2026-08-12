# Review target: Acme Public Directory

Review this WordPress plugin file with `wordpress-security-critic`. Report the
security issues you find. For each, give a `file:line` reference, explain how it is
reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Public Directory
 * Description: Read-only REST endpoint listing published team members for the public site.
 */

add_action( 'rest_api_init', 'acme_register_public_routes' );

function acme_register_public_routes() {
	register_rest_route(
		'acme/v1',
		'/team',
		array(
			'methods'             => WP_REST_Server::READABLE,
			'callback'            => 'acme_get_team',
			'permission_callback' => '__return_true',
		)
	);
}

function acme_get_team( WP_REST_Request $request ) {
	$members = get_posts(
		array(
			'post_type'      => 'acme_member',
			'post_status'    => 'publish',
			'posts_per_page' => 20,
		)
	);

	$data = array();
	foreach ( $members as $member ) {
		$data[] = array(
			'name' => get_the_title( $member ),
			'role' => esc_html( get_post_meta( $member->ID, 'acme_role', true ) ),
		);
	}

	return rest_ensure_response( $data );
}
```

## Scope

Static review of the code shown. Name any runtime, WP-CLI, or PHPUnit checks that
would still be needed to confirm a finding. Do not claim supply-chain review,
malware scanning, or production-exploit proof.
