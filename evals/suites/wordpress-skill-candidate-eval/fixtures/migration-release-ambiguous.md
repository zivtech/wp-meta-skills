# Migrations and release readiness: AMBIGUOUS_TRADEOFF

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Handle migrations, page-builder conversion, redirects, media, data validation, rollback, and plugin-directory readiness.
Fixture tier: The request is underspecified and should trigger clarifying assumptions and tradeoff framing.

Scenario summary: A client needs either a one-time importer or a six-month sync from a legacy CMS while editors gradually rebuild pages.

Artifact under review:
- The legacy CMS remains the source of truth for some programs during transition.
- Editors want to improve content in WordPress before final cutover.
- The team is unsure whether to build idempotent sync, one-time import scripts, or manual migration batches.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Compares one-time import, recurring sync, and manual batch tradeoffs.
- Identifies source-of-truth, conflict resolution, IDs, redirects, and freeze-window questions.
- Suggests pilot migration and acceptance metrics before choosing.

A weak or unsafe response likely:
- Chooses one-time import without source-of-truth analysis.
- Ignores editor changes during transition.
- Assumes redirects can wait until launch week.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Migrations and release readiness domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
