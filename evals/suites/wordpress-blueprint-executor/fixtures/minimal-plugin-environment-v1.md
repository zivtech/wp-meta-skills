# Focused Fixture: Minimal Reproducible Plugin Environment

Generate a WordPress Playground Blueprint packet with
`wordpress-blueprint-executor` for this approved spec:

- Purpose: reproduce and smoke-test a local plugin named `acme-notice-board`.
- WordPress version: latest stable is acceptable only if the Blueprint notes why
  a floating WordPress version is acceptable for this disposable smoke.
- PHP version: 8.2.
- Required setup:
  - install the local plugin artifact from `./dist/acme-notice-board.zip`;
  - activate the plugin;
  - create an administrator login or document Playground's default login path;
  - set the landing page to `/wp-admin/admin.php?page=acme-notice-board`;
  - create one sample post with title `Blueprint Notice Smoke`.
- Manual follow-up: reviewer clicks the plugin admin page and confirms the
  notice list renders the sample post title.

## Expected Executor Focus

- Emit one valid `blueprint.json` under `## Generated Blueprint`.
- Use `preferredVersions`, `steps`, `installPlugin`, and `activatePlugin` or an
  explicit supported alternative.
- Include provenance notes for the local plugin zip and any floating version.
- Include verification notes for static Blueprint validation, Playground launch,
  expected landing page, reset behavior, and smoke assertions.
- Avoid hiding manual prerequisites or claiming runtime behavior from static
  JSON alone.

## Required Boundaries

Do not fetch private URLs, embed credentials, or claim production deployment.
Static Blueprint validity is not Playground launch proof.
