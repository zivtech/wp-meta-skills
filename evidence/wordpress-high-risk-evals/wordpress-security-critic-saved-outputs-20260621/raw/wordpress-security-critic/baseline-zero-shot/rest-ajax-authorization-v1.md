**Security Review: REST and AJAX Authorization Boundary**

The excerpt creates reachable authorization failures on both mutation paths.

**Findings**

1. **REST mutation is public**
   `register_rest_route()` sets:

```php
'permission_callback' => '__return_true',
```

That makes `POST /wp-json/acme/v1/flag/{id}` callable by anyone who can reach the REST API. The callback mutates post meta:

```php
update_post_meta( $post_id, '_acme_editorial_flag', ... );
```

There is no `is_user_logged_in()`, `current_user_can()`, or post-specific capability check such as:

```php
current_user_can( 'edit_post', $post_id )
```

This is authentication without authorization, and in practice it is worse: the route is explicitly public.

A subscriber, logged-out visitor, or cross-site caller able to send the request could set `_acme_editorial_flag` on arbitrary post IDs unless other infrastructure blocks the request.

2. **AJAX nonce is treated as authorization**
   The AJAX handler uses:

```php
check_ajax_referer( 'acme-flags' );
delete_post_meta( absint( $_POST['post_id'] ), '_acme_editorial_flag' );
```

The nonce check only verifies that the request includes a valid nonce for the `acme-flags` action. It does **not** prove the caller can edit the target post.

A correct handler still needs a capability check after resolving the target post:

```php
$post_id = absint( $_POST['post_id'] ?? 0 );

if ( ! current_user_can( 'edit_post', $post_id ) ) {
	wp_send_json_error( array( 'message' => 'Forbidden' ), 403 );
}
```

Without that, any logged-in user who obtains a valid nonce could clear flags from posts they cannot edit.

3. **Logged-out AJAX mutation is exposed**
   This line is especially risky:

```php
add_action( 'wp_ajax_nopriv_acme_clear_flag', 'acme_flags_clear_flag' );
```

It exposes the delete mutation to unauthenticated users. `check_ajax_referer()` does not make this safe. If the nonce is printed publicly, cached into a page, leaked, or otherwise obtainable, logged-out users can delete the meta value.

For a post-editing mutation, the `nopriv` hook should be removed unless there is a very specific public-write design, which this fixture does not establish.

**Recommended Fix Shape**

Use the same post-specific authorization model on both paths.

For REST:

```php
'permission_callback' => function ( WP_REST_Request $request ) {
	$post_id = absint( $request['id'] );
	return $post_id && current_user_can( 'edit_post', $post_id );
},
```

For AJAX:

```php
add_action( 'wp_ajax_acme_clear_flag', 'acme_flags_clear_flag' );
// Remove wp_ajax_nopriv_acme_clear_flag.

function acme_flags_clear_flag() {
	check_ajax_referer( 'acme-flags' );

	$post_id = absint( $_POST['post_id'] ?? 0 );

	if ( ! $post_id || ! current_user_can( 'edit_post', $post_id ) ) {
		wp_send_json_error( array( 'message' => 'Forbidden' ), 403 );
	}

	delete_post_meta( $post_id, '_acme_editorial_flag' );
	wp_send_json_success();
}
```

**Required Tests**

This static review identifies the authorization failures, but it does not prove production exploitability. Runtime checks should cover:

- Logged-out REST `POST /wp-json/acme/v1/flag/{id}` returns `401` or `403` and does not update meta.
- Subscriber REST request returns `403` and does not update meta.
- Editor or authorized user REST request succeeds for a post they can edit.
- Logged-out AJAX request to `admin-ajax.php?action=acme_clear_flag` cannot delete meta, even with a nonce scenario explicitly tested.
- Subscriber AJAX request with a valid nonce cannot delete meta for a post they cannot edit.
- Editor AJAX request with a valid nonce can clear the flag for a post they can edit.

**What This Review Is Not Claiming**

This is not a supply-chain review, malware scan, or proof of exploitation in a deployed site. It is a static authorization review of the provided excerpt. The concrete issue is that both mutation paths lack target-object capability checks, and the AJAX path additionally exposes a mutation through `wp_ajax_nopriv_*`.