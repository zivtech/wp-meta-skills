# Security: AUTHZ_SUBTLE

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Capability vs. intent, nonce semantics, AJAX authorization, privilege boundaries.
Fixture tier: A non-obvious authorization gap that PASSES a nonce check and survives WPCS `NonceVerification`. A reviewer that equates "nonce present" with "authorized" will miss it.

Scenario summary: A plugin exposes an authenticated AJAX action that changes any user's role. The handler verifies a nonce but never checks the caller's capability.

Artifact under review:

```php
add_action( 'wp_ajax_acme_set_role', 'acme_set_role' );

function acme_set_role() {
    check_ajax_referer( 'acme_admin', 'nonce' );   // nonce verified

    $user_id = (int) $_POST['user_id'];
    $role    = sanitize_text_field( $_POST['role'] );

    $user = get_user_by( 'id', $user_id );
    $user->set_role( $role );                       // role changed

    wp_send_json_success( array( 'role' => $role ) );
}
```

The `acme_admin` nonce is printed on a staff dashboard partial that renders for any logged-in user with the `read` capability (Subscriber and above).

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Identify that a verified nonce proves request intent/origin, NOT authorization, and that no `current_user_can()` gate exists.
- Show the concrete escalation: an authenticated Subscriber who can read the nonce can set their own role to administrator.
- Require a capability check (e.g., `current_user_can( 'promote_users' )`) plus a test for an unauthorized (Subscriber) caller.

A weak or unsafe response likely:
- Concludes the handler is secure because the nonce is checked.
- Recommends "add a nonce" (already present) or stronger input sanitization, missing the authorization gap.
- Treats the `(int)` cast or `sanitize_text_field` as the main concern.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Security domain. Reward capability-vs-intent reasoning, the concrete escalation path, and executable remediation plus tests. Penalize "nonce = secure" reasoning, generic CMS advice, and invented issues.
