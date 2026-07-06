# REST, Abilities, and Interactivity APIs: AMBIGUOUS_TRADEOFF

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Choose and review REST routes, hooks, cron, Interactivity API, Abilities API, and progressive enhancement boundaries.
Fixture tier: The request is underspecified and should trigger clarifying assumptions and tradeoff framing.

Scenario summary: A donation calculator could use the Interactivity API, a small React block, or plain server-rendered forms.

Artifact under review:
- The calculator needs instant feedback, works in campaign landing pages, and must remain usable with limited JavaScript.
- The theme is block-based and already loads minimal front-end JavaScript.
- The team wants maintainability over novelty but is curious about the Interactivity API.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Compares Interactivity API, hydrated React, and server-rendered fallback against constraints.
- Asks about browser support, validation, analytics, and editor preview needs.
- Recommends a proof path rather than novelty-driven adoption.

A weak or unsafe response likely:
- Chooses Interactivity API solely because it is WordPress-native.
- Ignores no-JS behavior.
- Defaults to a full React app without bundle/performance reasoning.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the REST, Abilities, and Interactivity APIs domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
