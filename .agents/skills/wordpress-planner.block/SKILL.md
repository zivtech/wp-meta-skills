---
name: wordpress-planner.block
type: planner
model: Codex-fable-5
description: Plan Block Editor blocks, block.json metadata, attributes, serialization, dynamic rendering, Interactivity API, and deprecations.
---

# WordPress Block Planner

## When to Use

Use for new or existing Block Editor blocks, block.json changes, editor controls, saved markup, dynamic rendering, render.php, viewScript/viewScriptModule, Interactivity API, block supports, transforms, or deprecations.

This planner owns the definition of a repository-defined custom block: its `block.json`, attributes, editor and frontend assets, `save()`/`render.php`/`render_callback` contract, and saved-content compatibility. It does not own bulk source-to-block transformation, migrated `post_content` serialization, unsupported-source accounting, import idempotence, or migration semantic/editor/frontend proof; route those concerns to `wordpress-planner.migration`.

## Protocol

Phase 0 - Block boundary: classify static, dynamic, hybrid, variation, pattern, transform, or Interactivity API work, name existing content compatibility risk, and confirm that the request is a custom-block definition rather than a source migration.
    Phase 1 - Inventory and tooling: inspect namespace, target path, existing block.json, attributes, supports, saved markup, render.php/render_callback, @wordpress/scripts or equivalent build tooling, WP/PHP targets, dependencies, and fixtures.
    Phase 2 - User/editor workflow: define inserter behavior, inspector controls, editing states, validation recovery, preview needs, permissions, and accessibility expectations.
    Phase 3 - Metadata and attributes: specify block.json fields, apiVersion, supports, attribute sources, defaults, schema, selectors, context, usesContext, variations, styles, and i18n.
    Phase 4 - Render and interaction plan: decide save vs render.php/render_callback, server data, REST routes, viewScript/viewScriptModule, Interactivity API stores, hydration, escaping, caching, and error states.
    Phase 5 - Compatibility plan: define deprecated block versions, attribute migrations, transforms, fixtures with existing saved content, post_content impact, and recovery strategy. Here migration means the block's own saved-content compatibility, not CMS-to-WordPress transformation.
    Phase 6 - Security/performance/accessibility: map REST permission callbacks, private preview data, dynamic render cost, asset loading, keyboard behavior, landmarks, and ARIA needs.
    Phase 7 - Assumption register and alternatives: compare static/dynamic/hybrid approaches and note fragile dependencies.
    Phase 8 - Test strategy: define block validation, editor smoke, frontend smoke, fixture snapshots, deprecation tests, REST permission tests, and performance checks against the exact block name, selector, attributes, saved markup, and visible output.
    Phase 9 - Executor and critic handoff.

## Hard Gates

- Attribute schema and saved markup must be explicit.
    - Emit these affirmative decision records in their owning sections: `Block identity:` and `Primary serialization:` in Block Scope; `Metadata file:`, `Attributes:`, and `Saved markup:` in Metadata And Attribute Plan; `Render surface:` and `Failure behavior:` in Render And Interaction Plan; `Compatibility decision:` and `Saved-content fixture:` in Compatibility And Migration Plan; and `Editor oracle:` and `Frontend oracle:` in Test Strategy. `Primary serialization:` is `static`, `dynamic`, or `hybrid`; `Attributes:` is `none` or `schema`; `Saved markup:` is `empty`, `self-closing`, `html`, or `parent-owned`; `Render surface:` is `save()`, `render.php`, `render_callback`, `save()+render.php`, or `save()+render_callback`; `Failure behavior:` is `return-empty`, `fallback`, `recover`, `throw`, `error-object`, or `log-and-return-empty`; `Compatibility decision:` is `new-contract`, `unchanged`, `deprecate`, `migrate`, `transform`, or `accept-breakage`; and the fixture/editor/frontend values are exactly `required`. Interactivity API, variation, pattern, and transform are separate facets, not serialization modes. Keep explanation in prose, not in record values.
    - Concrete browser records are also required in Test Strategy: `Editor oracle method: playwright-insert-save-reload`, `Editor oracle block:` with the exact block identity, `Frontend oracle method: playwright-selector-visible-text`, `Frontend oracle selector:` with the identity-derived `.wp-block-*` selector, and `Frontend expected text:` with the exact visible plain text.
    - Keep the ownership boundary explicit: this planner owns custom-block definition, assets, save/render behavior, and compatibility; `wordpress-planner.migration` owns source mapping, serialization, unsupported-content accounting, idempotence, and migration proof.
    - If a migration requires a new custom block, accept only the bounded custom-block contract after the migration planner defines the source mapping and semantic oracle. Do not absorb the importer or bulk content transformation into the block plan.
    - Existing repository-owned migration code must be revised in its owning repository, not regenerated wholesale or handed to `wordpress-plugin-executor` for replacement.
    - Dynamic blocks must define escaping, permissions, cache behavior, and render failure behavior.
    - Breaking saved markup or attribute changes require deprecated versions, transforms, migration strategy, or an explicit acceptance of validation breakage.
    - Do not recommend blind post_content rewrites without backup, dry run, fixtures, and rollback.
    - Editor and frontend behavior must be planned together.
    - Verification must cover existing saved-content fixtures, editor smoke, frontend smoke, npm/build checks, and REST permission checks when data leaves the editor.

## Exact API And Verification Contract

Every recommendation, decision, remediation, and verification handoff must name the concrete WordPress surface it relies on. When relevant, include exact functions, hooks, files, packages, or commands instead of category labels: `current_user_can()`, `check_admin_referer()`/`check_ajax_referer()`/`wp_verify_nonce()`, `register_rest_route` `permission_callback` or `WP_REST_Controller` permission methods, `$wpdb->prepare()`, `sanitize_key()`/`sanitize_text_field()`/`wp_kses_post()`, `esc_html()`/`esc_attr()`/`esc_url()`/`wp_safe_redirect()`, `wp_handle_upload()`, `block.json`, `register_block_type()`, `render_callback`/`render.php`, deprecated block versions/migrate/transforms, `theme.json`, `register_post_type()`, `register_taxonomy()`, `register_post_meta()`/`register_meta()` with `show_in_rest`/schema/`auth_callback`, `WP_Query` args, `wp_cache_get()`/`wp_cache_set()`, transients with invalidation, `wp_schedule_event()`/`wp_next_scheduled()`/Action Scheduler, `wp_register_ability()`/`wp_abilities_api_init`, `label`/`description`/`category`, `wp_register_ability_category()`/`wp_abilities_api_categories_init`, `input_schema`/`output_schema`, `execute_callback`, `permission_callback`, `@wordpress/abilities`, `@wordpress/core-abilities`, `wordpress/mcp-adapter`, `mcp_adapter_init`, `mcp-adapter-discover-abilities`/`mcp-adapter-execute-ability`, `wp_ai_client_prompt()`, `wp_connectors_init`, Query Monitor, WP-CLI, Plugin Check, PHPCS/WPCS, PHPUnit, and Playwright/editor smoke where applicable. If no exact WordPress API applies, state why and name the verification oracle instead.

## Calibration

Treat uncertainty as design data. Separate observed evidence from assumptions, name negative space, and avoid generic CMS advice or Drupal vocabulary transplants. Do not claim benchmark, release, or current-version status without evidence.

## Failure Modes

Watch for hidden authorization assumptions, unsafe production commands, missing rollback, missing test strategy, cache claims without invalidation, block/theme editor parity gaps, migration responsibilities smuggled into a custom-block spec, unlogged upstream reuse, and unsupported version claims.

## Output Contract

Use these headings:
- `## Block Scope`
- `## Current-State Evidence`
- `## Metadata And Attribute Plan`
- `## Render And Interaction Plan`
- `## Compatibility And Migration Plan`
- `## Security Performance And Accessibility Notes`
- `## Assumption Register`
- `## Test Strategy`
- `## Acceptance Criteria`
- `## Executor Handoff`
- `## Critic Handoff`

The decision-record labels above are part of the saved output contract. Use each
label exactly once at column zero in its owning section and give it an affirmative value; prose
elsewhere does not substitute for the record.

## Provenance

Original Zivtech protocol. Compatible references remain reference-only unless reuse is logged and licensed.
