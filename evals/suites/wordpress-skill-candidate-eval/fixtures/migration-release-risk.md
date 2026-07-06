# Migrations and release readiness: HAS_RISK

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Handle migrations, page-builder conversion, redirects, media, data validation, rollback, and plugin-directory readiness.
Fixture tier: The artifact includes non-obvious WordPress risks that a strong skill should find and calibrate.

Scenario summary: A launch handoff proposes direct production SQL updates to convert shortcodes and rewrite domains.

Artifact under review:
- The command examples include UPDATE wp_posts SET post_content = REPLACE(...) on production.
- There is no redirect map, no media validation, and no plan for page-builder shortcodes that remain inside reusable blocks.
- The plugin intended for release lacks readme.txt, stable tag, assets, and license notes for bundled code.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Blocks destructive production SQL and requires dry-run/staging/backups.
- Flags shortcode leftovers, redirect gaps, media validation, and plugin-directory readiness issues.
- Provides safer WP-CLI/search-replace dry-run or scripted migration alternatives.

A weak or unsafe response likely:
- Approves SQL because it is faster.
- Misses plugin release metadata.
- Ignores redirects and shortcode leftovers.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Migrations and release readiness domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
