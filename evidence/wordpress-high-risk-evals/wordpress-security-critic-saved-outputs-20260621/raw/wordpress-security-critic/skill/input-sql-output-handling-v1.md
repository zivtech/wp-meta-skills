Running the security review against this plugin excerpt now, following the full protocol.

---

**VERDICT: REJECT**

---

**Overall Assessment**

This admin-post handler has two critical and independently exploitable failures: a completely unsanitized `$_POST['type']` value interpolated directly into SQL, and authorization enforced only by a nonce with no capability check. Either flaw alone justifies rejection. Three major issues compound the risk: `$_POST['term']` passes through `sanitize_text_field()` but remains SQL-injectable; `$row->note_html` is rendered raw; and the missing `wp_unslash()` call silently corrupts sanitization results. The function cannot ship as written.

---

**Pre-commitment Predictions**

Before line-by-line review, these failures were predicted:

1. `$type` completely unvalidated — **confirmed**
2. Both variables SQL-injectable via string interpolation — **confirmed**
3. `wp_unslash()` missing before sanitization — **confirmed**
4. No `current_user_can()` check — **confirmed**
5. Output escaping absent or wrong for heading and attribute contexts — **confirmed**
6. `note_html` rendered without `wp_kses_post()` or equivalent — **confirmed**

All six materialized. The pre-commitment round identified the complete failure surface.

---

**Critical Findings**

**C1 — SQL Injection via `$type` (no sanitization, direct interpolation)**

- **Path**: POST to `wp-admin/admin-post.php`, action `acme_search_notes`
- **Caller capability**: Any logged-in user who can generate a valid nonce for `acme-search-notes`. WordPress nonces are user-session-specific; a subscriber can call `wp_create_nonce('acme-search-notes')` from any page their session loads. `admin-post.php` is accessible to all authenticated users by WordPress design.
- **Data controlled**: The full SQL fragment in `WHERE note_type = '$type'`
- **Payload example**: `$_POST['type'] = "' UNION SELECT user_login,user_pass FROM wp_users-- "`
- **Rendered query**: `WHERE note_type = '' UNION SELECT user_login,user_pass FROM wp_users-- '`
- **Impact**: Full read of `wp_users` (login names, password hashes, emails). On shared hosting where the MySQL user holds `FILE` privilege, potential out-of-band file write. `get_results()` silently executes the injected statement.
- **Violated boundary**: `$_POST['type']` reaches the query with zero processing — no `wp_unslash()`, no `sanitize_key()`, no allowlist, no `$wpdb->prepare()`.
- **Missing guard**: `$wpdb->prepare()` with a `%s` placeholder **and** an allowlist validation that kills the request before the query fires if `$type` is not a known type.

---

**C2 — Authorization by Nonce Only (missing capability check)**

- **Path**: Same endpoint
- **Caller capability**: Any authenticated WordPress user (subscriber role or above)
- **How**: `check_admin_referer()` verifies CSRF origin — that the nonce was issued to the current session. It does **not** verify the user's role or capability. A subscriber who loads any front-end or dashboard page can execute `wp_create_nonce('acme-search-notes')` in their browser console and POST a valid request.
- **Impact**: Subscribers and contributors can search all editorial note data intended only for editors or admins. Combined with C1, they can exfiltrate the entire database.
- **Violated boundary**: "Hidden-field authorization" — UI gatekeeping (presumably only admins see the form) substitutes for server-side enforcement.
- **Missing guard**: `current_user_can( 'edit_posts' )` — or a more restrictive capability — checked **before** the nonce, so unauthorized callers are rejected at the capability gate and never reach nonce evaluation.

---

**Major Findings**

**M1 — SQL Injection via `$term` (`sanitize_text_field` is not SQL sanitization)**

`sanitize_text_field()` removes HTML tags and collapses whitespace. It does **not** escape SQL metacharacters. After sanitization, `O'Brien` remains `O'Brien`. A term like `%' UNION SELECT 1,user_pass FROM wp_users-- ` retains its quotes and injects cleanly into the LIKE clause.

Missing guard: `$wpdb->prepare()` binding `'%' . $wpdb->esc_like( $term ) . '%'` as the LIKE value. `$wpdb->esc_like()` escapes the literal `%` and `_` wildcard characters within the search term; `prepare()` then handles quoting.

---

**M2 — Missing `wp_unslash()` Before Sanitization**

WordPress applies `addslashes()` to all superglobal input via `wp_magic_quotes()` at bootstrap. `sanitize_text_field( $_POST['term'] )` receives the already-slashed value, producing corrupted output for any input containing apostrophes or backslashes: `it's` becomes `it\'s` in the heading.

Missing guard: `sanitize_text_field( wp_unslash( $_POST['term'] ) )`. The same applies to `$_POST['type']` before allowlist comparison.

---

**M3 — `$row->note_html` Rendered Without Escaping**

`note_html` is echoed directly as the `innerHTML` of `<article>`. If any stored note contains `<script>`, `<iframe>`, or event-handler attributes — whether from prior injection through C1, from an insufficiently-guarded insert path not shown here, or from direct database manipulation — this produces stored XSS in the admin context, where `HttpOnly` cookies and session tokens are present.

Per the review boundary: stripping all markup with `esc_html()` is wrong if the product intent is to preserve safe rich text. The correct guard is `wp_kses_post( $row->note_html )`, which preserves `<strong>`, `<em>`, and standard inline elements while stripping `<script>`, `<iframe>`, and all event handler attributes.

---

**Minor Findings**

**m1 — `$term` Not Escaped in HTML Heading Context**

```php
echo '<h1>Results for ' . $term . '</h1>';
```

`sanitize_text_field()` strips tags, so tag-injection XSS is mitigated here. But sanitize functions are for input normalization, not output context. The correct call is `esc_html( $term )`. These are different contracts: `sanitize_*` modifies data for storage; `esc_*` makes data safe for a specific output context.

---

**m2 — `$row->post_id` Not Escaped in Attribute Context**

```php
echo '<article data-note="' . $row->post_id . '">';
```

`post_id` is a database integer, so practical XSS risk is low. The correct call is `esc_attr( $row->post_id )`. The escaping contract for attribute output is `esc_attr()` regardless of expected type — this prevents future breakage if the column type changes and eliminates the class of risk entirely.

---

**What's Missing**

- **PHPUnit tests**: No test coverage for the handler. Minimum needed: (1) subscriber is rejected with 403 before nonce evaluation, (2) an invalid `$type` value is rejected before any query fires, (3) SQL-injectable `$term` returns zero rows and produces no error output, (4) a note containing `<script>` is stripped by `wp_kses_post()`, (5) a note containing `<strong>` survives `wp_kses_post()`.
- **Type allowlist documentation**: The valid domain of `note_type` values is nowhere declared. Even after the fix, the allowlist needs to come from the plugin's schema or a registered constant — not be inlined as magic strings.
- **Audit logging**: Searches against editorial note data should log user ID, timestamp, and query terms for compliance and forensics (`error_log()` to a dedicated log, a custom table, or an action hook for external consumers).
- **Threat model in plugin header**: No documentation of intended user roles, data sensitivity of `acme_notes`, or trust boundaries. A future maintainer has no signal about what this function is allowed to expose.

---

**Multi-Perspective Notes**

- **Performance (not a security issue)**: The leading-wildcard LIKE pattern (`'%$term%'`) cannot use a B-tree index on `note_html`. This is a correctness concern at scale — not a security finding — but worth noting for any future optimization work.
- **Data integrity**: No existence check for `{$wpdb->prefix}acme_notes` before querying. A deactivated-but-not-uninstalled state produces a silent PHP notice rather than a handled error.

---

**Exploitability Notes**

C1 is exploitable by any authenticated user who knows the action name (readable from the plugin source) and can generate a same-session nonce. C2 allows lower-privilege users to reach the query without needing C1 — they can dump all notes via legitimate search terms. Combined, a subscriber can both read all notes and exfiltrate the entire database via UNION injection. M3 is exploitable if any note row was stored with unsafe HTML, which C1 makes retroactively possible: a prior request could have injected a note containing a stored XSS payload.

---

**Verdict Justification**

**REJECT.** Two independently critical paths are present and neither requires elevated privilege to trigger. The nonce check is functional as a CSRF guard but is not authorization. No output-escaping fix addresses the entry-point failures. The function must be fully rewritten before any production or staging deployment.

---

**Remediation Guide**

```php
add_action( 'admin_post_acme_search_notes', 'acme_search_notes' );
function acme_search_notes() {
    global $wpdb;

    // 1. Capability check BEFORE nonce — fail-fast on unauthorized callers.
    if ( ! current_user_can( 'edit_posts' ) ) {
        wp_die( esc_html__( 'You do not have permission to perform this action.', 'acme' ), 403 );
    }

    // 2. Nonce verification (CSRF guard, runs after capability is confirmed).
    check_admin_referer( 'acme-search-notes' );

    // 3. wp_unslash() before sanitization; sanitize_text_field for input normalization.
    $term = sanitize_text_field( wp_unslash( $_POST['term'] ?? '' ) );

    // 4. Validate $type against a closed allowlist — kill the request before any query.
    $allowed_types = [ 'internal', 'editorial', 'public' ]; // replace with canonical source
    $type          = sanitize_key( wp_unslash( $_POST['type'] ?? '' ) );
    if ( ! in_array( $type, $allowed_types, true ) ) {
        wp_die( esc_html__( 'Invalid note type.', 'acme' ), 400 );
    }

    // 5. Prepared query: %s for type, esc_like() + %s for LIKE wildcard search.
    $rows = $wpdb->get_results(
        $wpdb->prepare(
            "SELECT post_id, note_html
             FROM {$wpdb->prefix}acme_notes
             WHERE note_type = %s
               AND note_html LIKE %s",
            $type,
            '%' . $wpdb->esc_like( $term ) . '%'
        )
    );

    // 6. Context-correct escaping throughout.
    echo '<div class="wrap">';
    printf( '<h1>%s %s</h1>', esc_html__( 'Results for', 'acme' ), esc_html( $term ) );
    foreach ( $rows as $row ) {
        printf(
            '<article data-note="%s">%s</article>',
            esc_attr( $row->post_id ),
            wp_kses_post( $row->note_html )   // preserves safe markup, strips script/iframe/events
        );
    }
    echo '</div>';
}
```

**Verification checklist:**

| Test | Expected result |
|---|---|
| Subscriber POST with valid own nonce | 403 before nonce check |
| `$_POST['type'] = 'malicious'` | `wp_die()` at step 4, no query executed |
| `$_POST['term'] = "' UNION SELECT ..."` | Bound as literal string by `prepare()`, zero rows returned |
| `$_POST['term'] = "it's"` with `wp_unslash()` | Displays correctly as `it's` in heading |
| Note row containing `<script>alert(1)</script>` | `wp_kses_post()` strips script tag, safe output |
| Note row containing `<strong>bold</strong>` | Preserved through `wp_kses_post()` |

---

**Open Questions**

1. **Correct capability gate**: `edit_posts` is used above as a reasonable default for editorial data. The real answer depends on who `acme_notes` is intended for — if only administrators should search notes, `manage_options` or a custom capability is more appropriate.
2. **Provenance of `note_html`**: Is this column always plugin-controlled (safe by construction), or can it contain user-submitted content? If user-submitted, `wp_kses_post()` is the minimum; a tighter `wp_kses()` call with a custom allowlist may be warranted depending on what markup the feature legitimately needs.
3. **Prior injection exposure**: C1 was present before this review. Any `note_html` rows inserted via a similarly unguarded insert path should be audited — stored XSS payloads may already be in the table.
4. **Canonical `$type` domain**: The allowlist in the remediation uses placeholder values. The real set should come from the plugin's own schema constants or a `get_option()` call — not be inlined without documentation.
