## Input Summary
Approved Blueprint executor packet for a self-contained disposable WordPress
Playground smoke. The packet writes a tiny plugin directly with `mkdir` and `writeFile`,
activates it with `activatePlugin`, and lands on an admin page that renders
`Inline Blueprint Smoke Ready`.

The Blueprint is launch-ready static evidence because it has no VFS ZIP
payloads, private URLs, credentials, or remote fetches. It is not live runtime
evidence until a recorded Playground launch smoke confirms the admin page text
renders.

## Generated Blueprint
```json
{
  "$schema": "https://playground.wordpress.net/blueprint-schema.json",
  "landingPage": "/wp-admin/admin.php?page=acme-inline-blueprint-smoke",
  "preferredVersions": {
    "php": "8.2",
    "wp": "latest"
  },
  "features": {
    "networking": false
  },
  "steps": [
    {
      "step": "login",
      "username": "admin"
    },
    {
      "step": "mkdir",
      "path": "/wordpress/wp-content/plugins/acme-inline-blueprint-smoke"
    },
    {
      "step": "writeFile",
      "path": "/wordpress/wp-content/plugins/acme-inline-blueprint-smoke/acme-inline-blueprint-smoke.php",
      "data": "<?php\n/**\n * Plugin Name: Acme Inline Blueprint Smoke\n * Description: Disposable admin page for a self-contained WordPress Playground Blueprint smoke.\n * Version: 0.1.0\n * Author: Zivtech\n * License: GPL-2.0-or-later\n */\n\nadd_action( 'admin_menu', 'acme_inline_blueprint_smoke_menu' );\n\nfunction acme_inline_blueprint_smoke_menu() {\n\tadd_menu_page(\n\t\t'Inline Blueprint Smoke',\n\t\t'Inline Blueprint Smoke',\n\t\t'manage_options',\n\t\t'acme-inline-blueprint-smoke',\n\t\t'acme_inline_blueprint_smoke_render'\n\t);\n}\n\nfunction acme_inline_blueprint_smoke_render() {\n\tif ( ! current_user_can( 'manage_options' ) ) {\n\t\twp_die( esc_html__( 'You do not have permission to view this smoke page.', 'acme-inline-blueprint-smoke' ) );\n\t}\n\n\techo '<div class=\"wrap\"><h1>Inline Blueprint Smoke Ready</h1><p>Self-contained Playground launch fixture loaded without VFS payloads.</p></div>';\n}\n"
    },
    {
      "step": "activatePlugin",
      "pluginName": "Acme Inline Blueprint Smoke",
      "pluginPath": "acme-inline-blueprint-smoke/acme-inline-blueprint-smoke.php"
    },
    {
      "step": "setSiteOptions",
      "options": {
        "blogname": "Acme Inline Blueprint Smoke"
      }
    }
  ]
}
```

## Provenance Notes
- The plugin source is contained entirely inside this Blueprint JSON through
  `mkdir` and `writeFile` steps; there is no local VFS ZIP payload to supply.
- Blueprint shape follows the current WordPress Playground data format and step
  documentation for `landingPage`, `preferredVersions`, `features`,
  `steps`, `login`, `mkdir`, `writeFile`, `activatePlugin`, and
  `setSiteOptions`:
  https://wordpress.github.io/wordpress-playground/blueprints/data-format/ and
  https://wordpress.github.io/wordpress-playground/blueprints/steps/.
- `preferredVersions.wp` is intentionally `latest` because this is a disposable
  launch smoke, not a release-support matrix. A release certification would pin
  supported WordPress versions explicitly.

## Safety And Determinism Notes
- The Blueprint is disposable and uses `features.networking: false`; it does
  not fetch private URLs, call production systems, or embed credentials.
- The plugin checks `current_user_can( 'manage_options' )` before rendering the
  admin page and uses `esc_html__()` for the denied-access message.
- Static Blueprint validation and launch-readiness preflight prove JSON shape
  and absence of missing VFS payload blockers only. They do not prove plugin
  activation or admin-page rendering until the launch smoke is recorded.

## Deviation Log
- The fixture asks for a launchable self-contained Blueprint; this packet uses
  `mkdir` and `writeFile` instead of `installPlugin` so no ZIP file or remote
  URL is needed.
- The fixture asks for administrator login or documented default login path.
  This packet uses the Playground `login` step for `admin` and avoids a literal
  password.
- The plugin is intentionally minimal and exists only to expose a visible
  smoke assertion in Playground.

## Verification Notes
- Packet contract: `python3 evals/harness/validate_wordpress_executor_packet.py --executor blueprint --packet evals/suites/wordpress-blueprint-executor/examples/self-contained-plugin-launch-v1.materializable-packet.md`
- Materializer: `python3 evals/harness/materialize_wordpress_executor_packet.py --executor blueprint --packet evals/suites/wordpress-blueprint-executor/examples/self-contained-plugin-launch-v1.materializable-packet.md --out-dir /tmp/acme-inline-blueprint --overwrite`
- Static Blueprint schema/oracle: `python3 evals/harness/validate_wordpress_artifact.py --artifact-type blueprint --path /tmp/acme-inline-blueprint/blueprint.json`
- Certifier: `python3 evals/harness/certify_wordpress_executor_artifact.py --executor blueprint --packet evals/suites/wordpress-blueprint-executor/examples/self-contained-plugin-launch-v1.materializable-packet.md --out-dir /tmp/acme-inline-blueprint --result-dir /tmp/acme-inline-blueprint-cert --overwrite`
- Launch-readiness preflight: run `python3 evals/harness/audit_wordpress_blueprint_launch_readiness.py` against the certification result directory and confirm status `ready_for_manual_launch` with a generated Playground fragment URL.
- Playground launch smoke still must open the generated fragment URL, confirm landing page `/wp-admin/admin.php?page=acme-inline-blueprint-smoke`, confirm visible text `Inline Blueprint Smoke Ready`, capture browser status and console/runtime errors, and use Playground reset before repeat runs.

## Critic Handoff
Send this packet and the generated `blueprint.json` to `wordpress-critic` for
self-contained Blueprint fidelity, launch-boundary language, capability
guarding, and manual smoke checklist review. Ask the reviewer to keep runtime
claims blocked until recorded Playground launch evidence exists.
