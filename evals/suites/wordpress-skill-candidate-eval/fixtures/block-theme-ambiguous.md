# Block themes and theme.json: AMBIGUOUS_TRADEOFF

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Evaluate theme.json, templates, template parts, patterns, style variations, CSS scope, and editor controls.
Fixture tier: The request is underspecified and should trigger clarifying assumptions and tradeoff framing.

Scenario summary: A university network wants one parent block theme with school-specific style variations and occasional child-theme overrides.

Artifact under review:
- Schools share layout and accessibility requirements but differ in palettes and typography.
- Some schools want local templates for admissions pages.
- The central team wants updates to flow without overwriting local brand work.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Compares style variations, child themes, patterns, and per-site governance.
- Identifies update, token, and template override risks.
- Asks which variations are brand tokens vs structural divergence.

A weak or unsafe response likely:
- Rejects child themes categorically in block themes.
- Assumes style variations can solve structural template differences.
- Ignores update governance across sites.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Block themes and theme.json domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
