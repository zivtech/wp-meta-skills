# Evidence Manifest

> **Redaction note (2026-07-02):** bundled evidence files were redacted before
> public release to remove local absolute home-directory paths and one
> unrelated local plugin name that leaked into Codex stderr logs. Redactions
> replaced path strings only (`/Users/<user>/...` → `/Users/redacted/...`,
> monorepo clone path → `/path/to/zivtech-meta-skills`); no scores, verdicts,
> gate results, or model output content were changed.

This package is supported by deterministic contracts, artifact gates, local
runtime proofs, and selected high-risk saved-output evidence. Selected
scorecards and runtime JSON files are bundled under
`evidence/wordpress-skill-candidate-eval/`; selected high-risk eval outputs and
contract results are bundled under `evidence/wordpress-high-risk-evals/`. The
full result archives are not bundled in the standalone package. They are
explicitly out of scope for the first public release unless a later release
adds public artifact URLs.

## Current Proof Surfaces

| Claim area | Source evidence | Proven | Not proven |
|---|---|---|---|
| Package extraction | `wordpress-skills/docs/standalone-extraction-readiness-2026-06-21.md`; current clean-root public import | WordPress skills, docs, suites, metadata, CI workflow, and a pruned validation harness can be extracted, clean-imported, and validated in a standalone repo. | Release tag, public artifact URLs, or broad benchmark maturity. |
| Static contracts | `scripts/validate-wordpress-exact-api-contract.py`; `evals/harness/validate_wordpress_skill_output.py`; `evals/harness/validate_wordpress_executor_packet.py`; `evals/harness/validate_wordpress_artifact.py` | Exact WordPress API/surface contracts, output-shape contracts, packet contracts, and static generated-artifact gates exist and pass in the current validation bundle. | Human quality superiority, broad code correctness, or production deployment readiness. |
| Plugin PHPUnit runtime | `evals/results/wordpress-skill-candidate-eval/generated-plugin-phpunit-full-profile-20260620/scorecard.md` | Generated plugin activation in WordPress `7.0`, artifact-local PHPUnit, WPCS/PHPCS, Plugin Check, and full profile pass. | Block/editor/browser behavior, MCP Adapter behavior, AI Client provider behavior. |
| Block build/editor/frontend runtime | `evals/results/wordpress-skill-candidate-eval/generated-block-full-profile-20260620/scorecard.md` | Generated block build, wrapper-based `wp-env` registration, WPCS/PHPCS, Plugin Check, editor insertion, save/publish, and frontend output. | PHPUnit, Abilities API, block deprecation, Interactivity API, MCP Adapter, AI Client. |
| Block Interactivity API runtime | `evals/results/wordpress-skill-candidate-eval/generated-block-interactivity-full-profile-20260621/scorecard.md` | Built `viewScriptModule`, static Interactivity surfaces, editor insertion, frontend render, and click/state assertion. | PHPUnit, block deprecation, MCP Adapter, AI Client. |
| Block deprecation runtime | `evals/results/wordpress-skill-candidate-eval/generated-block-deprecation-full-profile-20260621/scorecard.md` | One legacy serialized fixture migrated through WordPress deprecation handling into current saved markup and frontend output. | Broad migration compatibility across many deprecated versions. |
| MCP Adapter runtime | `evals/results/wordpress-skill-candidate-eval/generated-mcp-adapter-full-profile-20260621/scorecard.md` | MCP Adapter installation, STDIO tool discovery, generated ability discovery, generated ability execution, WPCS/PHPCS, and Plugin Check. | Browser/editor behavior, PHPUnit, AI Client provider-call behavior; upstream adapter deprecation notices remain adapter/runtime risk. |
| AI Client provider-call runtime | `evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-full-profile-20260621/scorecard.md` | Deterministic no-auth provider registration/configuration, connector registration, `wp_ai_client_prompt()`, model preference selection, generated output, WPCS/PHPCS, and Plugin Check. | Credentialed OpenAI, Anthropic, Google, or other external provider behavior. |
| Security critic saved-output contract | `evals/results/wordpress-security-critic-saved-outputs-20260621/scorecard.md` | Saved outputs and contract-oracle results exist for `wordpress-security-critic` skill, zero-shot baseline, and few-shot baseline across the original smoke fixture plus three focused fixtures. All three focused skill outputs passed the deterministic output contract. | Independent QA/test-critic review, human benchmark interpretation, production exploitability, supply-chain/CVE coverage, and accepted baseline quality comparison. Baseline lanes did not pass the strict skill-output contract. |
| Performance critic saved-output contract | `evals/results/wordpress-performance-critic-saved-outputs-20260621/scorecard.md` | Saved outputs and contract-oracle results exist for `wordpress-performance-critic` skill, zero-shot baseline, and few-shot baseline across the original smoke fixture plus three focused fixtures. All three focused skill outputs and the legacy smoke skill output passed the deterministic output contract. | Independent QA/test-critic review, human benchmark interpretation, production latency/capacity, Core Web Vitals failure, cache effectiveness, and accepted baseline quality comparison. Baseline lanes did not pass the strict skill-output contract. |
| Performance query/cache regenerated output | `evals/results/wordpress-performance-critic-query-cache-regenerated-20260621/scorecard.md`; `evals/results/wordpress-performance-critic-query-cache-regenerated-answer-key-20260621/scorecard.md` | After the performance prompt-boundary repair, the single regenerated `query-cache-pressure-v1` skill output passed the output contract 1/1 and scored recall 1.000, API coverage 0.700, specificity 1.000, and composite 0.900 under deterministic answer-key coverage. | Full focused-suite behavior by itself, independent QA/test-critic review, long-run variance reduction, and any accepted benchmark-superiority claim. |
| Performance critic regenerated focused outputs | `evals/results/wordpress-performance-critic-regenerated-focused-20260621/scorecard.md`; `evals/results/wordpress-performance-critic-regenerated-focused-answer-key-20260621/scorecard.md` | Full focused post-repair regeneration passed generation 9/9 across `skill`, `baseline-zero-shot`, and `baseline-few-shot`. Focused skill outputs passed the output contract 3/3; baseline lanes remained 0/6 on the strict skill-output contract. Deterministic answer-key composites were skill 0.915, baseline-zero-shot 0.845, and baseline-few-shot 0.862. | Independent QA/test-critic review, accepted benchmark interpretation, long-run variance reduction, production latency/capacity, and any public benchmark-superiority claim. |
| Migration planner saved-output contract | `evals/results/wordpress-planner-migration-saved-outputs-20260621/scorecard.md` | Saved outputs and contract-oracle results exist for `wordpress-planner.migration` skill, zero-shot baseline, and few-shot baseline across the original smoke fixture plus three focused fixtures. All three focused skill outputs and the legacy smoke skill output passed the deterministic output contract. | Independent QA/test-critic review, human benchmark interpretation, real migration readiness, source-data fitness, launch readiness, and accepted baseline quality comparison. Baseline lanes did not pass the strict skill-output contract. |
| High-risk deterministic answer-key coverage | `evals/results/wordpress-high-risk-answer-key-20260621/scorecard.md`; `evals/results/wordpress-high-risk-answer-key-20260621/qa-review.md`; `evals/results/wordpress-high-risk-answer-key-20260621/performance-query-cache-recall-review.md`; `evals/results/wordpress-high-risk-answer-key-20260621/performance-query-cache-semantic-annotation.md` | Deterministic lexical answer-key coverage exists for the focused security, performance, and migration saved outputs. Focused skill composites: security `0.936`, performance `0.844`, migration `0.954`. Main-agent QA review accepts the run with reservations for internal diagnostic and evidence-boundary use. Performance tied `baseline-zero-shot` on composite and did not show a clean lexical edge. Query-cache follow-up found one semantic scorer miss and one real archived-output gap; scoped semantic annotation records the archived skill response as semantically `3/4` on must-detect items for `query-cache-pressure-v1`. The prompt was amended without changing archived scores. | Semantic LLM judging, independent QA/test-critic review, variance measurement, runtime proof, benchmark superiority, or accepted human interpretation of baseline quality. |
| Blueprint executor static certification | `evals/results/wordpress-blueprint-executor-static-cert-20260621/scorecard.md` | Focused saved Blueprint executor packets exist for minimal plugin environment, block/theme reproduction, and unsupported-feature boundary fixtures. All three passed packet contract, materialization, and static `blueprint.json` artifact certification. | Recorded Playground launch behavior, frontend/editor behavior, plugin/theme activation, external-service behavior, answer-key scoring, QA/test-critic review, human benchmark interpretation, and baseline quality comparison. |
| Blueprint launch-readiness preflight | `evals/results/wordpress-blueprint-executor-launch-preflight-20260621/scorecard.md` | Preflight checks the certified generated Blueprints for launch blockers and records exact missing VFS plugin/theme ZIP payloads. Current status is `blocked`: the committed evidence bundle lacks `acme-notice-board.zip`, `acme-block-theme.zip`, `acme-events-block.zip`, and `acme-crm-sync.zip`. | Browser launch, plugin/theme activation, frontend/editor behavior, external-service behavior, or runtime success in WordPress Playground. |
| Blueprint self-contained Playground smoke | `evals/results/wordpress-blueprint-executor-self-contained-static-cert-20260621/scorecard.md`; `evals/results/wordpress-blueprint-executor-self-contained-launch-preflight-20260621/scorecard.md`; `evals/results/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/scorecard.md`; `evals/results/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/qa-review.md` | A self-contained Blueprint writes and activates a disposable plugin without VFS ZIP payloads, passes static certification, produces a launchable Playground fragment, and passes one browser-observed Playground smoke with visible text `Inline Blueprint Smoke Ready`. Main-agent QA review accepts this as narrow internal runtime evidence with reservations. | VFS-backed packet launch behavior, frontend/editor behavior beyond this admin-page smoke, external-service behavior, independent QA/test-critic review, public release approval, benchmark interpretation, or baseline quality comparison. |

## Bundled Evidence Files

The standalone package includes:

- `evidence/wordpress-skill-candidate-eval/generated-plugin-phpunit-full-profile-20260620/scorecard.md`
- `evidence/wordpress-skill-candidate-eval/generated-plugin-phpunit-full-profile-20260620/runtime-smoke.json`
- `evidence/wordpress-skill-candidate-eval/generated-block-full-profile-20260620/scorecard.md`
- `evidence/wordpress-skill-candidate-eval/generated-block-full-profile-20260620/runtime-smoke.json`
- `evidence/wordpress-skill-candidate-eval/generated-block-interactivity-full-profile-20260621/scorecard.md`
- `evidence/wordpress-skill-candidate-eval/generated-block-interactivity-full-profile-20260621/runtime-smoke.json`
- `evidence/wordpress-skill-candidate-eval/generated-block-deprecation-full-profile-20260621/scorecard.md`
- `evidence/wordpress-skill-candidate-eval/generated-block-deprecation-full-profile-20260621/runtime-smoke.json`
- `evidence/wordpress-skill-candidate-eval/generated-mcp-adapter-full-profile-20260621/scorecard.md`
- `evidence/wordpress-skill-candidate-eval/generated-mcp-adapter-full-profile-20260621/runtime-smoke.json`
- `evidence/wordpress-skill-candidate-eval/generated-ai-client-provider-full-profile-20260621/scorecard.md`
- `evidence/wordpress-skill-candidate-eval/generated-ai-client-provider-full-profile-20260621/runtime-smoke.json`
- `evidence/wordpress-high-risk-evals/wordpress-security-critic-saved-outputs-20260621/scorecard.md`
- `evidence/wordpress-high-risk-evals/wordpress-security-critic-saved-outputs-20260621/contract-summary.json`
- `evidence/wordpress-high-risk-evals/wordpress-security-critic-saved-outputs-20260621/contracts/`
- `evidence/wordpress-high-risk-evals/wordpress-security-critic-saved-outputs-20260621/raw/`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-saved-outputs-20260621/scorecard.md`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-saved-outputs-20260621/contract-summary.json`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-saved-outputs-20260621/contracts/`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-saved-outputs-20260621/raw/`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-query-cache-regenerated-20260621/scorecard.md`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-query-cache-regenerated-20260621/contract-summary.json`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-query-cache-regenerated-20260621/contracts/`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-query-cache-regenerated-20260621/raw/`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-query-cache-regenerated-answer-key-20260621/scorecard.md`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-query-cache-regenerated-answer-key-20260621/answer-key-summary.json`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-regenerated-focused-20260621/scorecard.md`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-regenerated-focused-20260621/contract-summary.json`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-regenerated-focused-20260621/contracts/`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-regenerated-focused-20260621/raw/`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-regenerated-focused-answer-key-20260621/scorecard.md`
- `evidence/wordpress-high-risk-evals/wordpress-performance-critic-regenerated-focused-answer-key-20260621/answer-key-summary.json`
- `evidence/wordpress-high-risk-evals/wordpress-planner-migration-saved-outputs-20260621/scorecard.md`
- `evidence/wordpress-high-risk-evals/wordpress-planner-migration-saved-outputs-20260621/contract-summary.json`
- `evidence/wordpress-high-risk-evals/wordpress-planner-migration-saved-outputs-20260621/contracts/`
- `evidence/wordpress-high-risk-evals/wordpress-planner-migration-saved-outputs-20260621/raw/`
- `evidence/wordpress-high-risk-evals/wordpress-high-risk-answer-key-20260621/scorecard.md`
- `evidence/wordpress-high-risk-evals/wordpress-high-risk-answer-key-20260621/answer-key-summary.json`
- `evidence/wordpress-high-risk-evals/wordpress-high-risk-answer-key-20260621/qa-review.md`
- `evidence/wordpress-high-risk-evals/wordpress-high-risk-answer-key-20260621/performance-query-cache-recall-review.md`
- `evidence/wordpress-high-risk-evals/wordpress-high-risk-answer-key-20260621/performance-query-cache-semantic-annotation.md`
- `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-static-cert-20260621/scorecard.md`
- `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-static-cert-20260621/certification-summary.json`
- `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-static-cert-20260621/*/certification.json`
- `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-static-cert-20260621/*/generated-blueprint/blueprint.json`
- `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-launch-preflight-20260621/scorecard.md`
- `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-launch-preflight-20260621/launch-preflight-summary.json`
- `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-self-contained-static-cert-20260621/scorecard.md`
- `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-self-contained-static-cert-20260621/certification-summary.json`
- `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-self-contained-static-cert-20260621/*/certification.json`
- `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-self-contained-static-cert-20260621/*/generated-blueprint/blueprint.json`
- `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-self-contained-launch-preflight-20260621/scorecard.md`
- `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-self-contained-launch-preflight-20260621/launch-preflight-summary.json`
- `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/scorecard.md`
- `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/playground-smoke.json`
- `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/qa-review.md`

## Validation Bundle

Run inside a generated standalone package:

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
  -q
```

Recorded package proof at extraction checkpoint:

- Package: local scratch path omitted from public docs
- Manifest verification: pass
- Agent frontmatter validation: pass
- WordPress Exact API contract validation: pass
- Strict selected WordPress suite validation: pass
- WordPress harness tests: 148 passed

Current validation also includes the API-existence lint and security-gate test
files in the public workflow.

## Evidence Boundaries

This evidence does not claim:

- superiority over a frontier model or a strong few-shot baseline;
- lower long-run output variance across repeated generations;
- production readiness for generated plugins, blocks, or themes;
- credentialed third-party AI-provider behavior;
- independently QA-reviewed high-risk benchmark maturity or accepted semantic
  benchmark interpretation;
- release tagging, broad benchmark maturity, or public artifact URLs for full
  result archives.
