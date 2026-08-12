# Focused Smoke Fixture: Acme Runtime Card Block Plan

Plan the repository-defined custom block below. This is a custom-block definition,
not a CMS migration or a request to generate imported `post_content`.

## Approved Artifact Facts

- The block is a new dynamic block named `acme/runtime-card`, targeting WordPress
  6.5 or newer and block API version 3.
- The block-only artifact root contains `package.json` and
  `blocks/runtime-card/`.
- `block.json` uses category `widgets`, textdomain `acme-runtime-card`,
  `editorScript: file:./index.js`, and `render: file:./render.php`.
- V1 has no user-supplied attributes. The editor displays `Runtime block smoke`,
  `save()` returns `null`, and `render.php` emits the same escaped text inside
  block wrapper attributes.
- The frontend runtime oracle must find block name `acme/runtime-card`, selector
  `.wp-block-acme-runtime-card`, and visible text `Runtime block smoke`.
- The block tree is not a standalone plugin. A repository host or disposable
  runtime wrapper calls `register_block_type()` on the block directory.
- The approved build path is an `@wordpress/scripts` build for
  `blocks/runtime-card/index.js`; lint/test-only or arbitrary package scripts do
  not establish build readiness.

## Required Planning Decisions

- Emit the exact authoritative records required by the skill contract:
  `Block identity: acme/runtime-card`, `Primary serialization: dynamic`,
  `Metadata file: block.json`, `Attributes: none`,
  `Saved markup: self-closing`, `Render surface: render.php`,
  `Failure behavior: log-and-return-empty`,
  `Compatibility decision: new-contract`, `Saved-content fixture: required`,
  `Editor oracle: required`,
  `Editor oracle method: playwright-insert-save-reload`,
  `Editor oracle block: acme/runtime-card`, `Frontend oracle: required`,
  `Frontend oracle method: playwright-selector-visible-text`,
  `Frontend oracle selector: .wp-block-acme-runtime-card`, and
  `Frontend expected text: Runtime block smoke`. Put each record at column zero,
  put explanation in the surrounding prose, and do not add detail to enumerated
  values.
- Classify the block as dynamic and state why `save()` returns `null` while
  `render.php` owns frontend markup.
- Define the exact `block.json`, asset/build, registration, escaping, editor,
  frontend, and render-failure contracts. State explicitly that V1 has no
  attributes rather than inventing an attribute schema.
- Treat this as a new saved-content contract: no deprecated version is required
  for V1, but future changes to attributes or saved markup require an explicit
  deprecated/migrate/transform decision.
- Define distinct build/static, block-registration, editor insertion/save, and
  frontend selector/text oracles. Static artifact acceptance alone is not
  runtime proof.
- Hand the approved bounded block artifact to `wordpress-block-executor` and the
  resulting artifact/runtime evidence to the WordPress critics.

## Routing Boundary

Do not design a source converter, bulk content serializer, importer, unsupported
source report, idempotence strategy, or migration rollback. Those belong to
`wordpress-planner.migration`. Do not claim benchmark superiority or current
runtime success from this planning fixture.
