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

Current generated-block runtime proof requires the direct artifact, its exact
pre-stage digest, an opaque evidence ID, and the fixture-owned block assertions.
For the tracked Acme Runtime Card packet, run:

```bash
artifact="<generated-block-dir>"
digest="$(PYTHONPATH=evals/harness python3 - "$artifact" <<'PY'
import sys
from pathlib import Path
from artifact_staging import digest_regular_tree
print(digest_regular_tree(Path(sys.argv[1])))
PY
)"
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path "$artifact" \
  --artifact-kind block \
  --expected-artifact-digest "$digest" \
  --evidence-id generated-runtime-card-full-profile-YYYYMMDD \
  --block-build-smoke \
  --block-name acme/runtime-card \
  --editor-insert-render-smoke \
  --expected-frontend-selector .wp-block-acme-runtime-card \
  --expected-frontend-text "Runtime block smoke" \
  --provision-full-profile \
  --strict-full-profile \
  --write \
  --run-id generated-runtime-card-full-profile-YYYYMMDD \
  --timeout-sec 300
```

The runtime harness wraps the generated block-only artifact in a disposable
plugin and verifies the digest before staging, npm build, the exact registered
block identity, WPCS/PHPCS, Plugin Check, selector-scoped editor insertion, and
frontend text. The reviewed assertion values are not inferred from generated
prose. The repository smoke packet example is
`examples/smoke-wordpress-v1.materializable-packet.md`; its first local proof is
recorded at
`evals/results/wordpress-skill-candidate-eval/generated-block-full-profile-20260620/`.
That directory is historical evidence; rerun the command above on the current
artifact before making a current runtime claim.

`examples/interactivity-wordpress-v1.materializable-packet.md` remains a
materializable static example. External generated-block Interactivity runtime
mode is unsupported by the current isolated artifact path. The result at
`evals/results/wordpress-skill-candidate-eval/generated-block-interactivity-full-profile-20260621/`;
is historical built-in-fixture evidence only; it does not prove the current
external packet's Interactivity behavior. The packet may use the standard bound
build/editor/frontend command documented inside it, without an Interactivity
claim.

`examples/deprecation-wordpress-v1.materializable-packet.md` likewise remains a
materializable static example. External generated-block deprecation runtime
mode is unsupported by the current isolated artifact path. The result at
`evals/results/wordpress-skill-candidate-eval/generated-block-deprecation-full-profile-20260621/`;
is historical built-in-fixture evidence only and does not establish current
external-packet migration behavior. The packet may prove only the standard
bound build/editor/frontend profile until the isolated artifact adapter gains a
fixture-owned deprecation contract.
