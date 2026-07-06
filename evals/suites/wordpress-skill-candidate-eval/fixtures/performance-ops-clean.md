# Performance and operations: CLEAN_CONTROL

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Review query cost, caching, autoloaded options, enqueue strategy, media, cron, hosting constraints, and safe validation.
Fixture tier: The artifact is mostly sound and should not attract invented findings.

Scenario summary: A listing page uses WP_Query with taxonomy filters, no_found_rows where pagination is not needed, and cached remote API data.

Artifact under review:
- Scripts are enqueued only for the listing block.
- External API results are refreshed by scheduled event and stored with expiration.
- Object cache is available on hosting and images use core responsive image handling.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Recognizes sound performance patterns.
- Checks query indexes, cache invalidation, asset conditions, and observability.
- Avoids recommending premature custom tables.

A weak or unsafe response likely:
- Flags any WP_Query as slow without data.
- Ignores cache invalidation.
- Recommends disabling core responsive images.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Performance and operations domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
