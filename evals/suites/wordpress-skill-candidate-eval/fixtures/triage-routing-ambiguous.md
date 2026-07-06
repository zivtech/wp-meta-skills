# Triage and routing: AMBIGUOUS_TRADEOFF

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Route a WordPress request to the right planner, executor, or critic surface without inventing implementation work.
Fixture tier: The request is underspecified and should trigger clarifying assumptions and tradeoff framing.

Scenario summary: A multisite client wants one workflow for campaign landing pages that sometimes need custom blocks and sometimes only need editor patterns.

Artifact under review:
- Three subsites share a parent block theme but have different brand constraints.
- Editors want autonomy, while governance wants reusable patterns and limited custom code.
- The client asks whether this should be a network plugin, theme variation, pattern library, or training issue.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Frames network plugin, child/theme variation, synced pattern, and training tradeoffs without forcing one answer too early.
- Identifies governance, capability, rollout, and maintenance questions.
- Routes design-system decisions separately from block/plugin execution.

A weak or unsafe response likely:
- Chooses a single implementation before clarifying governance and multisite constraints.
- Ignores editor permissions and rollout across subsites.
- Treats multisite as a generic hosting concern.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Triage and routing domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
