**Scope**

This is a smoke evaluation for `wordpress-security-critic`, not a live audit. I am evaluating whether the candidate response would satisfy the critic contract for a WordPress security review covering:

- Capability checks
- Nonce handling
- Sanitization and escaping
- SQL safety
- REST API permissions
- Upload handling

Assumption: no repository, plugin code, theme code, logs, or runtime configuration were inspected. Any finding must therefore be framed as a review requirement or risk area, not as a confirmed vulnerability.

**WordPress-Specific Decisions**

A valid `wordpress-security-critic` response should expect WordPress-native controls:

- Capability checks should use `current_user_can()` with the narrowest relevant capability, not role-name checks.
- Nonces should be verified with `check_admin_referer()`, `check_ajax_referer()`, or `wp_verify_nonce()` depending on context, but never treated as authorization by themselves.
- Input should be sanitized with appropriate WordPress functions such as `sanitize_text_field()`, `sanitize_key()`, `absint()`, `sanitize_email()`, or `wp_kses_post()` based on expected data shape.
- Output should be escaped at render time with `esc_html()`, `esc_attr()`, `esc_url()`, `wp_kses_post()`, or equivalent context-aware escaping.
- SQL should use `$wpdb->prepare()` for dynamic values and avoid interpolating request data into queries.
- REST routes should define `permission_callback`; public routes should explicitly return `true` only when intentionally public.
- Upload handling should use WordPress upload APIs and validate MIME/type, file size, extension, and user capability.

**Risks**

The highest-risk areas in this fixture are authorization bypass, stored XSS, SQL injection, and unsafe file upload.

Specific risks to call out:

- Nonce-only protection is insufficient if capability checks are missing.
- Sanitization does not replace escaping; both are needed at different boundaries.
- `$wpdb->prepare()` must be used correctly, including placeholders for all dynamic values.
- REST endpoints without meaningful `permission_callback` can expose privileged operations.
- Upload handlers can become remote code execution or stored XSS paths if MIME validation and capability checks are weak.

**Verification**

Safe verification should be limited to review and test-oriented steps, for example:

- Inspect relevant PHP handlers, REST route registration, AJAX callbacks, admin actions, and upload flows.
- Add or review PHPUnit/integration tests for unauthorized users, invalid nonces, malformed input, SQL parameters, and blocked upload types.
- Confirm escaping in templates and admin output contexts.
- Confirm REST routes reject unauthenticated or underprivileged users where appropriate.

Avoid unsafe production commands, destructive database actions, or claims of benchmark/security scan results unless actual evidence is provided.

**Open Questions**

- Which code surface is in scope: plugin, theme, mu-plugin, REST API, admin screens, AJAX, upload endpoint, or all of the above?
- Are any REST routes intentionally public?
- What user roles/capabilities are expected to access each privileged action?
- What file types are uploads supposed to allow?
- Is the next step a planner handoff, executor fix, or critic review pass?

Downstream handoff: if issues are confirmed, route to a WordPress security planner for remediation design, a WordPress executor for scoped fixes, and back to `wordpress-security-critic` for review.