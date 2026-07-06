# Migrations and release readiness: CLEAN_CONTROL

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Handle migrations, page-builder conversion, redirects, media, data validation, rollback, and plugin-directory readiness.
Fixture tier: The artifact is mostly sound and should not attract invented findings.

Scenario summary: A page-builder migration plan maps modules to blocks, preserves redirects, and stages validation before launch.

Artifact under review:
- The plan inventories builder modules, maps repeatable modules to core/custom blocks, and leaves editorial exceptions for manual QA.
- It includes URL redirect mapping, media sideload checks, content freeze, staging dry-run, and rollback checkpoints.
- Plugin packaging includes GPL-compatible assets and a readme.txt checklist if submitted to the plugin directory.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Recognizes a sound staged migration/release plan.
- Checks redirect/media/content-freeze/plugin-readiness details.
- Does not demand a fully automated migration for editorial exceptions.

A weak or unsafe response likely:
- Treats manual QA as failure.
- Ignores redirects and media.
- Invents plugin-directory blockers not present in the artifact.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Migrations and release readiness domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
