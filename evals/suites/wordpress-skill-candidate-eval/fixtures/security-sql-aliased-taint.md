# Security: INJECTION_SUBTLE

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: SQL injection, taint flow across function boundaries, `$wpdb` safety.
Fixture tier: An injection where the tainted value crosses two function hops before reaching the query, so WPCS `PreparedSQL` does not flag it, and `$wpdb->prepare()` is used elsewhere in the plugin as a decoy. Authorization here is correct — the ONLY real issue is the cross-function SQLi.

Scenario summary: An authenticated AJAX endpoint lists orders filtered by status; the status value reaches the query through a helper without sanitization or a placeholder.

Artifact under review:

```php
add_action( 'wp_ajax_acme_orders', 'acme_orders' );

function acme_orders() {
    check_ajax_referer( 'acme_orders', 'nonce' );
    if ( ! current_user_can( 'manage_woocommerce' ) ) {
        wp_send_json_error( array(), 403 );
    }
    $status = acme_param( 'status' );
    wp_send_json_success( acme_query_orders( $status ) );
}

function acme_param( $key ) {
    return isset( $_GET[ $key ] ) ? wp_unslash( $_GET[ $key ] ) : '';   // unslashed, not sanitized
}

function acme_query_orders( $status ) {
    global $wpdb;
    // Other queries in this plugin correctly use $wpdb->prepare().
    $sql = "SELECT * FROM {$wpdb->prefix}acme_orders WHERE status = '{$status}'";
    return $wpdb->get_results( $sql );
}
```

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Trace the taint: `$_GET['status']` → `acme_param()` → `acme_query_orders()` → interpolated into the SQL string.
- State that `prepare()` used on other queries does not protect this path, and that the present capability check does not mitigate injection.
- Require `$wpdb->prepare()` with a `%s` placeholder (and/or an allow-list for `status`) plus a regression test with an injection payload.

A weak or unsafe response likely:
- Concludes the plugin is safe because `$wpdb->prepare()` appears elsewhere.
- Stops at the authorized handler and never follows the value into the helper.
- Recommends output escaping as the fix (wrong layer) or flags the capability check as missing (it is present).

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Security domain. Reward cross-function taint tracing, correct remediation layer, and a concrete test. Penalize "prepare elsewhere = safe" reasoning, generic CMS advice, and invented issues.
