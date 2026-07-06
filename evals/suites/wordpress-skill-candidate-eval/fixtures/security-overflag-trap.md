# Security: FALSE_POSITIVE_TRAP

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: False-positive resistance, calibrated severity, admin-equivalent power, correct WordPress idioms.
Fixture tier: Sound admin code that INVITES over-flagging. The strong response recognizes it is correct (with at most minor hardening); a weak response manufactures injection/XSS/nonce findings that are not real.

Scenario summary: An `admin-post` maintenance handler clears expired cache rows and renders an admin-authored notice. It is properly gated and uses correct idioms.

Artifact under review:

```php
add_action( 'admin_post_acme_rebuild', 'acme_rebuild' );

function acme_rebuild() {
    if ( ! current_user_can( 'manage_options' ) ) {
        wp_die( esc_html__( 'Forbidden', 'acme' ), 403 );
    }
    check_admin_referer( 'acme_rebuild' );

    global $wpdb;
    // Hardcoded maintenance statement — no user input in the query.
    $wpdb->query( "DELETE FROM {$wpdb->prefix}acme_cache WHERE expires < UTC_TIMESTAMP()" );

    $notice = get_option( 'acme_last_notice', '' ); // admin-authored, intentionally rich HTML
    echo wp_kses_post( $notice );

    wp_safe_redirect( admin_url( 'admin.php?page=acme' ) );
    exit;
}
```

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Recognize the handler is sound: capability gate (`manage_options`) + `check_admin_referer` + a hardcoded query with no injection surface + `wp_kses_post` on admin-authored rich HTML + `wp_safe_redirect`.
- Calibrate: no CRITICAL/MAJOR finding is warranted; offer at most minor, optional hardening (e.g., `exit` after redirect is already present; consider scheduling the cleanup via cron) clearly labeled as non-blocking.
- Name negative space: what the review does NOT find, and why each tempting flag does not apply.

A weak or unsafe response likely:
- Flags the hardcoded `$wpdb->query` as SQL injection or demands `$wpdb->prepare()` on a query with no variables.
- Calls the `wp_kses_post` output an XSS vulnerability.
- Claims a nonce is missing (`check_admin_referer` is present) or that `manage_options` is insufficient.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Security domain. Reward calibrated recognition of sound patterns, correct WordPress idiom knowledge, and explicit negative space. Penalize invented injection/XSS/nonce findings, demanding `prepare()` where there is no variable input, and treating appropriate admin power as a vulnerability.
