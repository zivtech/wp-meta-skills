# Block development: HAS_RISK

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Handle block.json, attributes, saved markup, dynamic render, deprecations, and editor/runtime parity.
Fixture tier: The artifact includes non-obvious WordPress risks that a strong skill should find and calibrate.

Scenario summary: A static Alert block changes saved markup and attribute names after launch without a deprecation path.

Artifact under review:
- Version 1 saved <section class="alert"><h2>{title}</h2><p>{body}</p></section>.
- Version 2 renames body to content, removes h2, and changes wrapper classes.
- No deprecated block version or migration is defined, and the editor fetches private preview data from a custom REST route.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Flags block validation breakage and missing deprecated migration.
- Checks REST permission boundary for preview data.
- Proposes deprecations, transforms, fixtures with existing saved content, and editor/front-end parity tests.

A weak or unsafe response likely:
- Treats block markup changes as harmless CSS refactors.
- Misses private preview data exposure.
- Suggests bulk editing post_content without backup.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Block development domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
