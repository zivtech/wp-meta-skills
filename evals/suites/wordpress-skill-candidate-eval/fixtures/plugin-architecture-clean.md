# Plugin architecture: CLEAN_CONTROL

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Design or review plugin boundaries, hooks, lifecycle, settings, and release packaging.
Fixture tier: The artifact is mostly sound and should not attract invented findings.

Scenario summary: A plugin plan defines an Events CPT, settings screen, and shortcode-compatible block for legacy pages.

Artifact under review:
- The plan keeps CPT registration, settings, and REST exposure in the plugin, while templates remain in the block theme.
- Settings use register_setting with sanitize callbacks and capability checks.
- Activation flushes rewrite rules once; uninstall removes only plugin-owned options after confirmation.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Recognizes sound plugin ownership and lifecycle choices.
- Checks namespace, text domain, dependency, and release packaging details.
- Avoids demanding a custom table without a scaling reason.

A weak or unsafe response likely:
- Flags plugin ownership as wrong because themes can register CPTs.
- Ignores activation/uninstall lifecycle.
- Invents a need for direct SQL or custom tables.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Plugin architecture domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
