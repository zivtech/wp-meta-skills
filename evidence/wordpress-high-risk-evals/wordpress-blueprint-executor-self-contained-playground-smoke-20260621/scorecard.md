# WordPress Blueprint Playground Smoke

- Run: `wordpress-blueprint-executor-self-contained-playground-smoke-20260621`
- Fixture: `self-contained-plugin-launch-v1`
- Status: `pass`
- Preflight summary: `evals/results/wordpress-blueprint-executor-self-contained-launch-preflight-20260621/launch-preflight-summary.json`
- Response status: `200`
- Landing seen: `true`
- Visible assertion found: `true`
- Browser: `playwright-default`

## Assertion

- Expected landing: `/wp-admin/admin.php?page=acme-inline-blueprint-smoke`
- Expected visible text: `Inline Blueprint Smoke Ready`
- Observed landing URL: `https://playground.wordpress.net/scope:ambitious-sunny-valley/wp-admin/admin.php?page=acme-inline-blueprint-smoke`

## Console And Runtime Messages

- `warning`: Loaded WordPress version (7.0) differs from requested version (latest).
- `log`: JQMIGRATE: Migrate is installed, version 3.4.1

## Boundary

This smoke proves the named Blueprint artifact launched in the observed WordPress Playground session and rendered the expected visible assertion. It does not prove benchmark quality, long-run variance, production deployment, broad plugin behavior, or external-service behavior.
