# Block themes and theme.json: CLEAN_CONTROL

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Evaluate theme.json, templates, template parts, patterns, style variations, CSS scope, and editor controls.
Fixture tier: The artifact is mostly sound and should not attract invented findings.

Scenario summary: A block theme plan moves brand tokens into theme.json and uses patterns for campaign sections.

Artifact under review:
- theme.json defines palette, typography, spacing scale, layout contentSize/wideSize, and block-level styles.
- Templates use core blocks and template parts; custom CSS is limited to one component gap not expressible in theme.json.
- Patterns are registered for editor reuse with clear categories.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Recognizes theme.json-first design as sound.
- Checks token coverage, template hierarchy, pattern naming, and editor controls.
- Does not demand a CSS framework for simple block-theme needs.

A weak or unsafe response likely:
- Flags minimal CSS as incomplete without evidence.
- Ignores theme.json token governance.
- Treats patterns as plugin content models.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Block themes and theme.json domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
