# Block development: AMBIGUOUS_TRADEOFF

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Handle block.json, attributes, saved markup, dynamic render, deprecations, and editor/runtime parity.
Fixture tier: The request is underspecified and should trigger clarifying assumptions and tradeoff framing.

Scenario summary: Editors want a Promo block that can either be a reusable pattern or a custom block with analytics metadata.

Artifact under review:
- The visual layout is simple and could be a synced pattern.
- Marketing wants campaign ID, placement taxonomy, and click tracking later.
- Developers are unsure whether analytics metadata justifies a custom block in V1.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Frames pattern-first vs custom-block tradeoffs.
- Identifies metadata, analytics, governance, and editor UX decision points.
- Suggests a staged path that avoids premature custom code while preserving future migration.

A weak or unsafe response likely:
- Builds a custom block solely because the layout repeats.
- Ignores future analytics metadata.
- Assumes synced patterns can carry all structured reporting needs.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Block development domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
