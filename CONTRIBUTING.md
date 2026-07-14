# Contributing

`wp-meta-skills` is a prompt-only WordPress skill package. Contributions should
improve the skill contracts, WordPress API specificity, validation harnesses, or
evidence quality.

## Working Rules

- Keep generated examples free of secrets, credentials, private URLs, and real
  client data.
- Name exact WordPress APIs, hooks, files, packages, commands, or verification
  surfaces when a claim depends on them.
- Preserve negative space: say what a proof does not cover.
- Prefer deterministic contracts and runtime oracles over generic review-quality
  claims.
- Do not copy or closely adapt upstream prompt text unless the source license,
  attribution, and reuse ledger entry are resolved first.

## Validation

Most contributions can be validated directly in this repository. If you edit
any tracked file, regenerate the checksum manifest first:

```bash
./install.sh --generate-manifest
```

(`scripts/build-wp-meta-skills-package.py` lives in the private
`zivtech-meta-skills` source monorepo, not in this repository; it only matters
for maintainers regenerating the whole package. See `PROVENANCE.md`.)

Then run the validation bundle:

```bash
./install.sh --verify
python3 scripts/validate-agent-frontmatter.py
python3 scripts/validate-wordpress-exact-api-contract.py
python3 scripts/validate-eval-suite-integrity.py \
  --strict-suites wordpress-plugin-executor \
  --strict-suites wordpress-block-executor \
  --strict-suites wordpress-security-critic \
  --strict-suites wordpress-performance-critic \
  --strict-suites wordpress-planner.migration \
  --strict-suites wordpress-blueprint-executor \
  --strict-suites wordpress-skill-candidate-eval \
  --allow-known-gaps
python3 -m pytest \
  evals/harness/tests/test_invoke_claude_command.py \
  evals/harness/tests/test_workspace_lease.py \
  evals/harness/tests/test_runtime_image_provision.py \
  evals/harness/tests/test_wp_env_network_guard.py \
  evals/harness/tests/test_isolated_runtime_contract.py \
  evals/harness/tests/test_wp_staged_runtime.py \
  evals/harness/tests/test_executor_repair_loop.py \
  evals/harness/tests/test_artifact_layout.py \
  evals/harness/tests/test_artifact_execution_graph.py \
  evals/harness/tests/test_artifact_execution_gate.py \
  evals/harness/tests/test_artifact_explicit_scanners.py \
  evals/harness/tests/test_artifact_traversal.py \
  evals/harness/tests/test_runtime_artifact_pipeline.py \
  evals/harness/tests/test_isolated_block_artifact_contract.py \
  evals/harness/tests/test_wordpress_runtime_artifact_gate.py \
  evals/harness/tests/test_wordpress_runtime_smoke.py \
  evals/harness/tests/test_wordpress_artifact_oracle.py \
  evals/harness/tests/test_wordpress_blueprint_launch_readiness.py \
  evals/harness/tests/test_wordpress_executor_packet_oracle.py \
  evals/harness/tests/test_wordpress_exact_api_contract.py \
  evals/harness/tests/test_wordpress_executor_artifact_certifier.py \
  evals/harness/tests/test_wordpress_packet_materializer.py \
  evals/harness/tests/test_wordpress_high_risk_answer_keys.py \
  evals/harness/tests/test_wordpress_high_risk_saved_outputs.py \
  evals/harness/tests/test_wordpress_skill_output_contract.py \
  evals/harness/tests/test_answer_key_score.py \
  evals/harness/tests/test_pairwise_pilot.py \
  evals/harness/tests/test_wordpress_candidate_pilot_generation.py \
  evals/harness/tests/test_wp_api_lint.py \
  evals/harness/tests/test_wp_security_gate.py \
  -m 'not docker_boundary' -q
```

## Reuse And Provenance

Reference-only upstream comparison is allowed. Direct copied or closely adapted
prompt text requires a source URL, commit or access date, license, local file,
adapted section, and rationale in the reuse ledger before it lands.

When in doubt, keep the production skill text clean-room and cite the upstream
project as a comparator rather than importing its wording.
## Sandbox inventory updates

Plan 009 runtime inputs are reviewed in `evals/harness/container-images.json`.
An update must record the immutable OCI index digest, linux/amd64 and
linux/arm64 child manifests, source tag, verification date, purpose, and
license. Update the repository runner lock with scripts disabled, verify its
registry integrity, run the hermetic provisioning/materialization tests, and
run the separate no-secrets GitHub-hosted Linux Docker feasibility job against
the exact commit. Mutable tags, unreviewed helper images, local Docker Desktop
results, and generated lock synthesis are not acceptable substitutes. The
legacy canary slice requires at least 20 GiB free, permits at most a
conservative 12 GiB post-run delta (leaving an 8 GiB reserve), and has a causal
30-minute process timeout. The aggregate no-secrets job has a 60-minute envelope
because the package-acquisition boundary runs before that slice. A budget
failure blocks the checkpoint.

The generated-code runtime uses the same inventory but has a separate required
Linux gate:

```bash
python3 -m pytest \
  evals/harness/tests/test_wp_staged_runtime.py \
  -m docker_boundary -q
```

That gate never receives Actions secrets. It builds from the recorded platform
digests and committed build-input hashes, then proves generated PHP and browser
JavaScript inside the repository-owned isolated topology. Do not substitute a
host `wp-env`, host browser, Docker Desktop result, mutable image tag, or cached
local image for this gate.

The generated runtime runs in its own required job. Its process has a causal
30-minute timeout inside a 35-minute job envelope reserved for cleanup. The job
requires 20 GiB free before any runtime pull/build and permits at most a 12 GiB
disk delta after its exact run-owned containers, networks, and image tags are
removed. The post-cleanup measurement includes residual image layers and build
cache; exceeding it fails the job.

The acquisition proxy allowlist is limited to the reviewed npm and Composer
registry endpoints represented by the committed locks. The final generated-code
runtime has no public acquisition route: the browser can reach only the exact
WordPress gateway origin, WordPress and CLI can reach only the database peer,
and the database has no application-facing peer beyond that backend network.
Each final bridge is both `internal` and configured with Docker's IPv4 gateway
mode `isolated`; live inspection requires no host bridge address and each
generated-code container must have no default route. The generated runtime
therefore requires Docker Engine 28 or newer and blocks before provisioning on
older or unparseable daemon versions.
Widening either allowlist is a security change requiring inventory review,
hostile-route canaries, both test profiles, and a new hosted Linux proof.
