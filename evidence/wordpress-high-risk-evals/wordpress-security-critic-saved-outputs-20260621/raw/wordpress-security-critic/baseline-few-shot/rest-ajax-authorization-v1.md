**Scope**

Static security review of the provided WordPress plugin excerpt only. This is not a supply-chain review, malware scan, full plugin audit, or proof of production exploitability. The target is reachable authorization failure across REST and AJAX mutation paths.

**WordPress-Specific Decisions**

The REST route is vulnerable:

```php
'permission_callback' => '__return_true',
```

This makes the `POST /wp-json/acme/v1/flag/{id}` mutation publicly reachable. The callback updates post meta without checking whether the caller is authenticated or can edit the target post.

Expected protection should be target-specific, for example:

```php
'permission_callback' => function ( WP_REST_Request $request ) {
	$post_id = absint( $request['id'] );
	return current_user_can( 'edit_post', $post_id );
}
```

The AJAX clear path has nonce-as-authorization confusion:

```php
check_ajax_referer( 'acme-flags' );
delete_post_meta( absint( $_POST['post_id'] ), '_acme_editorial_flag' );
```

`check_ajax_referer()` verifies request intent/origin context, not user capability. A valid nonce does not prove the caller can edit the target post. The handler also needs:

```php
$post_id = absint( $_POST['post_id'] ?? 0 );

if ( ! current_user_can( 'edit_post', $post_id ) ) {
	wp_send_json_error( array( 'message' => 'Forbidden' ), 403 );
}
```

The `wp_ajax_nopriv_acme_clear_flag` registration is especially risky because it exposes a mutation path to logged-out users:

```php
add_action( 'wp_ajax_nopriv_acme_clear_flag', 'acme_flags_clear_flag' );
```

If the nonce is leaked, printed publicly, cached into public HTML, or otherwise disclosed, logged-out users could clear flags. For an editorial post-meta mutation, the unauthenticated AJAX action should likely be removed.

**Risks**

High-confidence authorization failure: unauthenticated or underprivileged users can mutate `_acme_editorial_flag` through the REST route because the permission callback is public.

High-confidence authorization gap: AJAX nonce validation is being treated as sufficient authorization, but WordPress nonces are not capability checks.

Higher exposure on AJAX: `wp_ajax_nopriv_*` makes the mutation available to logged-out callers if they obtain a valid nonce.

What I am not claiming: I am not claiming a confirmed production exploit, nonce leakage in the real site, supply-chain compromise, malware, privilege escalation beyond this meta mutation, or broader plugin compromise. The finding is based only on the shown code.

**Verification**

Concrete tests should cover forbidden and allowed cases, not only successful mutation.

Recommended test paths:

1. REST forbidden subscriber:
   - Log in as a subscriber.
   - Send `POST /wp-json/acme/v1/flag/{post_id}` with `flag=review`.
   - Expected secure behavior: `403`.
   - Current fixture likely updates post meta.

2. REST logged-out:
   - Send the same REST request without authentication.
   - Expected secure behavior: `401` or `403`.
   - Current fixture likely updates post meta.

3. REST editor allowed:
   - Log in as an editor who can edit the target post.
   - Send the same request.
   - Expected secure behavior: success and meta updated.

4. AJAX forbidden subscriber:
   - Log in as a subscriber with a valid nonce.
   - Call `admin-ajax.php?action=acme_clear_flag&post_id={id}`.
   - Expected secure behavior: `403`.
   - Current fixture likely deletes post meta.

5. AJAX logged-out:
   - Call the `nopriv` action with a valid leaked/public nonce, if one is available in the rendered page.
   - Expected secure behavior: no mutation path for logged-out users.
   - Current fixture permits deletion if nonce passes.

6. AJAX editor allowed:
   - Log in as an editor with a valid nonce and a post they can edit.
   - Expected secure behavior: success and meta deleted.

These could be implemented with WordPress PHPUnit REST/AJAX tests or equivalent controlled integration tests. Avoid unsafe production mutation tests; use a local, staging, or test database fixture.

**Open Questions**

- Is `_acme_editorial_flag` intended to be editable only by users who can `edit_post`, or should it require a stricter custom capability?
- Where is the `acme-flags` nonce generated and exposed?
- Is the nonce ever printed on public pages or cached HTML?
- Should logged-out users ever be able to clear editorial flags? Based on the fixture, the answer appears to be no.
- Should the REST callback reject invalid post IDs or non-editable post types before mutation?