# wordpress-plugin-executor Smoke Eval

Smoke-tier evaluation scaffold for `wordpress-plugin-executor`. This suite provides two fixtures, matching rubrics, and fair baselines so the skill has initial eval evidence without claiming full benchmark readiness:

- `smoke-wordpress-v1`: minimal plugin lifecycle, settings, and verification-packet materializability.
- `abilities-ai-surface-v1`: Abilities API registration, guarded AI Client helper, Connectors boundary, and MCP Adapter discovery/execution as verification surfaces.

Baseline generation defaults to the isolated local Codex CLI lane in `eval.yaml`: `baseline_provider: codex`, `baseline_model_policy: newest-chatgpt-level-at-run-time`, currently resolved as `gpt-5.5`. Skill-agent generation remains a Claude-agent surface until a Codex skill-dispatch path exists; do not treat historical Sonnet skill runs as the current baseline default.

Output contract oracle:

```bash
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-plugin-executor \
  --output <candidate-output.md>
```

Deterministic packet oracle:

```bash
python3 evals/harness/validate_wordpress_executor_packet.py \
  --executor plugin \
  --packet <candidate-output.md>
```

Packet materializer:

```bash
python3 evals/harness/materialize_wordpress_executor_packet.py \
  --executor plugin \
  --packet <candidate-output.md> \
  --out-dir <generated-plugin-dir>
```

Combined certification gate:

```bash
python3 evals/harness/certify_wordpress_executor_artifact.py \
  --executor plugin \
  --packet <candidate-output.md> \
  --out-dir <generated-plugin-dir> \
  --result-dir <result-dir> \
  --overwrite
```

Generated artifact oracle:

```bash
python3 evals/harness/validate_wordpress_artifact.py \
  --artifact-type plugin \
  --path <generated-plugin-dir>
```

Runtime proof requires explicit tooling, for example:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path <generated-plugin-dir>/<plugin-slug> \
  --phpunit-smoke \
  --provision-full-profile \
  --write \
  --run-id generated-plugin-phpunit-full-profile-YYYYMMDD \
  --timeout-sec 300
```

The test-bearing example packet is `examples/phpunit-wordpress-v1.materializable-packet.md`. Its first local full-profile proof is recorded at `evals/results/wordpress-skill-candidate-eval/generated-plugin-phpunit-full-profile-20260620/`, after packet certification into `evals/results/wordpress-skill-candidate-eval/generated-plugin-phpunit-artifact-cert-20260620/generated-plugin`.

MCP Adapter runtime proof uses `examples/mcp-adapter-wordpress-v1.materializable-packet.md`:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path <generated-plugin-dir>/<plugin-slug> \
  --ability-name acme-mcp-smoke/get-runtime-marker \
  --mcp-adapter-smoke \
  --mcp-adapter-execute-args-json '{"marker":"Runtime MCP smoke"}' \
  --mcp-adapter-expected-output "Runtime MCP smoke" \
  --provision-full-profile \
  --write \
  --run-id generated-mcp-adapter-full-profile-YYYYMMDD \
  --timeout-sec 300
```

The first local proof is recorded at `evals/results/wordpress-skill-candidate-eval/generated-mcp-adapter-full-profile-20260621/`, after packet certification into `evals/results/wordpress-skill-candidate-eval/generated-mcp-adapter-artifact-cert-20260621/generated-plugin`. It proves adapter installation, STDIO tool discovery, public ability discovery/execution, WPCS/PHPCS, and Plugin Check for one generated public ability. It does not prove AI Client provider-call behavior, browser/editor behavior, broad integration coverage, or release readiness.

AI Client provider-call runtime proof uses `examples/ai-client-provider-wordpress-v1.materializable-packet.md`:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --workdir /tmp/wp-ai-client-runtime-smoke-YYYYMMDD \
  --artifact-path <generated-plugin-dir>/<plugin-slug> \
  --ai-client-smoke \
  --ai-client-provider-id acme-ai-client-smoke \
  --ai-client-model-id acme-deterministic-text \
  --ai-client-helper-function 'AcmeAIClientSmoke\generate_summary' \
  --ai-client-prompt "Runtime AI Client smoke" \
  --ai-client-expected-output "AI Client smoke: deterministic provider response" \
  --provision-full-profile \
  --write \
  --run-id generated-ai-client-provider-full-profile-YYYYMMDD \
  --timeout-sec 300
```

The first local proof is recorded at `evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-full-profile-20260621/`, after packet certification into `evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-artifact-cert-20260621/generated-plugin`. It proves deterministic no-auth AI Client provider registration/configuration, connector registration, model preference selection, generated text output, WPCS/PHPCS, and Plugin Check for one generated provider fixture. It does not prove credentialed external-provider behavior, browser/editor behavior, broad integration coverage, or release readiness.
