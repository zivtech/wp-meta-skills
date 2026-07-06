# wordpress-block-executor Smoke Eval

Smoke-tier evaluation scaffold for `wordpress-block-executor`. This suite provides one fixture, one rubric, and fair baselines so the skill has initial eval evidence without claiming full benchmark readiness.

Output contract oracle:

```bash
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-block-executor \
  --output <candidate-output.md>
```

Deterministic packet oracle:

```bash
python3 evals/harness/validate_wordpress_executor_packet.py \
  --executor block \
  --packet <candidate-output.md>
```

Packet materializer:

```bash
python3 evals/harness/materialize_wordpress_executor_packet.py \
  --executor block \
  --packet <candidate-output.md> \
  --out-dir <generated-block-dir>
```

Combined certification gate:

```bash
python3 evals/harness/certify_wordpress_executor_artifact.py \
  --executor block \
  --packet <candidate-output.md> \
  --out-dir <generated-block-dir> \
  --result-dir <result-dir> \
  --overwrite
```

Generated artifact oracle:

```bash
python3 evals/harness/validate_wordpress_artifact.py \
  --artifact-type block \
  --path <generated-block-dir>
```

Runtime proof requires explicit tooling, for example:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path <generated-block-dir> \
  --artifact-kind block \
  --block-build-smoke \
  --editor-insert-render-smoke \
  --provision-full-profile \
  --write \
  --run-id generated-block-full-profile-YYYYMMDD \
  --timeout-sec 300
```

The runtime harness wraps the generated block-only artifact in a disposable
plugin, infers the block name from `block.json` when `--block-name` is omitted,
and verifies npm build, WPCS/PHPCS, Plugin Check, editor insertion, and frontend
render. The repository smoke packet example is
`examples/smoke-wordpress-v1.materializable-packet.md`; its first local proof is
recorded at
`evals/results/wordpress-skill-candidate-eval/generated-block-full-profile-20260620/`.

For an Interactivity API generated-block proof, use
`examples/interactivity-wordpress-v1.materializable-packet.md` and add
`--interactivity-smoke` to the runtime command. The first local proof is
recorded at
`evals/results/wordpress-skill-candidate-eval/generated-block-interactivity-full-profile-20260621/`;
it verifies the compiled `viewScriptModule`, Interactivity API directives, and a
frontend click that changes the rendered count from `0` to `1`.

For a block deprecation generated-block proof, use
`examples/deprecation-wordpress-v1.materializable-packet.md` and add
`--deprecation-smoke` to the runtime command. The first local proof is recorded
at
`evals/results/wordpress-skill-candidate-eval/generated-block-deprecation-full-profile-20260621/`;
it creates a post from the legacy serialized fixture, verifies the migrated
current-block attribute, saves current serialized markup, and checks frontend
rendered text.
