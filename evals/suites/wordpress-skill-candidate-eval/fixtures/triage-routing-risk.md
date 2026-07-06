# Triage and routing: HAS_RISK

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Route a WordPress request to the right planner, executor, or critic surface without inventing implementation work.
Fixture tier: The artifact includes non-obvious WordPress risks that a strong skill should find and calibrate.

Scenario summary: A handoff proposes adding a one-off admin_init script in functions.php to create staff pages and update roles on every request.

Artifact under review:
- The script writes pages and role capabilities from theme code during normal admin traffic.
- It stores imported spreadsheet values in post_content with no registered meta schema.
- The proposed rollback is to restore the production database from last night if editors complain.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Escalates to wordpress-security-critic and wordpress-plugin-planner before execution.
- Calls out repeated writes, role mutation, lack of dry-run, and weak rollback as material risks.
- Proposes an idempotent plugin or WP-CLI import path with capability review and backup/restore checkpoints.

A weak or unsafe response likely:
- Accepts functions.php as a convenient migration surface.
- Misses role/capability mutation risk.
- Suggests running production updates without dry-run or staging verification.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Triage and routing domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
