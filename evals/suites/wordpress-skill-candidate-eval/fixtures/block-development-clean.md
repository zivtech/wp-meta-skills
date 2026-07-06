# Block development: CLEAN_CONTROL

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Handle block.json, attributes, saved markup, dynamic render, deprecations, and editor/runtime parity.
Fixture tier: The artifact is mostly sound and should not attract invented findings.

Scenario summary: A dynamic Resource Card block renders server-side from a selected post ID.

Artifact under review:
- block.json defines apiVersion 3, attributes for postId and layout, editorScript/style handles, and supports spacing/color.
- PHP register_block_type points to the build directory and render_callback escapes title, excerpt, and URL.
- The saved markup is minimal because front-end output is dynamic.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Recognizes dynamic-block pattern as sound.
- Checks attribute schema, escaping, editor preview, and asset registration.
- Does not demand serialized saved markup for server-rendered content.

A weak or unsafe response likely:
- Claims minimal save output is invalid.
- Ignores render_callback escaping.
- Confuses block supports with theme.json settings.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Block development domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
