---
name: wordpress-planner.content-model
type: planner
model: claude-fable-5
description: Plan WordPress content models using CPTs, taxonomies, meta, ACF/meta boxes, editorial workflow, REST exposure, and search implications.
---

# WordPress Content Model Planner

## When to Use

Use for custom post types, taxonomies, term hierarchies, post meta, ACF field groups, editor workflows, permalink strategy, REST exposure, WPGraphQL/headless exposure, or search/facet design.

## Protocol

Phase 0 - Modeling boundary: state the user goal, editorial audience, content samples available, and what is not being modeled yet.
    Phase 1 - Inventory and tooling: inspect existing post types, taxonomies, post meta, ACF field groups, templates, blocks, REST exposure, URLs, search indexes, reporting needs, WP/PHP targets, and available wp-env/Playground/WP-CLI/Composer/npm/test tooling.
    Phase 2 - Content behavior analysis: classify lifecycle, ownership, permissions, search/filter needs, URL needs, revision needs, and display variation before choosing CPTs or taxonomies.
    Phase 3 - Post type and taxonomy design: decide CPT, taxonomy, post meta, option, user meta, block attribute, pattern, or external-system boundaries with explicit tradeoffs.
    Phase 4 - Field and relationship matrix: specify names, cardinality, validation, defaults, UI placement, dependency implications, registered meta schema, REST exposure, and portability.
    Phase 5 - Editorial workflow: define roles/capabilities, moderation, previews, revision expectations, bulk editing, admin columns, dashboard burden, and training needs.
    Phase 6 - API, search, and template implications: specify show_in_rest, WPGraphQL/headless needs, permalinks, archive behavior, facets, indexing, canonical URLs, and theme/block dependencies.
    Phase 7 - Migration and backfill plan: define source mapping, data cleanup, redirects, fixtures, count checks, rollback, and sample review.
    Phase 8 - Assumption register and alternatives: compare one CPT plus taxonomies, multiple CPTs, page hybrids, ACF-heavy models, and custom tables when relevant.
    Phase 9 - Critic and executor handoff: name generated artifacts, plugin/theme responsibilities, and review checkpoints.

## Hard Gates

- Do not use the client's noun as the content model without testing content behavior.
    - Do not split CPTs solely by layout differences.
    - Do not use post meta for high-cardinality faceting or relationship-heavy queries without scale, index, and cache reasoning.
    - Do not recommend ACF without documenting portability, schema, REST exposure, dependency, export, and migration implications.
    - Every model must specify capabilities, REST exposure, permalink strategy, validation, migration/backfill, and sample-review gates.
    - Every plan must state the available runtime/tooling lane and the acceptance checks that can actually be run.

## Exact API And Verification Contract

Every recommendation, decision, remediation, and verification handoff must name the concrete WordPress surface it relies on. When relevant, include exact functions, hooks, files, packages, or commands instead of category labels: `current_user_can()`, `check_admin_referer()`/`check_ajax_referer()`/`wp_verify_nonce()`, `register_rest_route` `permission_callback` or `WP_REST_Controller` permission methods, `$wpdb->prepare()`, `sanitize_key()`/`sanitize_text_field()`/`wp_kses_post()`, `esc_html()`/`esc_attr()`/`esc_url()`/`wp_safe_redirect()`, `wp_handle_upload()`, `block.json`, `register_block_type()`, `render_callback`/`render.php`, deprecated block versions/migrate/transforms, `theme.json`, `register_post_type()`, `register_taxonomy()`, `register_post_meta()`/`register_meta()` with `show_in_rest`/schema/`auth_callback`, `WP_Query` args, `wp_cache_get()`/`wp_cache_set()`, transients with invalidation, `wp_schedule_event()`/`wp_next_scheduled()`/Action Scheduler, `wp_register_ability()`/`wp_abilities_api_init`, `label`/`description`/`category`, `wp_register_ability_category()`/`wp_abilities_api_categories_init`, `input_schema`/`output_schema`, `execute_callback`, `permission_callback`, `@wordpress/abilities`, `@wordpress/core-abilities`, `wordpress/mcp-adapter`, `mcp_adapter_init`, `mcp-adapter-discover-abilities`/`mcp-adapter-execute-ability`, `wp_ai_client_prompt()`, `wp_connectors_init`, Query Monitor, WP-CLI, Plugin Check, PHPCS/WPCS, PHPUnit, and Playwright/editor smoke where applicable. If no exact WordPress API applies, state why and name the verification oracle instead.

## Calibration

Treat uncertainty as design data. Separate observed evidence from assumptions, name negative space, and avoid generic CMS advice or Drupal vocabulary transplants. Do not claim benchmark, release, or current-version status without evidence.

## Failure Modes

Watch for hidden authorization assumptions, unsafe production commands, missing rollback, missing test strategy, cache claims without invalidation, block/theme editor parity gaps, unlogged upstream reuse, and unsupported version claims.

## Output Contract

Use these headings:
- `## Content Model Summary`
- `## Current-State Evidence`
- `## Content Behavior Analysis`
- `## Post Type Taxonomy And Field Matrix`
- `## Editorial Workflow`
- `## API Search And Template Implications`
- `## Migration And Validation Plan`
- `## Assumption Register`
- `## Alternatives Considered`
- `## Acceptance Criteria`
- `## Executor Handoff`
- `## Critic Handoff`

## Provenance

Original Zivtech protocol. Compatible references remain reference-only unless reuse is logged and licensed.
