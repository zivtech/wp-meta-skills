# REST, Abilities, and Interactivity APIs: HAS_RISK

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Choose and review REST routes, hooks, cron, Interactivity API, Abilities API, and progressive enhancement boundaries.
Fixture tier: The artifact includes non-obvious WordPress risks that a strong skill should find and calibrate.

Scenario summary: A proposal uses experimental API language to expose AI actions that can update posts from a public route.

Artifact under review:
- The draft references the Abilities API without confirming WordPress 6.9+ support or plugin dependency.
- It proposes `wp_ai_client_prompt()` for draft rewrites without confirming WordPress 7.0+ support, Connectors configuration, or a guarded fallback path.
- It mentions MCP exposure but does not identify `wordpress/mcp-adapter`, `mcp_adapter_init`, ability discovery, or ability execution boundaries.
- A public REST endpoint accepts an action name and post ID, then runs wp_update_post.
- The response includes raw model prompts and stores user identifiers in transients.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Flags unsupported/version-dependent API claims, unauthenticated mutation, privacy leakage, and missing capability checks.
- Separates viable REST design from Abilities API integration and requires `wp_register_ability()` on `wp_abilities_api_init` with `input_schema`, `output_schema`, `execute_callback`, and `permission_callback`.
- Requires `wp_ai_client_prompt()` and Connectors use to stay server-side, handle `WP_Error` via `is_wp_error()`, avoid raw prompt leakage, and confirm `wp_connectors_init` or provider availability only when provider plugins are in scope.
- Treats MCP as an adapter/export boundary: name `wordpress/mcp-adapter`, ability discovery/execution tools, and which abilities are exposed rather than exposing arbitrary REST actions.
- Requires version/dependency proof and security review before executor work.

A weak or unsafe response likely:
- Accepts future API names as stable.
- Misses public post mutation.
- Ignores prompt/identifier leakage.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the REST, Abilities, and Interactivity APIs domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
