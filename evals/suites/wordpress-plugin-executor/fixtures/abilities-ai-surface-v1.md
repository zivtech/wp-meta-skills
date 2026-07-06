# Modern Surface Fixture: wordpress-plugin-executor

Scenario: Generate a materializable plugin implementation packet from this approved spec.

## Approved Planner Spec

Build a minimal WordPress plugin named **Acme Editorial Assistant**.

- Plugin slug: `acme-editorial-assistant`
- Text domain: `acme-editorial-assistant`
- Target: WordPress 7.0+, PHP 8.1+
- Generated files:
  - `acme-editorial-assistant/acme-editorial-assistant.php`
  - `acme-editorial-assistant/readme.txt`
- Behavior:
  - Register a read-only ability named `acme-editorial-assistant/get-post-summary` on `wp_abilities_api_init` using `wp_register_ability()`.
  - The ability must include `label`, `description`, `category`, `input_schema`, `output_schema`, `execute_callback`, and `permission_callback`.
  - If the plugin uses a custom ability category, register it first with `wp_register_ability_category()` on `wp_abilities_api_categories_init`. If it uses a core category, name that category explicitly in code and verification notes.
  - The input schema accepts an integer `post_id` and disallows additional properties.
  - The output schema returns an object with `post_id`, `title`, and `summary` string fields.
  - The permission callback must require `current_user_can( 'edit_post', $post_id )` when a post ID is supplied.
  - The execute callback must read an existing published or editable post and return a deterministic excerpt-based summary. Do not call external AI providers from the ability callback.
  - Provide a separate helper function that demonstrates a guarded `wp_ai_client_prompt()` call for future draft-summary generation. It must check `function_exists( 'wp_ai_client_prompt' )`, require `current_user_can( 'edit_post', $post_id )`, handle `is_wp_error()`, and return `WP_Error` when unsupported or unauthorized.
  - Name `wp_connectors_init` in verification notes as the provider-configuration boundary. Do not register a provider or store credentials.
- Non-goals:
  - Do not generate custom MCP Adapter server code. The packet may mention `wordpress/mcp-adapter` and ability discovery/execution as a verification boundary only.
  - Do not add REST routes, AJAX endpoints, admin-post handlers, cron, SQL, uploads, remote HTTP calls, build tooling, provider plugins, credentials, or production write commands.
  - Do not invent additional files beyond the requested plugin bootstrap and readme.

## Output Requirements

The candidate output must use the `wordpress-plugin-executor` headings and be directly materializable:

- The first non-empty line must be `## Spec Conformance`.
- Do not include phase transcripts, process narration, quality tables, emoji, or prefaces.
- Use exactly these top-level headings, in this exact order, with no renamed synonyms and no extra top-level headings:
  - `## Spec Conformance`
  - `## Generated File Map`
  - `## Implementation Packets`
  - `## Security Notes`
  - `## Deviation Log`
  - `## Verification Notes`
  - `## Critic Handoff`
- Under `## Generated File Map`, list each generated file as an exact relative path in code spans, including `acme-editorial-assistant/acme-editorial-assistant.php` and `acme-editorial-assistant/readme.txt`.
- Under `## Implementation Packets`, each generated file must be introduced by `### relative/path.ext`.
- Each file heading must be followed immediately by one fenced code block containing the complete file contents.
- Generated PHP must be WPCS-oriented before runtime proof: include a file-level `@package` tag, use WordPress long `array()` syntax instead of short `[]` arrays, and format multiline arrays for PHPCS/WPCS readability.
- The packet must name exact WordPress APIs and verification surfaces: `wp_register_ability()`, `wp_abilities_api_init`, `label`, `description`, `category`, `wp_register_ability_category()`, `wp_abilities_api_categories_init`, `input_schema`, `output_schema`, `execute_callback`, `permission_callback`, `current_user_can()`, `wp_ai_client_prompt()`, `is_wp_error()`, `WP_Error`, `wp_connectors_init`, `wordpress/mcp-adapter`, PHPCS/WPCS, PHPUnit where tests exist, WP-CLI smoke commands, and Plugin Check.
- The handoff must name `wordpress-security-critic` and `wordpress-critic`.
- Verification notes must explicitly state whether commands were run. If they were not run, say that WPCS, PHPUnit, Plugin Check, wp-env, MCP Adapter discovery/execution, AI Client runtime calls, browser/editor behavior, and release readiness are not claimed.
