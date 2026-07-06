## Input Summary
Approved Blueprint executor packet for a disposable WordPress Playground reproduction of an `acme/events-list` block rendering issue inside the local `acme-block-theme` theme. The packet installs and activates the local theme and block plugin artifacts, creates a published page titled `Runtime Events Demo`, inserts the block with `{"limit":3}`, sets permalink structure to `/%postname%/`, and lands on `/runtime-events-demo/`.

The Blueprint is static evidence until a recorded Playground launch smoke proves the frontend wrapper and bug reproduction note actually appear.

## Generated Blueprint
```json
{
  "$schema": "https://playground.wordpress.net/blueprint-schema.json",
  "landingPage": "/runtime-events-demo/",
  "preferredVersions": {
    "php": "8.2",
    "wp": "latest"
  },
  "extraLibraries": [
    "wp-cli"
  ],
  "features": {
    "networking": false
  },
  "steps": [
    {
      "step": "login",
      "username": "admin"
    },
    {
      "step": "installTheme",
      "themeData": {
        "resource": "vfs",
        "path": "/wordpress/wp-content/uploads/acme-block-theme.zip"
      },
      "options": {
        "activate": true
      }
    },
    {
      "step": "installPlugin",
      "pluginData": {
        "resource": "vfs",
        "path": "/wordpress/wp-content/uploads/acme-events-block.zip"
      },
      "options": {
        "activate": true
      }
    },
    {
      "step": "setSiteOptions",
      "options": {
        "permalink_structure": "/%postname%/"
      }
    },
    {
      "step": "wp-cli",
      "command": "wp rewrite flush --hard"
    },
    {
      "step": "wp-cli",
      "command": "wp post create --post_type=page --post_status=publish --post_title='Runtime Events Demo' --post_name='runtime-events-demo' --post_content='<!-- wp:paragraph --><p>Bug reproduction note: confirm the events wrapper remains visible.</p><!-- /wp:paragraph --><!-- wp:acme/events-list {\"limit\":3} /-->'"
    }
  ]
}
```

## Provenance Notes
- Local theme artifact source: `./dist/acme-block-theme.zip`, represented as a Playground VFS upload at `/wordpress/wp-content/uploads/acme-block-theme.zip`.
- Local plugin artifact source: `./dist/acme-events-block.zip`, represented as a Playground VFS upload at `/wordpress/wp-content/uploads/acme-events-block.zip`.
- Blueprint shape follows the WordPress Playground data format and step documentation for `landingPage`, `preferredVersions`, `features`, `extraLibraries`, `steps`, `login`, `installTheme`, `installPlugin`, `setSiteOptions`, and `wp-cli`: https://wordpress.github.io/wordpress-playground/blueprints/data-format/ and https://wordpress.github.io/wordpress-playground/blueprints/steps/.
- `preferredVersions.wp` is intentionally `latest` because this is a disposable reproduction environment. Pin a specific supported WordPress version before converting this into release evidence.

## Safety And Determinism Notes
- The Blueprint is disposable and uses `features.networking: false`; it does not fetch private URLs, call external services, or embed credentials.
- The `wp-cli` steps create one local page and flush local rewrite rules inside the disposable Playground instance.
- The block comment preserves the exact `acme/events-list` block name and `limit` attribute requested by the fixture.
- Static Blueprint validation proves JSON shape and a non-empty `steps` array only. It does not prove the frontend bug is reproduced, the editor remains valid, or the block wrapper appears.

## Deviation Log
- The fixture asks for theme and plugin activation; this packet uses the documented `installTheme` and `installPlugin` activation options.
- The local zip files must be supplied to Playground before launch as VFS resources. This packet does not invent public URLs.
- The frontend landing page assumes WordPress resolves `/runtime-events-demo/` after `wp rewrite flush --hard`; a recorded Playground launch smoke must verify that assumption.

## Verification Notes
- Packet contract: `python3 evals/harness/validate_wordpress_executor_packet.py --executor blueprint --packet evals/suites/wordpress-blueprint-executor/examples/block-theme-reproduction-v1.materializable-packet.md`
- Materializer: `python3 evals/harness/materialize_wordpress_executor_packet.py --executor blueprint --packet evals/suites/wordpress-blueprint-executor/examples/block-theme-reproduction-v1.materializable-packet.md --out-dir /tmp/acme-events-blueprint --overwrite`
- Static Blueprint schema/oracle: `python3 evals/harness/validate_wordpress_artifact.py --artifact-type blueprint --path /tmp/acme-events-blueprint/blueprint.json`
- Certifier: `python3 evals/harness/certify_wordpress_executor_artifact.py --executor blueprint --packet evals/suites/wordpress-blueprint-executor/examples/block-theme-reproduction-v1.materializable-packet.md --out-dir /tmp/acme-events-blueprint --result-dir /tmp/acme-events-blueprint-cert --overwrite`
- Playground launch smoke still must open the generated Blueprint with both VFS zip artifacts present, confirm landing page `/runtime-events-demo/`, confirm the `acme/events-list` wrapper appears, confirm the bug reproduction note remains visible, perform any editor follow-up needed for block validity, and use Playground reset before repeat runs.

## Critic Handoff
Send this packet and the generated `blueprint.json` to `wordpress-critic` for block/theme reproduction fidelity, permalink assumptions, artifact provenance, editor/frontend negative space, and the manual smoke checklist. Ask the reviewer to keep bug-reproduction claims blocked until a recorded Playground launch smoke exists.
