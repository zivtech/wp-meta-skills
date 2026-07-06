# Security: CLEAN_CONTROL

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Assess capabilities, nonces, sanitization, escaping, SQL, REST, uploads, and exploitability.
Fixture tier: The artifact is mostly sound and should not attract invented findings.

Scenario summary: A REST endpoint exposes public event search and an authenticated endpoint updates event metadata.

Artifact under review:
- The public search route has permission_callback set to __return_true but only returns published event titles and permalinks.
- The update route requires current_user_can("edit_post", $event_id), validates a REST nonce via apiFetch, sanitizes text fields, and escapes output in render callbacks.
- Database lookups use WP_Query rather than interpolated SQL.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Does not flag the read-only public route as vulnerable solely because it uses __return_true.
- Confirms the authenticated route has capability, nonce, sanitization, and escaping boundaries.
- Notes remaining assumptions about private fields and rate limits.

A weak or unsafe response likely:
- Claims all __return_true REST routes are critical vulnerabilities.
- Ignores capability checks on mutation.
- Fails to distinguish public read from authenticated write.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Security domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
