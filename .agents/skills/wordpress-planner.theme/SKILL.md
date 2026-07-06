---
name: wordpress-planner.theme
type: planner
model: Codex-fable-5
description: Plan WordPress theme and block theme architecture including theme.json, templates, parts, patterns, style variations, and editor/frontend parity.
---

# WordPress Theme Planner

## When to Use

Use for block themes, classic themes, child themes, theme.json, template hierarchy, template parts, block patterns, style variations, global styles, editor supports, or frontend/editor parity.

## Protocol

Phase 0 - Theme boundary: classify block theme, classic theme, hybrid theme, child theme, design-system extraction, or template/pattern change.
    Phase 1 - Inventory and tooling: inspect theme.json version, templates, template parts, patterns, styles, functions.php, enqueue strategy, build tooling, Theme Check availability, block styles, assets, and editor/frontend behavior.
    Phase 2 - User and editorial goals: define Site Editor expectations, pattern governance, brand constraints, accessibility goals, responsive needs, and support burden.
    Phase 3 - Theme architecture: design theme.json settings/styles, custom templates, template hierarchy, parts, patterns, style variations, block styles, custom CSS scope, and tokens.
    Phase 4 - Editor/frontend parity: specify where behavior appears in Site Editor, post editor, frontend, navigation, archives, search, and error templates.
    Phase 5 - Accessibility and responsive strategy: plan landmarks, skip links, heading order, focus, contrast, reduced motion, media behavior, forms, and keyboard states.
    Phase 6 - Performance and maintainability: plan conditional assets, global styles scope, specificity, font loading, image sizes, cache implications, and child-theme override strategy.
    Phase 7 - Assumption register and alternatives: compare block vs classic vs hybrid decisions and name fragile design/token dependencies.
    Phase 8 - Test strategy: define Site Editor checks, template resolution, viewport checks, keyboard checks, visual regression, performance budget, and rollback.
    Phase 9 - Executor and critic handoff.

## Hard Gates

- Do not treat theme.json as a dumping ground for unrelated site configuration.
    - Template hierarchy, template parts, patterns, and style variations must be explicit.
    - Editor and frontend behavior must be planned together; deviations must be named.
    - Accessibility and responsive behavior are part of V1 scope, not polish.
    - No style variation without token provenance or rationale.
    - Verification must cover Site Editor checks, frontend viewport checks, keyboard/focus checks, Theme Check or equivalent linting when available, and rollback.

## Exact API And Verification Contract

Every recommendation, decision, remediation, and verification handoff must name the concrete WordPress surface it relies on. When relevant, include exact functions, hooks, files, packages, or commands instead of category labels: `current_user_can()`, `check_admin_referer()`/`check_ajax_referer()`/`wp_verify_nonce()`, `register_rest_route` `permission_callback` or `WP_REST_Controller` permission methods, `$wpdb->prepare()`, `sanitize_key()`/`sanitize_text_field()`/`wp_kses_post()`, `esc_html()`/`esc_attr()`/`esc_url()`/`wp_safe_redirect()`, `wp_handle_upload()`, `block.json`, `register_block_type()`, `render_callback`/`render.php`, deprecated block versions/migrate/transforms, `theme.json`, `register_post_type()`, `register_taxonomy()`, `register_post_meta()`/`register_meta()` with `show_in_rest`/schema/`auth_callback`, `WP_Query` args, `wp_cache_get()`/`wp_cache_set()`, transients with invalidation, `wp_schedule_event()`/`wp_next_scheduled()`/Action Scheduler, `wp_register_ability()`/`wp_abilities_api_init`, `label`/`description`/`category`, `wp_register_ability_category()`/`wp_abilities_api_categories_init`, `input_schema`/`output_schema`, `execute_callback`, `permission_callback`, `@wordpress/abilities`, `@wordpress/core-abilities`, `wordpress/mcp-adapter`, `mcp_adapter_init`, `mcp-adapter-discover-abilities`/`mcp-adapter-execute-ability`, `wp_ai_client_prompt()`, `wp_connectors_init`, Query Monitor, WP-CLI, Plugin Check, PHPCS/WPCS, PHPUnit, and Playwright/editor smoke where applicable. If no exact WordPress API applies, state why and name the verification oracle instead.

## Calibration

Treat uncertainty as design data. Separate observed evidence from assumptions, name negative space, and avoid generic CMS advice or Drupal vocabulary transplants. Do not claim benchmark, release, or current-version status without evidence.

## Failure Modes

Watch for hidden authorization assumptions, unsafe production commands, missing rollback, missing test strategy, cache claims without invalidation, block/theme editor parity gaps, unlogged upstream reuse, and unsupported version claims.

## Output Contract

Use these headings:
- `## Theme Scope`
- `## Current-State Evidence`
- `## Theme JSON And Template Plan`
- `## Pattern And Style Variation Plan`
- `## Editor Frontend Parity Plan`
- `## Accessibility Responsive And Performance Plan`
- `## Assumption Register`
- `## Test Strategy`
- `## Acceptance Criteria`
- `## Executor Handoff`
- `## Critic Handoff`

## Provenance

Original Zivtech protocol. Compatible references remain reference-only unless reuse is logged and licensed.
