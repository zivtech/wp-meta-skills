# WordPress Evaluation and Certification Harness

This directory contains the WordPress-specific generation, certification,
runtime, and diagnostic tools shipped by `wp-meta-skills`. It is not a generic
cross-domain evaluation harness. The inventory below covers supported
operator-facing tools and selected internal helpers; it is deliberately not an
exhaustive list of every top-level module. Every executable named in the
inventory is checked as a tracked regular file by the public-documentation
validator.

## Shipped WordPress Tool Inventory

### Repair and certification

- `evals/harness/run_executor_repair_loop.py` — bounded generate, certify,
  repair, and re-certify orchestration for plugin, block, and Blueprint
  executors.
- `evals/harness/certify_wordpress_executor_artifact.py` — composed packet,
  materialization, artifact, and optional runtime certification.
- `evals/harness/materialize_wordpress_executor_packet.py` — converts an
  executor packet into an isolated artifact tree.
- `evals/harness/validate_wordpress_executor_packet.py` — validates executor
  packet contracts before materialization.
- `evals/harness/validate_wordpress_artifact.py` — deterministic generated-file
  and artifact-structure checks.
- `evals/harness/validate_wordpress_skill_output.py` — validates planner,
  executor, and critic output contracts, including optional security-gate
  consumption.

### Static and runtime gates

- `evals/harness/wp_api_lint.py` — PHPStan-backed WordPress API-existence and
  supported-version checks.
- `evals/harness/wp_security_gate.py` — WPCS security findings and suppression
  differential sidecar.
- `evals/harness/run_wordpress_runtime_smoke.py` — isolated provisioned WordPress
  runtime for WPCS, Plugin Check, activation, PHPUnit, and scoped browser/API
  assertions.
- `evals/harness/audit_wordpress_blueprint_launch_readiness.py` — checks a
  certified Blueprint and its payload references for launch blockers.
- `evals/harness/run_wordpress_blueprint_playground_smoke.js` — operator-run
  browser smoke for a launch-ready Blueprint.

### Candidate and evidence evaluation

- `evals/harness/invoke.py` — invokes one suite fixture and condition through a
  configured local model backend.
- `evals/harness/run_wordpress_candidate_pilot.py` — historical candidate
  discrimination pilot with archived raw outputs and a summary decision.
- `evals/harness/run_wordpress_high_risk_saved_outputs.py` — generates focused
  WordPress skill/baseline outputs and applies the deterministic output oracle.
- `evals/harness/score_wordpress_high_risk_answer_keys.py` — deterministic
  answer-key scoring for the focused high-risk suites.
- `evals/harness/run_pairwise_pilot.py` — bounded blind pairwise diagnostic.
- `evals/harness/pairwise_judge.py` — pairwise prompt, parsing, and decision
  support used by the pilot.
- `evals/harness/answer_key_score.py` — lexical answer-key diagnostic scorer.
- `evals/harness/score_with_claude_cli.py` — local Claude CLI rubric scoring for
  saved outputs.
- `evals/harness/compute_kappa.py` — agreement calculation for compatible
  recorded judgments.

### Optional owner-operated lanes

- `evals/harness/llm_judge.py` — Anthropic-SDK judging support. It requires an
  operator-provided environment and is not part of the locked ordinary
  validation bundle.
- `evals/harness/run_gepa_executor_optimization.py` — GEPA optimization support.
  It requires the optional GEPA environment and is not ordinary CI.

### Internal helpers, not public CLIs

- `evals/harness/provider_preflight.py` — metadata-only Ollama/Gemini identity
  check used by generation paths.
- `evals/harness/workspace_lease.py` — exclusive workspace lease and owner
  diagnostics for runtime work.
- `evals/harness/runtime_artifact_pipeline.py` — staged artifact execution and
  evidence plumbing.
- `evals/harness/wp_runtime_oracles.py` — shared runtime result/oracle helpers.
- `evals/harness/wp_plugin_check_runtime.py` — Plugin Check runtime integration.
- `evals/harness/bounded_subprocess.py` — causal subprocess timeout and process
  cleanup.
- `evals/harness/sandboxed_package_runner.py` — isolated package acquisition and
  command execution used by the Docker boundary.

These helper modules may expose diagnostic entry points for tests or operators;
their listing does not make them stable public command-line interfaces.

## Repair-loop Contract

The repair loop is a workflow, not evidence that every model or artifact will
converge. It requires a suite fixture, a run ID, an executor/profile selection,
and an exact model where the selected provider needs one:

```bash
python3 evals/harness/run_executor_repair_loop.py \
  --suite wordpress-plugin-executor \
  --fixture abilities-ai-surface-v1 \
  --provider gemini \
  --model "$GEMINI_MODEL" \
  --profile static \
  --max-repairs 3 \
  --run-id example-static
```

The initial generation is iteration zero. A failed or empty generation may be
retried under `--gen-retries`; it never erases the last good packet. A repair
attempt receives bounded deterministic failure feedback. The loop stops when
certification passes, generation cannot produce a usable packet, the profile is
unsupported, or the repair budget is exhausted.

The executor/profile matrix fails closed:

| Executor | Static | Runtime |
|---|---|---|
| Plugin | Supported | Isolated `standard` profile |
| Block | Supported | Only with fixture-owned block, selector, and text assertions |
| Blueprint | Supported | Rejected |

No tracked block repair fixture currently carries the required runtime
assertions. Direct runtime-harness flags are operator inputs; only the fixture
loader proves that repair-loop assertions came from a canonical suite fixture.
Blueprint launch audit and browser smoke are separate tools, not a runtime
fallback for the repair loop.

## Certification Contract

The composed certifier validates the packet, materializes it into a new or
explicitly replaceable output directory, runs deterministic artifact checks,
and can require named external tools:

```bash
python3 evals/harness/certify_wordpress_executor_artifact.py \
  --executor plugin \
  --packet /path/to/packet.md \
  --out-dir /path/to/artifact \
  --result-dir /path/to/result \
  --profile static \
  --overwrite
```

Static certification does not imply activation, browser behavior, database
behavior, third-party integration, performance, or production safety. Runtime
certification proves only the exact provisioned gates and assertions recorded
for that run.

The API linter and security gate are deterministic sidecars. The API linter
checks configured WordPress symbol/version constraints; it does not prove that
an integration behaves correctly. The security gate detects configured WPCS
security findings and suppression abuse; contextual authorization,
reachability, exploitability, dependency CVEs, and deployment controls still
require review.

## Provider Preflight Boundary

Ollama and Gemini generation require an exact operator-selected model. The
preflight verifies that exact identity before invoking the model and writes a
sanitized receipt. There is no repository default model.

For Gemini, credentials travel in a header file descriptor. They must not be
placed in the URL, process arguments, saved receipt, error message, or test
artifact. Metadata success proves that the model resource matched and
advertised `generateContent` at observation time. It does not prove a content
request, quota, billing authorization, model quality, or future availability.

The `live_provider` test marker is separately authorized and excluded from
ordinary CI. Repository tests use controlled fakes for provider failure,
identity, and redaction behavior.

## Candidate and Saved-Output Diagnostics

`run_wordpress_candidate_pilot.py` is retained to reproduce the historical
directional pilot mechanics. It archives raw outputs, score data, metadata, and
a summary decision. Its own contract explicitly does not establish
benchmark-grade superiority.

`run_wordpress_high_risk_saved_outputs.py` is narrower. It writes raw outputs,
deterministic contract results, a manifest, and a scorecard for selected
WordPress suites and conditions. It does not judge semantic quality. The
answer-key and pairwise tools are diagnostics that require their own reviewed
interpretation and cannot upgrade a contract pass into a production or
benchmark claim.

## Result and Evidence Shape

Tools write only beneath explicit run/result directories or the repository's
ignored local result area. Depending on the tool, a run may contain:

- raw generated or saved output;
- per-output deterministic contract JSON;
- materialized artifacts and `certification.json`;
- runtime-smoke JSON with named gate results;
- sanitized provider-preflight metadata;
- a run manifest or aggregate summary;
- a Markdown scorecard describing scope and non-claims.

Paths inside committed public evidence are canonical public artifacts. Local
ignored results are not public proof merely because a matching run ID exists.
Moving a result into `evidence/` requires explicit review of content, claim
scope, secrets, local paths, licenses, and provenance.

## Validation

The harness is covered by the repository's locked test and policy sequence:

```bash
uv lock --check
uv sync --locked --extra test
uv run --locked --extra test python scripts/validate-eval-suite-integrity.py \
  --strict-suites wordpress-plugin-executor \
  --strict-suites wordpress-block-executor \
  --strict-suites wordpress-security-critic \
  --strict-suites wordpress-performance-critic \
  --strict-suites wordpress-planner.migration \
  --strict-suites wordpress-blueprint-executor \
  --strict-suites wordpress-skill-candidate-eval \
  --allow-known-gaps
uv run --locked --extra test python -m pytest \
  -m "not docker_boundary and not live_provider" evals/harness/tests -q
```

The Linux Docker sandbox and generated-runtime markers run in separate
no-secrets jobs because they have different isolation, timing, disk, and
cleanup contracts. See the root [CONTRIBUTING.md](../../CONTRIBUTING.md) and
workflow for those exact gates.

## Negative Space

This harness does not by itself prove:

- that a prompt persona outperforms a strong baseline;
- that a repair loop will converge for an arbitrary model or fixture;
- production correctness, capacity, accessibility, or security;
- behavior of credentials or providers not exercised by an authorized run;
- compatibility with every WordPress/PHP/Node/browser combination;
- integrity or provenance of untracked local results;
- independent review of a diagnostic score or saved output.
