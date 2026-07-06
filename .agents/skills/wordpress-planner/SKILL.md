---
name: wordpress-planner
type: planner
model: Codex-fable-5
description: Plan WordPress implementations across plugins, themes, blocks, content models, migrations, operations, and review checkpoints.
---

# WordPress Planner

## When to Use

Use this skill when a WordPress task needs implementation design before code, including plugin architecture, content models, block or theme planning, REST/API exposure, migrations, performance, security, release, or WP-CLI operations.

## Protocol

Phase 0 - Intake boundary: classify the request, name the WordPress surface, state what is in scope, and state what is not being claimed.
    Phase 1 - Repository and runtime triage: inspect the plugin/theme/site shape, WordPress/PHP targets, build tooling, hosting constraints, multisite/headless/WooCommerce implications, and available tests.
    Phase 2 - Current-state evidence: cite existing files, settings, hooks, post types, blocks, templates, REST routes, WP-CLI commands, and docs before designing new work.
    Phase 3 - User goal and success criteria: define the audience, editorial or operational workflow, acceptance gates, rollback needs, and the consequence of a wrong design.
    Phase 4 - WordPress-native architecture: decide ownership boundaries across core APIs, maintained plugins, custom plugins, mu-plugins, themes, blocks, REST, cron, data storage, permissions, cache, deployment, and observability.
    Phase 5 - Domain deep dive: route to focused content-model, plugin, block, theme, migration, security, or performance planning sections when the request needs them.
    Phase 6 - Assumption register: list fragile/moderate/robust assumptions with evidence, risk if wrong, detection signal, and mitigation.
    Phase 7 - Test and verification strategy: define unit, integration, E2E/manual, accessibility, security, performance, migration, and rollback checks in proportion to risk.
    Phase 8 - Implementation sequence: break the work into ordered tasks, dependencies, stop conditions, and owner handoffs without writing implementation code.
    Phase 9 - Executor and critic checkpoints: name the executor surface, required inputs, non-goals, and the exact critics required before production use.

## Hard Gates

- Do not recommend custom code when core APIs or mature maintained plugins solve the job unless tradeoffs justify custom work.
    - Do not store secrets in options, config, blueprints, fixtures, or generated docs.
    - Security-sensitive plans must cover capabilities, nonces, sanitization, escaping, prepared SQL, REST permission callbacks, AJAX/admin boundaries, upload constraints, and secret handling.
    - Performance-sensitive plans must cover object cache, transients, autoloaded options, query shape, cron, HTTP API calls, asset loading, and cache invalidation.
    - Migration plans must include source audit, redirects, media handling, dry run, idempotency, rollback, validation, and editorial cutover.
    - Do not transplant Drupal vocabulary into WordPress decisions; use WordPress concepts such as CPTs, taxonomies, post meta, block.json, theme.json, hooks, capabilities, WP-CLI, and Playground.

## Exact API And Verification Contract

Every recommendation, decision, remediation, and verification handoff must name the concrete WordPress surface it relies on. When relevant, include exact functions, hooks, files, packages, or commands instead of category labels: `current_user_can()`, `check_admin_referer()`/`check_ajax_referer()`/`wp_verify_nonce()`, `register_rest_route` `permission_callback` or `WP_REST_Controller` permission methods, `$wpdb->prepare()`, `sanitize_key()`/`sanitize_text_field()`/`wp_kses_post()`, `esc_html()`/`esc_attr()`/`esc_url()`/`wp_safe_redirect()`, `wp_handle_upload()`, `block.json`, `register_block_type()`, `render_callback`/`render.php`, deprecated block versions/migrate/transforms, `theme.json`, `register_post_type()`, `register_taxonomy()`, `register_post_meta()`/`register_meta()` with `show_in_rest`/schema/`auth_callback`, `WP_Query` args, `wp_cache_get()`/`wp_cache_set()`, transients with invalidation, `wp_schedule_event()`/`wp_next_scheduled()`/Action Scheduler, `wp_register_ability()`/`wp_abilities_api_init`, `label`/`description`/`category`, `wp_register_ability_category()`/`wp_abilities_api_categories_init`, `input_schema`/`output_schema`, `execute_callback`, `permission_callback`, `@wordpress/abilities`, `@wordpress/core-abilities`, `wordpress/mcp-adapter`, `mcp_adapter_init`, `mcp-adapter-discover-abilities`/`mcp-adapter-execute-ability`, `wp_ai_client_prompt()`, `wp_connectors_init`, Query Monitor, WP-CLI, Plugin Check, PHPCS/WPCS, PHPUnit, and Playwright/editor smoke where applicable. If no exact WordPress API applies, state why and name the verification oracle instead.

## Calibration

Treat uncertainty as design data. Separate observed evidence from assumptions, name negative space, and avoid generic CMS advice or Drupal vocabulary transplants. Do not claim benchmark, release, or current-version status without evidence.

## Failure Modes

Watch for hidden authorization assumptions, unsafe production commands, missing rollback, missing test strategy, cache claims without invalidation, block/theme editor parity gaps, unlogged upstream reuse, and unsupported version claims.

## Output Contract

Use these headings:
- `## Scope Summary`
- `## Current-State Evidence`
- `## Architecture Plan`
- `## WordPress-Specific Decisions`
- `## Assumption Register`
- `## Test And Verification Strategy`
- `## Implementation Sequence`
- `## Executor Handoff`
- `## Critic Checkpoints`
- `## Acceptance Criteria`
- `## Assumptions And Open Questions`

## Provenance

Original Zivtech protocol. Compatible references for evaluators include WordPress/agent-skills under GPL-2.0-or-later as reference-only material until repo-level license handling changes.
