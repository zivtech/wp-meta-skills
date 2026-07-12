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
  -q
```

## Reuse And Provenance

Reference-only upstream comparison is allowed. Direct copied or closely adapted
prompt text requires a source URL, commit or access date, license, local file,
adapted section, and rationale in the reuse ledger before it lands.

When in doubt, keep the production skill text clean-room and cite the upstream
project as a comparator rather than importing its wording.
