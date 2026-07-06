# wordpress-blueprint-executor Focused Eval Scaffold

Focused evaluation scaffold for `wordpress-blueprint-executor`. The suite now
contains the original broad smoke fixture plus four focused Blueprint executor
fixtures:

- `minimal-plugin-environment-v1`: local plugin install/activation, login or
  landing behavior, sample content, provenance, and static-vs-runtime boundary.
- `block-theme-reproduction-v1`: theme/plugin activation, block attributes,
  sample page content, permalink state, and frontend/editor follow-up.
- `unsupported-feature-boundary-v1`: external services, credentials, webhooks,
  public callbacks, deterministic fallback notes, and unsupported-feature
  honesty.
- `self-contained-plugin-launch-v1`: inline disposable plugin creation,
  activation, launch-readiness, and observed Playground smoke without VFS ZIP
  payloads.

This is not a benchmark result. Focused saved executor packets now exist under
`evals/suites/wordpress-blueprint-executor/examples/`, and deterministic static
certification results exist at
`evals/results/wordpress-blueprint-executor-static-cert-20260621/`. The three
focused packets passed packet contract, materialization, and static
`blueprint.json` artifact certification `3/3`. A launch-readiness preflight now
exists at
`evals/results/wordpress-blueprint-executor-launch-preflight-20260621/` and is
blocked because the certified Blueprints reference VFS plugin/theme ZIP payloads
that are not bundled in committed evidence. VFS-backed runtime claims still
need supplied payloads and their own Playground launch proof. Public benchmark
or broad runtime claims still need independent `test-critic` or QA review.

A self-contained packet now also exists at
`evals/suites/wordpress-blueprint-executor/examples/self-contained-plugin-launch-v1.materializable-packet.md`.
It passed static certification at
`evals/results/wordpress-blueprint-executor-self-contained-static-cert-20260621/`,
passed launch-readiness preflight at
`evals/results/wordpress-blueprint-executor-self-contained-launch-preflight-20260621/`,
and passed one browser-observed Playground smoke at
`evals/results/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/`.
That smoke proves only the self-contained artifact launched and rendered
`Inline Blueprint Smoke Ready`. A main-agent QA review now exists in the same
run directory and accepts the smoke as narrow internal runtime evidence with
reservations; it does not unblock the VFS-backed packets, replace independent
QA/test-critic review, or turn the suite into benchmark evidence.

Output contract oracle:

```bash
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-blueprint-executor \
  --output <candidate-output.md>
```

Deterministic packet oracle:

```bash
python3 evals/harness/validate_wordpress_executor_packet.py \
  --executor blueprint \
  --packet <candidate-output.md>
```

Packet materializer:

```bash
python3 evals/harness/materialize_wordpress_executor_packet.py \
  --executor blueprint \
  --packet <candidate-output.md> \
  --out-dir <generated-blueprint-dir>
```

Combined certification gate:

```bash
python3 evals/harness/certify_wordpress_executor_artifact.py \
  --executor blueprint \
  --packet <candidate-output.md> \
  --out-dir <generated-blueprint-dir> \
  --result-dir <result-dir> \
  --overwrite
```

Generated artifact oracle:

```bash
python3 evals/harness/validate_wordpress_artifact.py \
  --artifact-type blueprint \
  --path <generated-blueprint-dir>/blueprint.json
```

Static Blueprint validation proves JSON shape and non-empty steps only. Playground launch evidence still requires a separate runtime smoke record.

Launch-readiness preflight:

```bash
python3 evals/harness/audit_wordpress_blueprint_launch_readiness.py \
  --static-run-dir evals/results/wordpress-blueprint-executor-static-cert-20260621 \
  --out-dir evals/results/wordpress-blueprint-executor-launch-preflight-20260621
```

The current preflight status is `blocked`: all three focused Blueprints require
VFS plugin/theme ZIP payloads that are absent from the committed evidence
bundle.

Self-contained launch smoke:

```bash
node evals/harness/run_wordpress_blueprint_playground_smoke.js \
  --preflight-summary evals/results/wordpress-blueprint-executor-self-contained-launch-preflight-20260621/launch-preflight-summary.json \
  --fixture-id self-contained-plugin-launch-v1 \
  --expected-landing /wp-admin/admin.php?page=acme-inline-blueprint-smoke \
  --expected-text 'Inline Blueprint Smoke Ready' \
  --out-dir evals/results/wordpress-blueprint-executor-self-contained-playground-smoke-20260621
```

Negative space:

- This suite has one recorded live Playground reproduction for the
  self-contained packet only, plus a main-agent QA review of that smoke; the
  VFS-backed packets remain blocked without supplied ZIP payloads.
- Static Blueprint validation is not proof of frontend, editor, webhook, or
  external-service behavior.
- This suite does not prove `wordpress-blueprint-executor` outperforms a
  current ChatGPT-level baseline until scoring evidence and independent review
  exist.
