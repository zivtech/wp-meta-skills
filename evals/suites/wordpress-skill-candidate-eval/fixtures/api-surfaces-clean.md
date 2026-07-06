# REST, Abilities, and Interactivity APIs: CLEAN_CONTROL

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Choose and review REST routes, hooks, cron, Interactivity API, Abilities API, and progressive enhancement boundaries.
Fixture tier: The artifact is mostly sound and should not attract invented findings.

Scenario summary: A faceted resource finder uses a public REST route for published content and progressive enhancement for filters.

Artifact under review:
- Server-rendered initial results work without JavaScript.
- A REST route returns paginated published resources with sanitized query args.
- Client code enhances filters and preserves URLs for sharing.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Recognizes progressive enhancement and REST route as appropriate.
- Checks pagination, sanitization, caching, and accessibility of filter state.
- Avoids forcing admin-ajax for public reads.

A weak or unsafe response likely:
- Treats all REST routes as overengineering.
- Ignores non-JS baseline.
- Misses pagination and cache semantics.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the REST, Abilities, and Interactivity APIs domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
