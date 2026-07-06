# Plugin architecture: AMBIGUOUS_TRADEOFF

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Design or review plugin boundaries, hooks, lifecycle, settings, and release packaging.
Fixture tier: The request is underspecified and should trigger clarifying assumptions and tradeoff framing.

Scenario summary: A team is deciding whether a compliance banner belongs in an mu-plugin, a normal plugin, or the block theme.

Artifact under review:
- The banner must appear on all subsites and support editor-controlled text.
- Legal wants emergency override capability outside normal release cycles.
- The theme team worries a plugin will make layout integration harder.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Compares mu-plugin reliability, normal plugin update flow, and theme presentation tradeoffs.
- Separates compliance enforcement from editable content and presentation.
- Asks about multisite governance, release permissions, and failure behavior.

A weak or unsafe response likely:
- Declares mu-plugin always correct because the banner is global.
- Ignores editor control and release cadence.
- Moves legal compliance into a theme template without fallback.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Plugin architecture domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
