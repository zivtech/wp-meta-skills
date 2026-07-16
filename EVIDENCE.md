# Evidence Manifest

> **Packaging record (2026-07-02):** maintainers recorded that selected public
> evidence was sanitized to remove local absolute paths and one unrelated local
> plugin name before the clean public import. The original private inputs and a
> deterministic before/after transform are not included here, so this
> standalone repository cannot independently prove that only those strings
> changed. The committed files below are the canonical public proof surfaces.

This repository bundles selected deterministic contracts, artifact-gate
records, runtime-smoke records, and saved-output diagnostics. The evidence is
narrow and historical. Full result archives and original private packaging
inputs are not bundled.

## Current Proof Surfaces

| Claim area | Source evidence | Proven | Not proven |
|---|---|---|---|
| Standalone extraction | `docs/wordpress/standalone-extraction-readiness-2026-06-21.md` | The named WordPress skills, documents, suites, metadata, workflow, and pruned harness were extracted and checked at the recorded checkpoint. | A release tag, complete source-history preservation, or broad benchmark maturity. |
| Static contracts | `scripts/validate-wordpress-exact-api-contract.py`; `evals/harness/validate_wordpress_skill_output.py`; `evals/harness/validate_wordpress_executor_packet.py`; `evals/harness/validate_wordpress_artifact.py` | The current tree contains deterministic exact-API, output, packet, and static-artifact checks. | Human quality superiority, broad code correctness, or deployment readiness. |
| Plugin PHPUnit runtime | `evidence/wordpress-skill-candidate-eval/generated-plugin-phpunit-full-profile-20260620/scorecard.md` | The recorded fixture passed WordPress 7.0 activation, artifact-local PHPUnit, WPCS/PHPCS, Plugin Check, and its full profile. | Block/editor behavior, MCP Adapter behavior, or credentialed AI-provider behavior. |
| Block build, editor, and frontend runtime | `evidence/wordpress-skill-candidate-eval/generated-block-full-profile-20260620/scorecard.md` | The recorded fixture passed build, registration, WPCS/PHPCS, Plugin Check, editor insertion, save/publish, and scoped frontend output. | PHPUnit, Abilities API, deprecation, Interactivity API, MCP Adapter, or AI Client behavior. |
| Block Interactivity API runtime | `evidence/wordpress-skill-candidate-eval/generated-block-interactivity-full-profile-20260621/scorecard.md` | The recorded fixture exercised built `viewScriptModule`, static Interactivity surfaces, editor insertion, frontend render, and one click/state assertion. | PHPUnit, deprecation, MCP Adapter, or AI Client behavior. |
| Block deprecation runtime | `evidence/wordpress-skill-candidate-eval/generated-block-deprecation-full-profile-20260621/scorecard.md` | One recorded legacy serialization migrated through WordPress deprecation handling to current saved markup and frontend output. | Compatibility across multiple historical versions or arbitrary content. |
| MCP Adapter runtime | `evidence/wordpress-skill-candidate-eval/generated-mcp-adapter-full-profile-20260621/scorecard.md` | The recorded fixture exercised adapter installation, STDIO tool discovery, generated ability discovery/execution, WPCS/PHPCS, and Plugin Check. | Browser/editor behavior, PHPUnit, or AI Client provider calls. |
| AI Client no-auth provider runtime | `evidence/wordpress-skill-candidate-eval/generated-ai-client-provider-full-profile-20260621/scorecard.md` | The recorded fixture exercised deterministic no-auth provider and connector registration, prompt invocation, preference selection, generated output, WPCS/PHPCS, and Plugin Check. | Credentialed OpenAI, Anthropic, Google, or other external-provider behavior. |
| Security critic saved-output contract | `evidence/wordpress-high-risk-evals/wordpress-security-critic-saved-outputs-20260621/scorecard.md` | The recorded focused skill outputs passed the deterministic output contract. | Exploitability, supply-chain/CVE coverage, production security, or accepted baseline superiority. |
| Performance critic saved-output contract | `evidence/wordpress-high-risk-evals/wordpress-performance-critic-saved-outputs-20260621/scorecard.md` | The recorded focused skill outputs and legacy smoke skill output passed the deterministic output contract. | Production latency, capacity, Core Web Vitals, cache effectiveness, or accepted baseline superiority. |
| Performance query/cache regeneration | `evidence/wordpress-high-risk-evals/wordpress-performance-critic-query-cache-regenerated-20260621/scorecard.md`; `evidence/wordpress-high-risk-evals/wordpress-performance-critic-query-cache-regenerated-answer-key-20260621/scorecard.md` | One recorded regenerated skill output passed its output contract and received the recorded deterministic answer-key scores. | Full-suite behavior, independent review, variance reduction, or benchmark superiority. |
| Performance focused regeneration | `evidence/wordpress-high-risk-evals/wordpress-performance-critic-regenerated-focused-20260621/scorecard.md`; `evidence/wordpress-high-risk-evals/wordpress-performance-critic-regenerated-focused-answer-key-20260621/scorecard.md` | The recorded focused generation completed and the three skill outputs passed their deterministic contract; the scorecard records answer-key composites for all lanes. | Independent review, human benchmark interpretation, production behavior, or public superiority. |
| Migration planner saved-output contract | `evidence/wordpress-high-risk-evals/wordpress-planner-migration-saved-outputs-20260621/scorecard.md` | The recorded focused skill outputs and legacy smoke skill output passed the deterministic output contract. | Real migration, source-data fitness, launch readiness, or accepted baseline superiority. |
| High-risk answer-key diagnostics | `evidence/wordpress-high-risk-evals/wordpress-high-risk-answer-key-20260621/scorecard.md`; `evidence/wordpress-high-risk-evals/wordpress-high-risk-answer-key-20260621/qa-review.md`; `evidence/wordpress-high-risk-evals/wordpress-high-risk-answer-key-20260621/performance-query-cache-recall-review.md`; `evidence/wordpress-high-risk-evals/wordpress-high-risk-answer-key-20260621/performance-query-cache-semantic-annotation.md` | The recorded lexical answer-key diagnostics cover focused security, performance, and migration outputs; the scoped review records reservations and one semantic scorer miss. | Semantic LLM judging, variance, runtime proof, benchmark superiority, or accepted human interpretation of baseline quality. |
| Blueprint static certification | `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-static-cert-20260621/scorecard.md` | Three recorded packets passed packet contract, materialization, and static `blueprint.json` certification. | Playground launch, activation, editor/frontend behavior, or external services. |
| Blueprint launch-readiness preflight | `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-launch-preflight-20260621/scorecard.md` | The preflight recorded exact missing VFS payloads and a blocked result. | Browser launch, activation, editor/frontend behavior, or runtime success. |
| Self-contained Blueprint smoke | `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-self-contained-static-cert-20260621/scorecard.md`; `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-self-contained-launch-preflight-20260621/scorecard.md`; `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/scorecard.md`; `evidence/wordpress-high-risk-evals/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/qa-review.md` | One disposable self-contained Blueprint passed static certification, preflight, and a browser-observed admin-page text smoke recorded by the bundled review. | VFS-backed packet behavior, broader editor/frontend behavior, external services, independent review, or release/benchmark approval. |

## Bundled Evidence Files

The tracked public bundle consists of these two evidence trees. Each path below
must resolve to at least one tracked regular file:

- `evidence/wordpress-skill-candidate-eval/`
- `evidence/wordpress-high-risk-evals/`

The scorecards named in Current Proof Surfaces are the claim-specific entry
points. Other files below those trees are supporting raw outputs, contract
summaries, runtime-smoke JSON, generated artifacts, and scoped reviews. Their
presence does not expand a scorecard's stated proof boundary.

## Validation Bundle

Use the repository's locked environment and run every ordinary local gate:

```bash
./install.sh --verify
uv run --locked --extra test python scripts/validate-distribution-parity.py
uv run --locked --extra test python scripts/validate-agent-frontmatter.py
uv run --locked --extra test python scripts/validate-wordpress-exact-api-contract.py
uv run --locked --extra test python scripts/validate-eval-suite-integrity.py \
  --strict-suites wordpress-plugin-executor \
  --strict-suites wordpress-block-executor \
  --strict-suites wordpress-security-critic \
  --strict-suites wordpress-performance-critic \
  --strict-suites wordpress-planner.migration \
  --strict-suites wordpress-blueprint-executor \
  --strict-suites wordpress-skill-candidate-eval \
  --allow-known-gaps
uv run --locked --extra test python scripts/validate-public-docs.py
uv run --locked --extra test python -m pytest \
  -m "not docker_boundary and not live_provider" evals/harness/tests -q
```

The required Linux Docker sandbox and generated-runtime partitions are defined
in [CONTRIBUTING.md](CONTRIBUTING.md) and the Actions workflow. They run
separately from the general partition. Live-provider metadata smoke is manual
and explicitly authorized; it is not part of ordinary CI.

## Evidence Boundaries

This evidence does not claim:

- superiority over a frontier model or a strong few-shot baseline;
- lower long-run output variance across repeated generations;
- production readiness or universal security for generated artifacts;
- credentialed third-party AI-provider behavior;
- independently reviewed high-risk benchmark maturity;
- full historical-result publication, release tagging, or broad runtime
  coverage.
