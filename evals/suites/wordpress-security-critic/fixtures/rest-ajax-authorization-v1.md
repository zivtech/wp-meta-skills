# Focused Fixture: REST and AJAX Authorization Boundary

Review the following WordPress plugin excerpt with `wordpress-security-critic`.
The review target is not general code quality. It is whether the implementation
creates reachable authorization failures across REST and AJAX mutation paths.

## Artifact Under Review

```php
<?php
/**
 * Plugin Name: Acme Editorial Flags
 */

add_action( 'rest_api_init', 'acme_flags_register_routes' );
function acme_flags_register_routes() {
	register_rest_route(
		'acme/v1',
		'/flag/(?P<id>\d+)',
		array(
			'methods'             => 'POST',
			'callback'            => 'acme_flags_set_flag',
			'permission_callback' => '__return_true',
		)
	);
}

function acme_flags_set_flag( WP_REST_Request $request ) {
	$post_id = absint( $request['id'] );
	update_post_meta( $post_id, '_acme_editorial_flag', sanitize_key( $request['flag'] ) );
	return rest_ensure_response( array( 'updated' => true ) );
}

add_action( 'wp_ajax_acme_clear_flag', 'acme_flags_clear_flag' );
add_action( 'wp_ajax_nopriv_acme_clear_flag', 'acme_flags_clear_flag' );
function acme_flags_clear_flag() {
	check_ajax_referer( 'acme-flags' );
	delete_post_meta( absint( $_POST['post_id'] ), '_acme_editorial_flag' );
	wp_send_json_success();
}
```

## Expected Review Focus

- Detect authentication without authorization on `register_rest_route()` because
  `permission_callback` is public and no `current_user_can()` or mapped
  capability check protects the mutation.
- Detect nonce-as-capability confusion on the AJAX handler. A valid
  `check_ajax_referer()` token does not prove the caller can edit the target
  post.
- Detect that `wp_ajax_nopriv_acme_clear_flag` exposes a mutation to logged-out
  users if a nonce leaks or is printed publicly.
- Require a concrete test path for forbidden subscriber, logged-out, and editor
  cases rather than only happy-path mutation.

## Required Boundaries

Do not claim supply-chain review, malware scanning, or production exploit proof.
The fixture is a static review of a small code excerpt. The answer should state
what runtime tests or WP-CLI/PHPUnit checks would still be needed.
