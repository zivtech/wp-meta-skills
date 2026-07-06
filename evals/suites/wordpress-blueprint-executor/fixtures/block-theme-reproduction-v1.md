# Focused Fixture: Block Or Theme Reproduction Environment

Generate a WordPress Playground Blueprint packet with
`wordpress-blueprint-executor` for this approved reproduction spec:

- Purpose: reproduce a block rendering bug in a block theme.
- Theme artifact: `./dist/acme-block-theme.zip`.
- Plugin artifact: `./dist/acme-events-block.zip`.
- Setup:
  - install and activate the theme;
  - install and activate the block plugin;
  - create a page titled `Runtime Events Demo`;
  - insert an `acme/events-list` block with attributes `{ "limit": 3 }`;
  - set permalink structure to `/%postname%/`;
  - set the landing page to the generated page URL.
- Manual follow-up: reviewer opens the page and confirms the block wrapper
  appears while the bug reproduction note remains visible.

## Expected Executor Focus

- Preserve block/theme state needed for reproduction: theme activation, plugin
  activation, page content, block attributes, permalink state, and landing page.
- Keep generated JSON valid and explanation outside the JSON fence.
- Include provenance for uploaded artifacts and sample content.
- Include verification notes for static artifact validation, Playground launch,
  frontend URL, editor follow-up if needed, and reset behavior.

## Required Boundaries

Do not claim the bug is reproduced until a Playground launch smoke records the
actual frontend behavior. Static Blueprint validity only proves JSON shape and
non-empty steps.
