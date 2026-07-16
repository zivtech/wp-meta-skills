# Eval Harness

Repeatable runners and scoring infrastructure for the zivtech-meta-skills eval suites.

## Scripts

| Script | Purpose |
|---|---|
| `run_design_smoke.py` | Batch runner for 8 design suites (critic / planner) |
| `run_design_control_calibration.py` | Baseline control calibration gate for the design-tooling benchmark |
| `run_jtbd_simulation.py` | Two-LLM simulation runner for the JTBD interviewer |
| `llm_judge.py` | LLM-as-judge scoring (replaces semantic similarity) |
| `stratified_reporter.py` | Difficulty-stratified result reporting |
| `multi_epoch.py` | Multi-epoch runs with SEM and 95% CI |
| `invoke.py` | Unified skill invocation abstraction |
| `run_math_science_oracles.py` | Oracle-readiness smoke checks for math/science tooling fixtures |
| `validate_math_science_route_results.py` | Route-run result validation for math/science tooling pilots |
| `summarize_math_science_route_results.py` | Route-run pre-aggregation and target-tier readiness summary |
| `summarize_math_science_paired_readiness.py` | Paired comparison readiness and missing baseline/model worklist for math/science route pilots |
| `generate_math_science_baseline_packets.py` | Generates executable prompt packets and route-result templates for approved baseline comparison rows |
| `execute_math_science_baseline_packets.py` | Executes approved baseline packet templates into candidate outputs, oracle outputs, and route-run results |
| `execute_math_science_candidate_routes.py` | Executes full-scaffold pilot/local deterministic candidate rows from the coverage worklist |
| `execute_math_science_frontier_routes.py` | Executes approved public/synthetic frontier-model route rows with tools disabled and model/cost metadata recorded |
| `prepare_math_science_human_review.py` | Prepares RNA-seq expert-review packet and human-review gate route results |
| `validate_math_science_human_review.py` | Validates a completed RNA-seq human-review form before any oracle gate is cleared |
| `run_math_science_deseq2_live_r_parity.py` | Runs the approved live R/DESeq2 public pasilla parity check and emits a smoke route result |
| `summarize_math_science_paired_deltas.py` | Computes target-tier candidate-vs-baseline paired deltas once comparison rows are complete |
| `summarize_math_science_benchmark_power.py` | Computes planning MDE/power estimates from paired delta outputs |
| `validate_wordpress_executor_packet.py` | Deterministic contract oracle for WordPress plugin/block/blueprint executor packets |
| `materialize_wordpress_executor_packet.py` | Converts materializable WordPress plugin/block/blueprint executor packets into generated artifact files |
| `validate_wordpress_artifact.py` | Deterministic static/runtime oracle for generated WordPress plugin/block/theme/blueprint artifacts |
| `wp_api_lint.py` | API-existence and version-range lint for generated PHP (PHPStan + wordpress-stubs + wp-compat, did-you-mean suggestions) |
| `certify_wordpress_executor_artifact.py` | One-command WordPress executor packet -> materialization -> artifact certification pipeline |
| `audit_wordpress_blueprint_launch_readiness.py` | Preflight audit for generated Blueprint launch readiness and missing VFS payloads |
| `validate_wordpress_skill_output.py` | Deterministic output-contract oracle for saved WordPress planner/executor/critic responses |
| `run_wordpress_runtime_smoke.py` | Disposable wp-env smoke harness for the WordPress artifact oracle runtime lane |
| `safe_curl.py` | Fixed-path, no-ambient-config curl transport with bounded response and anonymous header-FD support |
| `provider_preflight.py` | Exact Ollama/Gemini metadata policy, sanitized receipts, and bounded provider generation adapters |
| `run_executor_repair_loop.py` | Bounded generation, certification, repair, and re-certification loop |

## Suite Integrity

Eval suites should keep fixture, metadata, and rubric contracts aligned:

- Every YAML document is limited to 1 MiB and must use unique mapping keys;
  anchors, aliases, and explicit tags are rejected before construction.
- Each eval config, metadata document, and rubric must match exactly one named
  schema profile. New intentional families require a named rule plus positive
  and negative contract tests.
- `fixtures.count` should match the number of fixture Markdown files.
- Every fixture should have matching metadata using the configured `metadata_suffix`.
- Every scoreable fixture should have a matching rubric in the configured `rubrics.directory`.
- Weighted rubric criteria require unique IDs, positive finite weights, and a
  total within an absolute `1e-6` tolerance of `max_score`. Missing criterion
  categories mean `quality`; the only other accepted weighted category is
  `false_positive_trap`, which the scorer inverts.
- Domain signals are score-bearing: expected WordPress APIs and artifact
  surfaces add one aggregate positive criterion, while each `must_not_claim`
  and `must_not_penalize_or_do` item adds a distinct inverted trap. Direct
  scorer calls reject malformed, blank, or unknown domain-signal values.
- Placeholder markers such as `TBD`, `[Finding]`, and `Placeholder` should not appear in scoreable metadata or rubric files.

Run a repo-wide report:

```bash
python3 scripts/validate-eval-suite-integrity.py
```

Run a strict check for suites being actively repaired:

```bash
python3 scripts/validate-eval-suite-integrity.py --strict-suites dashboard-planner,proposal-critic --allow-known-gaps
```

Known quarantined content gaps are recorded in [`evals/suites/QUALITY_GAPS.md`](../suites/QUALITY_GAPS.md). A known gap is not publication-ready benchmark evidence; it is an explicit marker that the suite still needs human completion.
YAML parsing and schema validation run before placeholder/content checks, and
structural `invalid_*`, `duplicate_*`, and `schema_*` issues cannot be
quarantined with `--allow-known-gaps`.

For WordPress executor outputs, validate saved packets before judge- or critic-based review:

```bash
python3 evals/harness/validate_wordpress_executor_packet.py --executor plugin --packet <candidate-output.md>
python3 evals/harness/validate_wordpress_executor_packet.py --executor block --packet <candidate-output.md>
python3 evals/harness/validate_wordpress_executor_packet.py --executor blueprint --packet <candidate-output.md>
```

Materialize plugin, block, or Blueprint packets into files before running artifact oracles:

```bash
python3 evals/harness/materialize_wordpress_executor_packet.py --executor plugin --packet <candidate-output.md> --out-dir <generated-plugin-dir>
python3 evals/harness/materialize_wordpress_executor_packet.py --executor block --packet <candidate-output.md> --out-dir <generated-block-dir>
python3 evals/harness/materialize_wordpress_executor_packet.py --executor blueprint --packet <candidate-output.md> --out-dir <generated-blueprint-dir>
```

The materializer requires each generated plugin or block file to appear as `### relative/path.ext` immediately followed by one fenced code block. Blueprint packets must include one fenced JSON object under `## Generated Blueprint`; the materializer writes it to `blueprint.json`.

## Exact-surface evidence boundaries

The saved-output and rubric contract uses two version-aligned data files. The
core function/class set comes from `data/wp-symbols.json`; reviewed non-core
hooks, keys, capabilities, commands, packages, tools, paths, and composed
surfaces come from `data/wp-exact-surfaces.json`. These support four distinct
claims:

1. Registry or core-symbol existence means the named surface is in a reviewed
   WordPress 7.0 contract boundary.
2. Output occurrence means the full surface was found contiguously with safe
   identifier boundaries; partial names and scattered words do not count.
3. Scoped non-applicability means a named subproblem includes a reason and a
   concrete oracle or owner. It never waives the output's minimum surfaces.
4. Runtime proof requires the applicable artifact/runtime oracle and its
   evidence packet.

The first three claims do not prove the fourth. In particular, a registered
third-party package or hook is reviewed contract vocabulary, not proof that it
is installed, callable, compatible, or exercised in the target runtime.

After materializing generated files, run the artifact oracle before making code-generation claims:

```bash
python3 evals/harness/validate_wordpress_artifact.py --artifact-type plugin --path <generated-plugin-dir>
python3 evals/harness/validate_wordpress_artifact.py --artifact-type block --path <generated-block-dir>
python3 evals/harness/validate_wordpress_artifact.py --artifact-type theme --path <generated-theme-dir>
python3 evals/harness/validate_wordpress_artifact.py --artifact-type blueprint --path <generated-blueprint-dir>/blueprint.json
```

For plugin artifacts, the static oracle also checks cheap WPCS-shape failures and modern WordPress AI surfaces. Plugin-header files must include a file-level `@package` tag, and obvious short `[]` array literals fail before expensive runtime checks. Abilities API code must use `wp_abilities_api_init`, `wp_register_ability()`, `label`, `description`, `category`, `input_schema`, `output_schema`, `execute_callback`, `permission_callback`, and either `Requires at least: 6.9` or a `function_exists( 'wp_register_ability' )` guard. AI Client code must guard or require WordPress 7.0+, handle `is_wp_error()`, and show a capability or prompt-prevention boundary. MCP Adapter references must name adapter initialization and exposed abilities. This static WPCS-shape check is not a substitute for `phpcs --standard=WordPress`; use `phpcs`/`wpcs` runtime gates for full coding-standards claims.

Use repeated `--require-tool` flags for environment-backed proof such as `phpcs`, `phpunit`, `plugin-check`, `npm-build`, or `wp-env`; reserve `--profile runtime` for the full default runtime contract. Pass `--wp-env-root <wp-env-project-root>` when the artifact lives under a separate `@wordpress/env` project root. Missing required tools produce `blocked`, not `pass`.

The static oracle also runs the API-existence lint (`api_existence`) for plugin, block, and theme artifacts that contain PHP. It requires the pinned PHP toolchain (one-time setup, PHP >= 8.1):

```bash
composer install --working-dir evals/harness/php-tools
```

Without the toolchain the check reports `blocked` — honest evidence, never a pass. The lint flags unknown core functions/classes/methods with did-you-mean suggestions and core symbols/hooks newer than the declared `Requires at least:` header; `function_exists()` guards suppress version-range findings through real scope analysis. It can also run standalone with a full JSON findings report:

```bash
python3 evals/harness/wp_api_lint.py --path <generated-plugin-dir> --out api-lint.json
```

Phase-1 negative space (also stated in every report): unknown hook names are not detected yet, string callbacks and PHP constants are not checked at PHPStan level 0, artifact `tests/` directories are excluded (the `phpunit` runtime gate owns test code), and WooCommerce/third-party symbol sets land in a later phase. See `docs/wordpress/runtime-oracle-runbook.md` for evidence semantics.

To run the full deterministic executor chain in one command, use the certifier:

```bash
python3 evals/harness/certify_wordpress_executor_artifact.py --executor plugin --packet <candidate-output.md> --out-dir <generated-plugin-dir> --result-dir <result-dir> --overwrite
python3 evals/harness/certify_wordpress_executor_artifact.py --executor block --packet <candidate-output.md> --out-dir <generated-block-dir> --result-dir <result-dir> --overwrite
python3 evals/harness/certify_wordpress_executor_artifact.py --executor blueprint --packet <candidate-output.md> --out-dir <generated-blueprint-dir> --result-dir <result-dir> --overwrite
```

The certifier writes `certification.json` and `scorecard.md` when `--result-dir` is provided, plus `api-lint.json` with the full API-existence findings whenever the artifact gate ran the lint. Failed or blocked certifications also write `repair-prompt.md`, a deterministic evaluator-feedback prompt that names the failing gate IDs, constraints, and fence-safe embedded saved packet for the next revision loop. It is the preferred inner-loop gate for executor outputs because it fails before artifact validation when the saved packet is malformed or non-materializable, and it produces model-readable feedback when an artifact gate fails.

Before claiming a generated Blueprint can launch in WordPress Playground, run
the launch-readiness preflight against the static certification output:

```bash
python3 evals/harness/audit_wordpress_blueprint_launch_readiness.py \
  --static-run-dir evals/results/wordpress-blueprint-executor-static-cert-20260621 \
  --out-dir evals/results/wordpress-blueprint-executor-launch-preflight-YYYYMMDD
```

This preflight is not a browser runtime. It blocks when the generated Blueprint
references VFS plugin/theme ZIP payloads that are not present in the committed
evidence bundle, and it writes a scorecard naming the missing payloads.

To prove the local `php-lint` plus `wp-env` lane without hand-building a fixture, run the disposable runtime smoke harness:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py --write --run-id wp-env-runtime-smoke-YYYYMMDD --timeout-sec 300
```

This harness creates a temporary plugin fixture, starts `@wordpress/env` with automatic port selection, runs `validate_wordpress_artifact.py` with `--require-tool php-lint --require-tool wp-env`, records the full plugin runtime profile as informational, then stops the environment.

`--workdir` selects an optional caller-owned parent, not the fixture root. Each
invocation creates a unique leased child beneath that parent and writes all
runtime files there. Callers must not expect files at the parent root. The JSON
summary reports the child as `runtime_root` and the supplied parent as
`workdir_parent`. `--keep-artifacts` and `--keep-running` retain the unique
child; otherwise the harness verifies its ownership sentinel before removing
only that child.

To provision and require the full disposable plugin runtime profile, including Composer-installed WPCS and Plugin Check inside `wp-env`, run:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py --provision-full-profile --write --run-id wp-env-runtime-full-profile-YYYYMMDD --timeout-sec 300
```

To prove a generated plugin artifact that includes a PHPUnit suite, first certify and materialize the packet, then run the generated plugin through the disposable runtime harness:

```bash
artifact="<generated-plugin-dir>/<plugin-slug>"
digest="$(PYTHONPATH=evals/harness python3 - "$artifact" <<'PY'
import sys
from pathlib import Path
from artifact_staging import digest_regular_tree
print(digest_regular_tree(Path(sys.argv[1])))
PY
)"
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path "$artifact" \
  --expected-artifact-digest "$digest" \
  --evidence-id generated-plugin-phpunit-full-profile-YYYYMMDD \
  --phpunit-smoke \
  --provision-full-profile \
  --strict-full-profile \
  --write \
  --run-id generated-plugin-phpunit-full-profile-YYYYMMDD \
  --timeout-sec 300
```

When the copied plugin artifact contains `composer.json`, the harness runs `composer install` inside the disposable copy before activating the plugin and running `phpunit`. With `--provision-full-profile`, the same run also requires WPCS/PHPCS and Plugin Check. This proves plugin activation, artifact-local PHPUnit, WPCS/PHPCS, Plugin Check, and the isolated container browser; it does not prove block/editor behavior, MCP Adapter exposure, AI Client provider calls, or broad integration coverage.

The isolated external-artifact path does not support the historical MCP Adapter
or AI Client special modes. Those built-in-fixture modes remain diagnostic-only;
historical result directories do not establish current external-artifact
support and cannot substitute for the standard isolated runtime contract.

To prove a disposable block is visible to both server-side and editor-side block registries, run:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py --fixture-kind block --block-name acme/runtime-card --editor-smoke --write --run-id wp-env-block-editor-smoke-YYYYMMDD --timeout-sec 180
```

To prove disposable block insertion, save/publish, and frontend server render, run:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py --fixture-kind block --block-name acme/runtime-card --editor-insert-render-smoke --expected-frontend-selector .wp-block-acme-runtime-card --expected-frontend-text "Runtime block smoke" --write --run-id wp-env-block-editor-insert-render-smoke-YYYYMMDD --timeout-sec 180
```

To prove a generated block executor artifact through build, full profile, and editor insert/render paths, first materialize/certify the packet, then let the runtime harness wrap the block-only artifact in a disposable plugin:

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
  --evidence-id generated-block-full-profile-YYYYMMDD \
  --block-build-smoke \
  --block-name vendor/block-name \
  --editor-insert-render-smoke \
  --expected-frontend-selector .wp-block-vendor-block-name \
  --expected-frontend-text "Exact fixture-owned text" \
  --provision-full-profile \
  --strict-full-profile \
  --write \
  --run-id generated-block-full-profile-YYYYMMDD \
  --timeout-sec 300
```

For an external artifact, all three assertion values are required and the declared
block name must equal the selected `block.json` name. The assertion is executed
inside the staged isolated runtime; no ordinary `wp-env` or host-browser fallback
is allowed. This proves the bounded build, exact graph scan, registration, narrow
authenticated post update, and selector/text frontend result for that artifact.
It does not prove PHPUnit, deprecation migration, Interactivity API behavior,
MCP Adapter exposure, AI Client provider-call behavior, or release readiness.
These direct CLI values are operator-supplied. Only
`run_executor_repair_loop.py` binds assertions to a canonical suite fixture
pair, and no tracked block-executor fixture currently contains that optional
mapping.

## Repair-loop provider preflight

The explicit `ollama` and `gemini` lanes require `--model`; there is no aging
repository default. Before creating a packet or invoking a model, the repair
loop checks the exact Ollama tag through loopback `/api/show`, or the exact
Gemini model through the official models metadata API. Gemini must return the
same canonical `models/{id}` name and advertise `generateContent`.

Provider HTTPS uses `safe_curl.py`: a fixed root-owned system curl 8.4.0 or
newer, first option `--disable`, minimal environment, no redirects or ambient
proxy/CA/config, and an anonymous header file descriptor for `x-goog-api-key`.
The version floor makes `--max-filesize` a response-memory bound even when the
server omits content length. The key is absent from
the URL, argv, disk, response diagnostics, and `provider-preflight.json`.
Failures persist only schema version, provider, validated model, timestamp,
status, endpoint class, and bounded error code. If trusted curl/header-FD/TLS is
unavailable, the lane is blocked; it does not fall back to query authentication,
temporary credential files, `--insecure`, or inherited configuration.

The explicit `live_provider` pytest marker performs metadata preflight only and
is excluded from ordinary CI. It also requires
`WP_META_SKILLS_LIVE_PROVIDER_AUTHORIZED=1`; missing authorization, model, or
credential fails this manual gate rather than skipping it. A pass proves the
bounded transport and advertised
metadata for that request. It does not make a generation call or prove quota,
billing authorization, content quality, or future model availability.

The repair-loop support matrix is plugin static/runtime, block static plus
assertion-conditional runtime, and Blueprint static-only. Blueprint launch
preflight/browser checks remain separate and cannot satisfy repair runtime.

Interactivity and deprecation-specific checks are not supported for an external
staged artifact or by the repair loop. Their legacy built-in harness-fixture
paths do not satisfy the `block-runtime` adapter and cannot substitute for its
exact fixture-owned selector/text proof. Historical result directories are not
evidence that these modes are available through the current isolated artifact
boundary.

For any saved WordPress skill response, validate the output contract before scoring:

```bash
python3 evals/harness/validate_wordpress_skill_output.py --skill wordpress-planner.plugin --output <candidate-output.md>
python3 evals/harness/validate_wordpress_skill_output.py --skill wordpress-critic --output <candidate-output.md>
```

This gate checks required headings, critic verdict shape, exact WordPress surfaces, concrete verification terms, negative-space language, placeholder markers, and generic WordPress labels.

---

## Quick Start

Run the design smoke suite (3 fixtures × 3 conditions per suite):

```bash
./evals/harness/run_design_smoke.sh
```

Targeted subset:

```bash
./evals/harness/run_design_smoke.sh --suites "ui-critic,web-design-critic"
```

Fast partial check (first fixture per suite):

```bash
./evals/harness/run_design_smoke.sh --max-fixtures 1
```

Re-score an existing run:

```bash
./evals/harness/run_design_smoke.sh --mode score --run-id design-smoke-YYYY-MM-DD-HHMMSS
```

Rerun failed cases only:

```bash
./evals/harness/run_design_smoke.sh --mode rerun-failures --run-id design-smoke-YYYY-MM-DD-HHMMSS
```

---

## Outputs

Each run writes to:

- `evals/results/<run-id>/raw/...`
- `evals/results/<run-id>/summary.json`
- `evals/results/<run-id>/scorecard.md`

---

## Scoring Model (existing, run_design_smoke.py)

The design smoke harness computes:

- Contract score: output contract marker coverage
- Semantic score: rubric-semantic extraction (`must_find`, `should_find`, `nice_to_find`)
- Verdict match rate: expected vs produced verdicts

Composite per condition:

- `40% contract + 30% semantic + 30% verdict-match`

This is intended for smoke benchmarking, not final statistical publication.

---

## 6.0.1 LLM-as-Judge Scoring (`llm_judge.py`)

Replaces keyword-based semantic similarity with rubric-aware LLM grading.
Each `must_find` / `should_find` criterion is scored independently by the judge.

The judge also supports candidate-comparison rubrics that use top-level weighted
`criteria` plus fixture-specific `domain_signals`. For those rubrics, positive
criteria earn their explicit weight when met, and `false_positive_trap` criteria
earn their weight when they are not triggered.

### Cost controls

| Model | When used |
|---|---|
| `claude-haiku-4-5` | Default judge — all initial scoring |
| `claude-sonnet-4-6` | Re-grade when initial confidence < 0.6 |

Low-confidence criteria are flagged `human_review_required: true` in the output.

### Standalone usage

```bash
# Requires ANTHROPIC_API_KEY
python3 evals/harness/llm_judge.py   # not a CLI; import as a module
```

### Programmatic usage

```python
from evals.harness.llm_judge import score_output_file, judge_result_to_dict
from pathlib import Path

result = score_output_file(
    output_path=Path("evals/results/my-run/raw/qa-critic/skill/clean-api-crud-suite.md"),
    rubric_path=Path("evals/suites/qa-critic/rubrics/clean-api-crud-suite.rubric.yaml"),
    fixture_id="clean-api-crud-suite",
    condition="skill",
)
print(result.composite_score)       # 0 – 100
print(result.human_review_required) # True if any criterion was low-confidence
print(judge_result_to_dict(result)) # JSON-serialisable dict
```

### Output schema (JudgeResult)

```json
{
  "fixture_id": "clean-api-crud-suite",
  "condition": "skill",
  "composite_score": 87.5,
  "must_find_score": 100.0,
  "should_find_score": 75.0,
  "nice_to_find_score": 100.0,
  "false_positive_penalty": 0.0,
  "human_review_required": false,
  "model_used": "claude-haiku-4-5",
  "criteria": [
    {
      "criterion_id": "MF1",
      "category": "must_find",
      "description": "...",
      "met": true,
      "confidence": 0.95,
      "reasoning": "The output explicitly calls out...",
      "flagged_for_review": false,
      "regraded": false
    }
  ]
}
```

---

## 6.0.2 Difficulty-Stratified Reporting (`stratified_reporter.py`)

Groups eval results by fixture difficulty level and reports per-stratum scores.

### Difficulty normalisation

The reporter normalises vocabulary across suites:

| Raw value | Normalised |
|---|---|
| `easy`, `CLEAN`, `BASELINE` | `easy` |
| `medium`, `HAS-BUGS`, `FLAWED`, `MODERATE` | `medium` |
| `hard`, `ADVERSARIAL`, `HARD` | `hard` |

### Standalone usage

```bash
python3 evals/harness/stratified_reporter.py \
    --run-id design-smoke-YYYY-MM-DD-HHMMSS \
    --suite qa-critic \
    --save
```

Outputs:
- Terminal summary table
- `evals/results/<run-id>/stratified-<suite>.json` (with `--save`)

### Programmatic usage

```python
from evals.harness.stratified_reporter import generate_stratified_report, save_stratified_report

report = generate_stratified_report(
    run_id="design-smoke-2026-03-28-120000",
    suite="qa-critic",
)
# report["strata"]["easy"]["skill"]["mean"]  → float
# report["baseline_comparison"]["hard"]["skill_minus_baseline-zero-shot"]  → float
save_stratified_report(report, run_id, suite)
```

---

## Math/Science Oracle Smoke Checks

Before comparing model/tool routes, run the deterministic oracle layer:

```bash
python3 evals/harness/run_math_science_oracles.py --write
```

Before aggregating candidate route comparisons, validate route-run result YAML files:

```bash
python3 evals/harness/validate_math_science_route_results.py
```

Then generate the standard-tier readiness summary:

```bash
python3 evals/harness/summarize_math_science_route_results.py --write
```

For the standard-tier gate, prefer the explicit tier flag:

```bash
python3 evals/harness/summarize_math_science_route_results.py --target-tier standard --write
python3 evals/harness/plan_math_science_route_coverage.py --write
python3 evals/harness/summarize_math_science_paired_readiness.py
python3 evals/harness/generate_math_science_baseline_packets.py --readiness evals/results/math-science-route-coverage-plan-2026-05-19-full-scaffold/route-coverage-plan.json --run-id math-science-baseline-execution-packets-2026-05-19-full-scaffold
python3 evals/harness/execute_math_science_baseline_packets.py
python3 evals/harness/execute_math_science_candidate_routes.py
python3 evals/harness/prepare_math_science_human_review.py
python3 evals/harness/validate_math_science_human_review.py evals/results/math-science-rnaseq-human-review-2026-05-19/review-form.template.yaml --template-ok
python3 evals/harness/run_math_science_deseq2_live_r_parity.py
python3 evals/harness/plan_math_science_route_coverage.py --target-tier standard --run-id math-science-route-coverage-plan-2026-05-19-full-scaffold --write
python3 evals/harness/validate_math_science_route_results.py
python3 evals/harness/summarize_math_science_route_results.py --target-tier standard --run-id math-science-route-summary-2026-05-19-full-scaffold --write
python3 evals/harness/summarize_math_science_paired_deltas.py --run-id math-science-paired-delta-analysis-2026-05-19-full-scaffold --write
python3 evals/harness/summarize_math_science_benchmark_power.py --delta-analysis evals/results/math-science-paired-delta-analysis-2026-05-19-full-scaffold/paired-delta-analysis.json --run-id math-science-benchmark-power-2026-05-19-full-scaffold --write
```

For the benchmark-local gate that excludes human-review fixtures, frontier rows, and newly approval-gated MCP reruns:

```bash
python3 evals/harness/plan_math_science_route_coverage.py --target-tier benchmark --omit-frontier --run-id math-science-route-coverage-plan-2026-05-19-benchmark-local --write
python3 evals/harness/generate_math_science_baseline_packets.py --readiness evals/results/math-science-route-coverage-plan-2026-05-19-benchmark-local/route-coverage-plan.json --run-id math-science-baseline-execution-packets-2026-05-19-benchmark-local --exclude-human-review
python3 evals/harness/execute_math_science_baseline_packets.py --packet-root evals/results/math-science-baseline-execution-packets-2026-05-19-benchmark-local --summary evals/results/math-science-baseline-execution-packets-2026-05-19-benchmark-local/baseline-batch-execution-summary.json
python3 evals/harness/execute_math_science_candidate_routes.py --worklist evals/results/math-science-route-coverage-plan-2026-05-19-benchmark-local/candidate-worklist.csv --summary evals/results/math-science-route-coverage-plan-2026-05-19-benchmark-local/candidate-route-execution-summary.json
python3 evals/harness/validate_math_science_route_results.py
python3 evals/harness/summarize_math_science_route_results.py --target-tier benchmark --run-id math-science-route-summary-2026-05-19-benchmark-local --write
python3 evals/harness/summarize_math_science_paired_readiness.py --target-tier benchmark --run-id math-science-paired-readiness-2026-05-19-benchmark-local --comparison-condition current-zivtech-baseline --comparison-condition baseline-zero-shot --comparison-condition baseline-few-shot
python3 evals/harness/summarize_math_science_paired_deltas.py --target-tier benchmark --run-id math-science-paired-delta-analysis-2026-05-19-benchmark-local --write
python3 evals/harness/summarize_math_science_benchmark_power.py --delta-analysis evals/results/math-science-paired-delta-analysis-2026-05-19-benchmark-local/paired-delta-analysis.json --run-id math-science-benchmark-power-2026-05-19-benchmark-local --write
```

For the user-approved benchmark gate that includes approved MCP reruns and approved frontier-model rows while keeping human-review fixtures blocked:

```bash
python3 evals/harness/plan_math_science_route_coverage.py --target-tier benchmark --approve-sandbox --approve-frontier --run-id math-science-route-coverage-plan-2026-05-19-benchmark-approved --write
python3 evals/suites/math-science-tooling/pilots/run_standard_route_repetitions.py --repetition-tier benchmark --repetitions 5 --run-date 2026-05-19 --approval-status approved_by_user_2026-05-19 --mcp-only
python3 evals/harness/execute_math_science_frontier_routes.py --worklist evals/results/math-science-route-coverage-plan-2026-05-19-benchmark-approved/frontier-worklist.csv --workers 4 --summary evals/results/math-science-route-coverage-plan-2026-05-19-benchmark-approved/frontier-route-execution-summary.json
python3 evals/harness/validate_math_science_route_results.py
python3 evals/harness/summarize_math_science_route_results.py --target-tier benchmark --run-id math-science-route-summary-2026-05-19-benchmark-approved --write
python3 evals/harness/summarize_math_science_paired_readiness.py --target-tier benchmark --run-id math-science-paired-readiness-2026-05-19-benchmark-approved --comparison-condition current-zivtech-baseline --comparison-condition baseline-zero-shot --comparison-condition baseline-few-shot
python3 evals/harness/summarize_math_science_paired_deltas.py --target-tier benchmark --run-id math-science-paired-delta-analysis-2026-05-19-benchmark-approved --write
python3 evals/harness/summarize_math_science_benchmark_power.py --delta-analysis evals/results/math-science-paired-delta-analysis-2026-05-19-benchmark-approved/paired-delta-analysis.json --run-id math-science-benchmark-power-2026-05-19-benchmark-approved --write
```

Outputs:

- Terminal summary of fixture oracle status
- `evals/results/<run-id>/oracle-smoke.json`
- `evals/results/<run-id>/scorecard.md`
- `evals/results/<run-id>/route-summary.json`
- `evals/results/<run-id>/route-summary.md`
- `evals/results/<run-id>/route-coverage-plan.json`
- `evals/results/<run-id>/route-coverage-plan.md`
- `evals/results/<run-id>/baseline-worklist.csv`
- `evals/results/<run-id>/candidate-worklist.csv`
- `evals/results/<run-id>/frontier-worklist.csv`
- `evals/results/<run-id>/approval-gated-worklist.csv`
- `evals/results/<run-id>/deseq2-live-r-top10.csv`
- `evals/results/<run-id>/paired-delta-analysis.json`
- `evals/results/<run-id>/paired-delta-analysis.md`
- `evals/results/<run-id>/paired-delta-comparisons.csv`
- `evals/results/<run-id>/benchmark-power.json`
- `evals/results/<run-id>/benchmark-power.md`

Current math/science standard-tier evidence lives in:

- `evals/results/math-science-route-result-validation-2026-05-17/`
- `evals/results/math-science-route-summary-2026-05-18/`
- `evals/results/math-science-route-summary-2026-05-19-full-scaffold/`
- `evals/results/math-science-route-coverage-plan-2026-05-19-full-scaffold/`
- `evals/results/math-science-baseline-execution-packets-2026-05-19-full-scaffold/`
- `evals/results/math-science-route-coverage-plan-2026-05-19-benchmark-local/`
- `evals/results/math-science-baseline-execution-packets-2026-05-19-benchmark-local/`
- `evals/results/math-science-route-summary-2026-05-19-benchmark-local/`
- `evals/results/math-science-route-coverage-plan-2026-05-19-benchmark-approved/`
- `evals/results/math-science-route-summary-2026-05-19-benchmark-approved/`
- `evals/results/math-science-paired-readiness-2026-05-19-benchmark-approved/`
- `evals/results/math-science-paired-delta-analysis-2026-05-19-benchmark-approved/`
- `evals/results/math-science-benchmark-power-2026-05-19-benchmark-approved/`
- `evals/results/math-science-rnaseq-human-review-2026-05-19/`
- `evals/results/math-science-deseq2-live-r-parity-2026-05-19/`
- `evals/results/math-science-route-summary-2026-05-17/`
- `evals/results/math-science-standard-tier-analysis-2026-05-17/`
- `evals/results/math-science-paired-comparison-readiness-2026-05-18/`
- `evals/results/math-science-paired-comparison-readiness-2026-05-19-full-scaffold/`
- `evals/results/math-science-baseline-execution-packets-2026-05-18/`
- `evals/results/math-science-paired-delta-analysis-2026-05-18/`
- `evals/results/math-science-paired-delta-analysis-2026-05-19-full-scaffold/`
- `evals/results/math-science-paired-delta-analysis-2026-05-19-benchmark-local/`
- `evals/results/math-science-benchmark-power-2026-05-18/`
- `evals/results/math-science-benchmark-power-2026-05-19-full-scaffold/`
- `evals/results/math-science-benchmark-power-2026-05-19-benchmark-local/`
- `evals/results/math-science-oracle-smoke-2026-05-18-fixture-expansion/`
- `evals/results/math-science-oracle-smoke-2026-05-19-benchmark-target/`

Status meanings:

- `pass`: executable oracle script ran and returned `pass: true`
- `answer_key_only`: fixed metadata answer key exists, but no executable script is expected
- `human_review_required`: checklist or expert review is the current oracle
- `pending`: known route decision is still needed, such as the formal-proof compiler route
- `fail`, `missing_answer_key`, `missing_executable`, or `missing_registry_entry`: blocking issue

### Output schema

```json
{
  "run_id": "...",
  "suite": "qa-critic",
  "overall": {
    "skill":               { "n": 10, "mean": 88.2, "std": 4.1, "min": 80.0, "max": 95.0 },
    "baseline-zero-shot":  { "n": 10, "mean": 61.5, "std": 6.2, "min": 52.0, "max": 73.0 }
  },
  "strata": {
    "easy":   { "skill": {...}, "baseline-zero-shot": {...} },
    "medium": { "skill": {...}, "baseline-zero-shot": {...} },
    "hard":   { "skill": {...}, "baseline-zero-shot": {...} }
  },
  "baseline_comparison": {
    "easy":   { "skill_minus_baseline-zero-shot": 24.5 },
    "medium": { "skill_minus_baseline-zero-shot": 28.1 },
    "hard":   { "skill_minus_baseline-zero-shot": 30.7 }
  },
  "fixtures": [ ... ]
}
```

---

## 6.0.3 Multi-Epoch Runs with SEM (`multi_epoch.py`)

Runs a fixture/condition pair N times and reports variance statistics.

### Tier defaults

| Tier | `runs_per_fixture` | When to use |
|---|---|---|
| `smoke` | 1 | Fast directional checks, PR validation |
| `standard` | 3 | Moderate confidence, 95% CI when n ≥ 3 |
| `benchmark` | 5 | Stronger directional claims, publication prep |

Set `runs_per_fixture` in `eval.yaml`:

```yaml
repetitions:
  runs_per_fixture: 3
```

### Statistics

When `runs_per_fixture >= 3`, the harness computes:

- **SEM** = `std / sqrt(n)`
- **95% CI** = `mean ± t(n-1, 0.975) × SEM`

The t-critical value uses the appropriate df from a lookup table (falls back to z = 1.960 for n ≥ 30).

### Standalone usage (post-hoc analysis)

```bash
python3 evals/harness/multi_epoch.py \
    --base-run-id design-smoke-2026-03-28-120000 \
    --suite qa-critic \
    --runs 3 \
    --save
```

### Programmatic usage

```python
from evals.harness.multi_epoch import aggregate_from_disk, save_epoch_summary, EpochRunner

aggregates = aggregate_from_disk(
    base_run_id="design-smoke-2026-03-28-120000",
    suite="qa-critic",
    fixture_ids=["clean-api-crud-suite", "signup-happy-path-gap"],
    conditions=["skill", "baseline-zero-shot"],
    n_epochs=3,
)
for agg in aggregates:
    print(agg.fixture_id, agg.condition, agg.mean_score, agg.sem, agg.ci_95_lower, agg.ci_95_upper)
```

### Output schema (epoch-summary.json)

```json
{
  "run_id": "design-smoke-2026-03-28-120000",
  "suite": "qa-critic",
  "runs_per_fixture": 3,
  "conditions": {
    "skill": {
      "n_fixtures": 10,
      "mean_of_means": 88.2,
      "fixtures": [
        {
          "fixture_id": "clean-api-crud-suite",
          "condition": "skill",
          "n_epochs": 3,
          "scores": [87.0, 89.5, 88.3],
          "mean_score": 88.27,
          "std": 1.257,
          "sem": 0.726,
          "ci_95_lower": 85.15,
          "ci_95_upper": 91.39,
          "ci_valid": true
        }
      ]
    }
  }
}
```

---

## 6.0.4 Invocation Abstraction (`invoke.py`)

Standardises how the harness invokes skills across three modes.

### Modes

| Mode | Stages | Skills |
|---|---|---|
| `critic` | 1: fixture → skill → output | All critic skills |
| `planner` | 1: fixture → skill → output | All planner skills |
| `executor` | 3: rollout → reproduction → grading | executor suites (dataviz-executor, etc.) |

The mode is resolved from `eval.yaml` → `invocation_mode` field (or derived from `skill.type`).
It can be overridden with `--mode` on the CLI.

### eval.yaml configuration

```yaml
# Option A: explicit field
invocation_mode: executor

# Option B: derive from skill type
skill:
  type: EXECUTOR
```

### Executor pipeline

Stage 1 (rollout): the planner agent receives the fixture and produces a spec.
Stage 2 (reproduction): the executor agent receives the spec and generates an artifact.
Stage 3 (grading): the critic agent reviews the artifact against the rubric.

Agent names default to `<suite-prefix>-planner`, `<suite>`, `<suite-prefix>-critic`.
Override with `--planner-agent`, `--executor-agent`, `--critic-agent`.

Stage 2 output is also written to the canonical single-stage path
(`raw/<suite>/<condition>/<fixture_id>.md`) so existing scorers can read it without changes.

### Standalone usage

```bash
# Single-stage (critic/planner)
python3 evals/harness/invoke.py \
    --run-id my-run-001 \
    --suite qa-critic \
    --fixture clean-api-crud-suite \
    --condition skill

# Executor pipeline
python3 evals/harness/invoke.py \
    --run-id my-run-001 \
    --suite dataviz-executor \
    --fixture simple-bar-chart \
    --condition skill \
    --mode executor
```

### Programmatic usage

```python
from evals.harness.invoke import invoke

result = invoke(
    run_id="my-run-001",
    suite="dataviz-executor",
    fixture_id="simple-bar-chart",
    condition="skill",
    # mode auto-detected from eval.yaml
)
print(result.ok)               # True / False
print(result.mode)             # "executor"
print(result.total_duration_sec)
for stage in result.stages:
    print(stage.stage, stage.ok, stage.duration_sec)
```

---

## Environment

All scripts that call the Anthropic API require:

```bash
export ANTHROPIC_API_KEY="<anthropic-api-key>"
```

The `run_design_smoke.py` runner invokes the `claude` CLI and does not use the SDK directly.
The `llm_judge.py`, `run_jtbd_simulation.py`, and optionally `invoke.py` use `import anthropic`.
