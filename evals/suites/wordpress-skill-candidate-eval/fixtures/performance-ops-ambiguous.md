# Performance and operations: AMBIGUOUS_TRADEOFF

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Review query cost, caching, autoloaded options, enqueue strategy, media, cron, hosting constraints, and safe validation.
Fixture tier: The request is underspecified and should trigger clarifying assumptions and tradeoff framing.

Scenario summary: A membership site wants aggressive full-page caching but has logged-in personalization and donation prompts.

Artifact under review:
- Most visitors are anonymous, but logged-in members see personalized calls to action.
- The hosting stack supports edge cache and object cache.
- Marketing wants A/B tests that may vary by campaign cookie.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Frames page cache, fragment/personalization, cookie variance, and object cache tradeoffs.
- Asks for traffic split, cache headers, and acceptance metrics.
- Avoids blanket cache bypass for all logged-in behavior without measurement.

A weak or unsafe response likely:
- Disables full-page cache categorically.
- Ignores cookie-based cache fragmentation.
- Treats object cache as a replacement for page cache.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Performance and operations domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
