# Block themes and theme.json: HAS_RISK

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Evaluate theme.json, templates, template parts, patterns, style variations, CSS scope, and editor controls.
Fixture tier: The artifact includes non-obvious WordPress risks that a strong skill should find and calibrate.

Scenario summary: A block theme uses broad CSS overrides and removes editor controls to force pixel-perfect layouts.

Artifact under review:
- style.css contains .wp-site-blocks * selectors and !important overrides for spacing and colors.
- theme.json disables custom color, spacing, and typography controls globally.
- Template parts hardcode campaign-specific content that editors must change monthly.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Flags editor UX, maintainability, and global-style collision risks.
- Suggests moving reusable values into theme.json and patterns, with scoped CSS only where needed.
- Calibrates that disabling controls can be valid only with documented governance.

A weak or unsafe response likely:
- Treats pixel-perfect control as automatically desirable.
- Misses hardcoded monthly content in template parts.
- Opposes all editor-control restrictions without governance nuance.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Block themes and theme.json domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
