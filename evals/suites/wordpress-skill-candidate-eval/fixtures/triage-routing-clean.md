# Triage and routing: CLEAN_CONTROL

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Route a WordPress request to the right planner, executor, or critic surface without inventing implementation work.
Fixture tier: The artifact is mostly sound and should not attract invented findings.

Scenario summary: A client asks whether a staff directory should be built as a plugin, a block pattern, or a theme template change.

Artifact under review:
- The site already runs a custom block theme and has no staff content type yet.
- Editors need sortable staff profiles, department filters, headshots, and reusable profile cards.
- The request is discovery-stage only; no code has been written and there is no production incident.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Routes content modeling to wordpress-planner.content-model before implementation.
- Separates plugin-owned data from theme-owned presentation and block-pattern layout.
- Identifies validation questions without escalating to security or performance crisis language.

A weak or unsafe response likely:
- Treats the request as a theme-only task or recommends editing template files first.
- Uses Drupal entity vocabulary as if it were WordPress-native.
- Flags imagined security issues without evidence.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Triage and routing domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
