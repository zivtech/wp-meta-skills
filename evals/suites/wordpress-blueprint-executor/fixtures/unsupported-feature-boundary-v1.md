# Focused Fixture: Unsupported Feature Boundary

Generate a WordPress Playground Blueprint packet with
`wordpress-blueprint-executor` for this approved reproduction request:

- Purpose: demonstrate a plugin integration that normally calls a paid CRM API.
- The plugin can be installed from `./dist/acme-crm-sync.zip`.
- The real CRM requires credentials, persistent webhook callbacks, and a public
  HTTPS endpoint.
- The requested Blueprint must not include credentials, fake live endpoints, or
  claims that webhooks will work inside disposable Playground.
- Acceptable fallback: install/activate the plugin, create a sample settings
  page state if possible, add manual notes for adding a local mock endpoint, and
  include deterministic instructions for what cannot be reproduced in
  Playground.

## Expected Executor Focus

- Produce the smallest honest Blueprint that installs the plugin and sets up
  any deterministic local state.
- Include explicit unsupported-feature notes for external credentials,
  persistent webhook callbacks, custom containers, and public HTTPS callbacks.
- Include manual fallback instructions and critic handoff instead of pretending
  external services are reproduced.
- Keep generated JSON valid and disposable.

## Required Boundaries

Do not embed secrets, call live CRM endpoints, or claim Playground can reproduce
persistent webhook behavior without external infrastructure.
