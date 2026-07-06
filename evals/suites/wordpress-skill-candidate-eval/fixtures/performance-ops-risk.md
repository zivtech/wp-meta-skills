# Performance and operations: HAS_RISK

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Review query cost, caching, autoloaded options, enqueue strategy, media, cron, hosting constraints, and safe validation.
Fixture tier: The artifact includes non-obvious WordPress risks that a strong skill should find and calibrate.

Scenario summary: A dynamic block performs nested meta queries and uncached HTTP requests during render.

Artifact under review:
- render_callback calls wp_remote_get for every block instance with no timeout.
- The query uses multiple LIKE meta_query clauses over 80,000 posts.
- A 900 KB settings array is stored as an autoloaded option and loaded on every request.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Flags render-path HTTP, meta_query scale risk, and autoload bloat.
- Proposes scheduled sync, indexed taxonomy/meta alternatives, object cache checks, and load testing.
- Requires non-destructive profiling commands and staging verification.

A weak or unsafe response likely:
- Only suggests adding a page cache.
- Misses autoload option size.
- Recommends running UPDATE queries on production.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Performance and operations domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
