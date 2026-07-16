# Smoke Fixture: Acme Runtime Card

Scenario: Generate a materializable WordPress block implementation packet from
an approved, exact block specification.

## Approved Specification

Build a block-only artifact for the dynamic block `acme/runtime-card`.

- Target WordPress 6.5 or newer and block API version 3.
- Use the title `Runtime Card`, category `widgets`, description `A disposable
  dynamic block used by the WordPress executor runtime oracle.`, and textdomain
  `acme-runtime-card`.
- Generate exactly these artifact paths:
  - `package.json`
  - `package-lock.json`, using approved lock profile
    `block-scripts-32.4.1-smoke`, lock SHA-256
    `990d9a67783977a5a4c54035666ebc48f7aaac8cdf69f2313caf2a17b317fa33`,
    and manifest SHA-256
    `e2259282345ac90cb5645507efd0daba536b2742be3eab676db10fd7fc1fb4f6`
  - `blocks/runtime-card/block.json`
  - `blocks/runtime-card/index.asset.php`
  - `blocks/runtime-card/index.js`
  - `blocks/runtime-card/render.php`
- Use `@wordpress/scripts` version `32.4.1`. The exact build command is
  `wp-scripts build blocks/runtime-card/index.js --output-path=blocks/runtime-card/build`;
  the start command is `wp-scripts start`.
- Declare `index.asset.php` dependencies `wp-blocks`, `wp-element`, and
  `wp-i18n`, with version `0.1.0`.
- Register the editor implementation as `acme/runtime-card`. It has no block
  attributes, displays the literal text `Runtime block smoke`, and returns
  `null` from `save()` because frontend output is dynamic.
- Declare `render.php` through `block.json`. The render template must refuse
  direct access, use `get_block_wrapper_attributes()` for the deterministic
  `.wp-block-acme-runtime-card` wrapper, and escape the literal visible text
  `Runtime block smoke` with the appropriate WordPress internationalization
  API.
- Keep the artifact block-only. Do not generate a permanent plugin wrapper,
  REST route, AJAX or admin-post handler, SQL, uploads, remote HTTP, secrets, or
  production write commands. The disposable runtime harness owns temporary
  registration and activation.

## Required Packet And Evidence Contract

Use the `wordpress-block-executor` output headings and emit each complete file
under `## Generated Block Files` as `### relative/path` followed immediately by
one fenced code block. The packet must be valid for the block packet validator,
materializer, and static artifact certifier.

Runtime claims require the current direct-artifact command. It must bind the
pre-stage artifact digest and evidence ID; pass `acme/runtime-card`,
`.wp-block-acme-runtime-card`, and `Runtime block smoke` explicitly; require the
block build, editor insertion/frontend render, provisioned full profile, and
strict full profile through `--strict-full-profile`; write a unique run ID; and
use a bounded timeout. Static
packet or artifact success is not runtime proof.

External generated-block Interactivity API and deprecation runtime modes are
unsupported by the current isolated artifact path. Historical built-in fixture
results must not be presented as current evidence for this artifact.

The response must distinguish observed evidence from assumptions, name any
deviation from this specification, and hand the materialized packet plus static
and runtime evidence to the WordPress and performance critics.
