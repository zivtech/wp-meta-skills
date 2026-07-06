# Plugin architecture: HAS_RISK

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Design or review plugin boundaries, hooks, lifecycle, settings, and release packaging.
Fixture tier: The artifact includes non-obvious WordPress risks that a strong skill should find and calibrate.

Scenario summary: A draft plugin fetches CRM data on every page load, stores a large autoloaded option, and renders admin HTML from callbacks mixed into the main file.

Artifact under review:
- The plugin hooks wp_head to call wp_remote_get without timeout or caching.
- It stores a 2 MB CRM response in an autoloaded option.
- It registers settings but has no sanitize callback, no uninstall path, and no namespaced classes.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Finds runtime network calls, autoload bloat, missing sanitization, and missing uninstall as concrete risks.
- Proposes transients or scheduled sync, non-autoloaded options, and separated admin/render classes.
- Requires staging load checks and rollback plan.

A weak or unsafe response likely:
- Only comments on file organization.
- Misses autoload and remote-call performance risks.
- Suggests adding more hooks without ownership boundaries.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Plugin architecture domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
