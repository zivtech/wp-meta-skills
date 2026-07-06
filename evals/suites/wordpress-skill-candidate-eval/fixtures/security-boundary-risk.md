# Security: HAS_RISK

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Assess capabilities, nonces, sanitization, escaping, SQL, REST, uploads, and exploitability.
Fixture tier: The artifact includes non-obvious WordPress risks that a strong skill should find and calibrate.

Scenario summary: An admin-ajax handler updates membership status and accepts rich text from POST data.

Artifact under review:
- The handler is registered for wp_ajax_nopriv_update_member_status.
- It reads $_POST["member_id"] and $_POST["bio_html"] directly, interpolates member_id into a $wpdb query, and echoes bio_html in the admin screen.
- The only check is a hidden form field named is_admin set to 1.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Flags unauthenticated mutation, missing nonce/capability checks, SQL injection, and stored XSS risk.
- Prioritizes exploitability and gives WordPress-native remediations.
- Requires tests for unauthorized requests and escaping.

A weak or unsafe response likely:
- Only recommends sanitize_text_field everywhere.
- Misses wp_ajax_nopriv mutation risk.
- Downplays stored XSS because the screen is in wp-admin.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Security domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
