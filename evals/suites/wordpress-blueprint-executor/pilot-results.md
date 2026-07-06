# Pilot Results

Status: focused static certification evidence, launch-readiness preflight, and
one self-contained Playground smoke with main-agent QA review exist; not
benchmark mature.

The suite now has the original smoke fixture plus four focused fixtures:

- `minimal-plugin-environment-v1`
- `block-theme-reproduction-v1`
- `unsupported-feature-boundary-v1`
- `self-contained-plugin-launch-v1`

Current evidence:

- Fixture, metadata, and rubric files exist for each focused fixture.
- Strict suite integrity validation passes for `wordpress-blueprint-executor`.
- Focused saved executor packets exist under
  `evals/suites/wordpress-blueprint-executor/examples/`:
  - `minimal-plugin-environment-v1.materializable-packet.md`
  - `block-theme-reproduction-v1.materializable-packet.md`
  - `unsupported-feature-boundary-v1.materializable-packet.md`
  - `self-contained-plugin-launch-v1.materializable-packet.md`
- Static certification run:
  `evals/results/wordpress-blueprint-executor-static-cert-20260621/`.
- The three focused packets passed packet contract, materialization, and static
  `blueprint.json` artifact certification `3/3`.
- Launch-readiness preflight run:
  `evals/results/wordpress-blueprint-executor-launch-preflight-20260621/`.
- Preflight status: `blocked`, because all three generated Blueprints reference
  VFS plugin/theme ZIP payloads that are absent from the committed evidence
  bundle:
  - `/wordpress/wp-content/uploads/acme-notice-board.zip`
  - `/wordpress/wp-content/uploads/acme-block-theme.zip`
  - `/wordpress/wp-content/uploads/acme-events-block.zip`
  - `/wordpress/wp-content/uploads/acme-crm-sync.zip`
- Self-contained static certification run:
  `evals/results/wordpress-blueprint-executor-self-contained-static-cert-20260621/`.
- Self-contained launch-readiness preflight run:
  `evals/results/wordpress-blueprint-executor-self-contained-launch-preflight-20260621/`,
  status `ready_for_manual_launch`.
- Self-contained Playground smoke run:
  `evals/results/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/`,
  status `pass`. The browser reached
  `/wp-admin/admin.php?page=acme-inline-blueprint-smoke` and found visible text
  `Inline Blueprint Smoke Ready`. It recorded a warning that Playground loaded
  WordPress `7.0` while the Blueprint requested `latest`.
- Main-agent QA review:
  `evals/results/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/qa-review.md`,
  accepting the self-contained smoke as narrow internal runtime evidence with
  reservations.

Still missing before benchmark or release-quality claims:

- saved current ChatGPT-level baseline outputs;
- the referenced VFS payloads for the three VFS-backed packets, if those
  packets need live launch proof;
- independent `test-critic` or QA review of the suite design and scoring
  interpretation.

This suite remains experimental until those gates are run. It does not prove
frontend/editor behavior beyond the self-contained admin-page smoke,
external-service behavior, webhook persistence, or superiority over a current
baseline.
