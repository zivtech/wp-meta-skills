# Smoke Fixture: wordpress-plugin-executor

Scenario: Generate a materializable plugin implementation packet from this approved spec.

## Approved Planner Spec

Build a minimal WordPress plugin named **Acme Runtime**.

- Plugin slug: `acme-runtime`
- Text domain: `acme-runtime`
- Target: WordPress 6.5+, PHP 8.1+
- Generated files:
  - `acme-runtime/acme-runtime.php`
  - `acme-runtime/readme.txt`
- Behavior:
  - Register activation and deactivation hooks.
  - On activation, create the `acme_runtime_mode` option with default value `safe`.
  - On deactivation, delete the `acme_runtime_preview` transient.
  - Register the `acme_runtime_mode` setting on `admin_init` using `register_setting()`.
  - Sanitize the setting with `sanitize_key()`.
  - Provide a small status-rendering helper guarded by `current_user_can( 'manage_options' )`.
  - Escape rendered option output with `esc_html()`.
- Non-goals:
  - Do not add REST routes, AJAX endpoints, admin-post handlers, cron, SQL, uploads, remote HTTP calls, build tooling, or production write commands.
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
- The deterministic packet oracle fails outputs that rename `## Deviation Log` to `## Deviations`, rename `## Verification Notes` to `## Verification Commands`, omit `## Generated File Map`, or add a preface before `## Spec Conformance`.
- Under `## Generated File Map`, list each generated file as an exact relative path in code spans, including `acme-runtime/acme-runtime.php` and `acme-runtime/readme.txt`. A directory tree without exact relative path tokens is not sufficient.
- Under `## Implementation Packets`, each generated file must be introduced by `### relative/path.ext`.
- Each file heading must be followed immediately by one fenced code block containing the complete file contents.
- The packet must name exact WordPress APIs and verification commands, including PHPCS/WPCS, PHPUnit where tests exist, WP-CLI smoke commands, and Plugin Check.
- The handoff must name `wordpress-security-critic` and `wordpress-critic`.
- Verification notes must explicitly state whether commands were run. If they were not run, say that WPCS, PHPUnit, Plugin Check, wp-env, browser/editor, and release readiness are not claimed.
