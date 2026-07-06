# Focused Fixture: Self-contained Plugin Launch Blueprint

Generate a WordPress Playground Blueprint packet with
`wordpress-blueprint-executor` for this approved spec:

- Purpose: create a launchable, self-contained Playground smoke that does not
  depend on local VFS ZIP payloads or remote URLs.
- WordPress version: latest stable is acceptable only if the Blueprint notes why
  a floating WordPress version is acceptable for this disposable smoke.
- PHP version: 8.2.
- Required setup:
  - write a disposable plugin named `acme-inline-blueprint-smoke` directly into
    `/wordpress/wp-content/plugins/acme-inline-blueprint-smoke` with `mkdir`
    and `writeFile`;
  - the plugin must register an admin page at
    `/wp-admin/admin.php?page=acme-inline-blueprint-smoke`;
  - activate the plugin with `activatePlugin`;
  - create an administrator login or document Playground's default login path;
  - set the landing page to
    `/wp-admin/admin.php?page=acme-inline-blueprint-smoke`;
  - render visible text `Inline Blueprint Smoke Ready` on the admin page.
- Manual follow-up: reviewer launches the generated fragment URL, waits for
  Playground setup to finish, and confirms the admin page text appears without
  missing-payload errors.

## Expected Executor Focus

- Emit one valid `blueprint.json` under `## Generated Blueprint`.
- Use `preferredVersions`, `features.networking: false`, `steps`, `mkdir`,
  `writeFile`, and `activatePlugin`.
- Include provenance notes that all generated plugin code is contained inside
  the Blueprint JSON and no VFS ZIP, private URL, or credential is required.
- Include verification notes for static Blueprint validation, launch-readiness
  preflight, Playground launch, expected landing page, reset behavior, and smoke
  assertions.
- Avoid claiming plugin runtime success until a recorded Playground launch smoke
  exists.

## Required Boundaries

Do not fetch private URLs, embed credentials, depend on missing local ZIPs, or
claim production deployment. A self-contained fragment URL is launch-ready
evidence only; it is not browser-observed runtime proof until a launch smoke is
recorded.
