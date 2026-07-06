# WordPress V1 Completion Todo

Updated: 2026-06-21.

This checklist tracks what remains before the WordPress skill suite can be treated as finished inside `zivtech-meta-skills`, and what must happen before splitting it into a standalone public `wp-meta-skills` repo.

## Current Baseline

- [x] Add `wordpress-skills/` collection with planner, executor, and critic surfaces.
- [x] Add `/wordpress-*` skill commands and matching agent definitions.
- [x] Survey the rendered skills.sh website for `wordpress`, not the skills.sh API.
- [x] Add candidate catalog, coverage matrix, provenance policy, reuse ledger, and lifecycle docs.
- [x] Add 27-fixture candidate eval suite.
- [x] Add smoke-tier eval suites for all V1 WordPress planner, executor, and critic surfaces.
- [x] Run candidate screening with official, community, license/provenance, and methodology lanes.
- [x] Repair weighted candidate-rubric parsing in `evals/harness/llm_judge.py`.
- [x] Commit and push initial V1 scaffold to `main`.
- [x] Close the frontier-model candidate-discrimination arc as directional-internal only.
  - Pairwise pilot/certification runs did not certify reliable separation from a strong few-shot prompt.
  - Fast and adversarial answer-key diagnostics found no detection/specificity edge and a small API-naming deficit.
  - Final pairwise decision: `evals/results/wordpress-skill-candidate-eval/pairwise-cert-2-xfamily/INTERNAL-DECISION-FINAL.md`.
  - Answer-key interpretation: `evals/results/wordpress-skill-candidate-eval/answerkey-diag-adversarial/RESULT-INTERPRETATION.md`.

## Finish Inside This Repo

- [x] Decide repo-level license handling before any direct GPL-family reuse.
  - Current issue: this repo documents Apache 2.0 in `README.md`, but has no standard root `LICENSE` file.
  - Decision: direct copied or closely adapted third-party prompt text is blocked inside this monorepo for WordPress V1; upstream projects remain reference/eval comparators only until root license handling or standalone release licensing is resolved.
  - Policy file: `wordpress-skills/docs/license-reuse-policy.md`.

- [x] Turn smoke scaffolds into mature V1 protocols.
  - Replaced smoke scaffold protocols with 10-phase planner/executor/critic contracts.
  - Added phases, hard gates, output contracts, companion handoffs, calibration guidance, failure modes, assumption registers, deviation logs, and verification packets.
  - Kept WordPress-native language and added Drupal-transplant guardrails.

- [x] Run the candidate discrimination pilot.
  - Generate and archive known-weak and known-strong outputs for `security-boundary-risk`, `block-development-risk`, `content-model-ambiguous`, and `performance-ops-clean`.
  - Score with the repaired weighted rubric path.
  - Result: `evals/results/wordpress-skill-candidate-eval/wordpress-candidate-pilot-20260616-live/` contains 48 outputs, 48 metadata files, 48 local Opus score files, `manifest.json`, `summary.json`, `scorecard.md`, and `internal-only-decision.md`.
  - Verdict: absolute-score discrimination failed (`-0.113` normalized separation vs. required `0.2`); switch to blind pairwise judging.

- [x] Archive candidate comparison outputs.
  - Conditions: `baseline-zero-shot`, `baseline-few-shot`, `raw_upstream_candidate`, and `zivtech_prototype`.
  - Metadata: model/version, prompt path, fixture ID, run index, condition order, judge model, and scoring config.
  - Current archive: `evals/results/wordpress-skill-candidate-eval/wordpress-candidate-pilot-20260616-live/manifest.json`.

- [x] Measure judge agreement or mark results internal-only.
  - Preferred: human or assisted annotation with an agreement metric before making quality claims.
  - Do not publish benchmark claims from single-judge uncalibrated scores.
  - Current decision: `internal-only, uncalibrated single-judge` in `evals/results/wordpress-skill-candidate-eval/wordpress-candidate-pilot-20260616-live/internal-only-decision.md`.

- [x] Run blind pairwise fallback for the candidate pilot.
  - Required because the absolute-score pilot saturated and failed separation.
  - Outcome: directional-internal only. Same-family rubric-anchored judging improved agreement, but cross-family judging confirmed moderate reliability and no robust separation from `baseline-few-shot`.

- [ ] Keep the 27-fixture candidate benchmark blocked unless the measurement target changes.
  - Do not run it for a frontier-model review-quality superiority claim.
  - Reopen only for cheaper-model lift, output-contract conformance, variance reduction, or executor/oracle-backed code generation.

- [ ] Upgrade per-skill eval evidence beyond smoke where risk warrants it.
  - At minimum, each V1 skill needs smoke-tier evidence or an explicit experimental label.
  - Plugin and block executor paths now have oracle-backed runtime evidence for
    the named generated-artifact lanes. That does not upgrade every high-risk
    suite.
  - Security critic now has focused REST/AJAX authorization,
    input/SQL/output-handling, upload/filesystem, and post-P2
    security-gate-consumption fixtures plus saved skill and baseline outputs
    with deterministic output-contract archives at
    `evals/results/wordpress-security-critic-saved-outputs-20260621/`.
    The three focused skill outputs passed the output contract 3/3.
    Deterministic answer-key coverage now exists at
    `evals/results/wordpress-high-risk-answer-key-20260621/`; focused skill
    outputs scored composite 0.936. Main-agent QA review now exists at
    `evals/results/wordpress-high-risk-answer-key-20260621/qa-review.md` and
    accepts this as internal diagnostic evidence with reservations. The lane
    still needs independent/semantic review before benchmark claims. The
    `security-gate-consumption-v1` fixture was added after the 2026-06-21
    saved-output run and needs fresh saved-output evidence before score claims
    include it.
  - Performance critic now has focused query/cache,
    autoload/transient/invalidation, and frontend-assets/render-path fixtures
    plus saved skill and baseline outputs with deterministic output-contract
    archives at
    `evals/results/wordpress-performance-critic-saved-outputs-20260621/`.
    The three focused skill outputs passed the output contract 3/3, and the
    legacy smoke skill output also passed. Deterministic answer-key coverage
    exists in `evals/results/wordpress-high-risk-answer-key-20260621/`; focused
    skill outputs tied `baseline-zero-shot` on lexical composite at 0.844, with
    higher API coverage but lower recall. Main-agent QA review now exists and
    rejects any performance-superiority claim from this run. Follow-up
    inspection found one semantic scorer miss around measurement language and
    one real archived-output gap around the custom-table scale evidence
    boundary; the performance critic prompt was amended for future generations
    without changing archived scores. Scoped semantic annotation now records
    the archived `query-cache-pressure-v1` skill output as semantically `3/4`
    on must-detect items, with the custom-table scale-evidence boundary still
    missing. Regenerated post-repair evidence now exists at
    `evals/results/wordpress-performance-critic-query-cache-regenerated-20260621/`;
    the single regenerated `query-cache-pressure-v1` skill output passed the
    output contract 1/1. Deterministic answer-key coverage for that regenerated
    output exists at
    `evals/results/wordpress-performance-critic-query-cache-regenerated-answer-key-20260621/`
    and scored recall 1.000, API coverage 0.700, specificity 1.000, and
    composite 0.900 for this one fixture. Full focused post-repair
    regeneration now exists at
    `evals/results/wordpress-performance-critic-regenerated-focused-20260621/`;
    generation passed 9/9 across `skill`, `baseline-zero-shot`, and
    `baseline-few-shot`, focused skill outputs passed the output contract 3/3,
    and baseline lanes remained 0/6 on the strict skill-output contract.
    Deterministic answer-key coverage for the regenerated focused run exists at
    `evals/results/wordpress-performance-critic-regenerated-focused-answer-key-20260621/`;
    condition composites were skill 0.915, baseline-zero-shot 0.845, and
    baseline-few-shot 0.862. The lane still needs independent review before
    benchmark claims.
  - Migration planner now has focused legacy-CMS mapping, URL/redirect/
    permalink, and cutover/rollback/reconciliation fixtures plus saved skill
    and baseline outputs with deterministic output-contract archives at
    `evals/results/wordpress-planner-migration-saved-outputs-20260621/`.
    The three focused skill outputs passed the output contract 3/3, and the
    legacy smoke skill output also passed. Deterministic answer-key coverage
    exists in `evals/results/wordpress-high-risk-answer-key-20260621/`; focused
    skill outputs scored composite 0.954. Main-agent QA review now exists and
    accepts this as internal diagnostic evidence with reservations. The lane
    still needs independent/semantic review before benchmark claims.
  - Blueprint executor now has focused minimal-plugin-environment,
    block/theme-reproduction, unsupported-feature-boundary, and
    self-contained-plugin-launch fixtures plus focused saved executor packets
    and deterministic static certification archives at
    `evals/results/wordpress-blueprint-executor-static-cert-20260621/`.
    The three focused packets passed packet contract, materialization, and
    static `blueprint.json` artifact certification 3/3. Launch-readiness
    preflight now exists at
    `evals/results/wordpress-blueprint-executor-launch-preflight-20260621/`
    and is blocked because the generated Blueprints reference VFS plugin/theme
    ZIP payloads that are absent from committed evidence. A separate
    self-contained packet passed static certification at
    `evals/results/wordpress-blueprint-executor-self-contained-static-cert-20260621/`,
    launch-readiness preflight at
    `evals/results/wordpress-blueprint-executor-self-contained-launch-preflight-20260621/`,
    and one browser-observed Playground smoke at
    `evals/results/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/`.
    Main-agent QA review now exists for that smoke and accepts it as narrow
    internal runtime evidence with reservations. The lane still needs
    independent review before benchmark claims; VFS-backed runtime claims still
    need supplied payloads and their own launch evidence.
  - Maturation plan:
    `wordpress-skills/docs/high-risk-eval-maturation-plan-2026-06-21.md`.
  - Do not mark this item complete merely because the plan exists; completion
    requires focused fixtures, rubrics, saved outputs, oracle runs, strict
    validation, and review for the matured suites.

- [x] Add an Exact API and Verification Contract amendment to WordPress agents and skill wrappers.
  - Triggered by the answer-key diagnostic: API naming was the only axis with meaningful spread, and `zivtech_prototype` trailed the baselines.
  - Agents and skill wrappers now require exact WordPress functions, hooks, files, packages, commands, or an explicit explanation of why no exact API applies.
  - `scripts/validate-wordpress-exact-api-contract.py` now verifies the contract across WordPress agents, skill wrappers, and candidate-eval rubrics.
  - Candidate-eval `expected_wordpress_apis` entries were hardened from category labels to exact functions, file globs, packages, commands, or named verification surfaces.

- [x] Run a cheaper-model model-dependence test after the Exact API amendment.
  - Question tested: does the WordPress suite lift Haiku generation on adversarial answer-key fixtures?
  - Result: directional null. `answerkey-haiku-adversarial-fast-20260620` showed no broad per-task review-quality lift (`zivtech - zero-shot = -0.006`, `zivtech - few-shot = 0.039`; both CIs straddle zero).
  - Boundary: this was one fast run, not a universal cheaper-model theorem; it weakens the cheap-model review-quality proposition and pushes value discovery toward contracts, variance, and runtime executor oracles.

  - [ ] Redesign the next eval around the skill suite's plausible value.
  - [x] Deterministic contract adherence gate for exact API naming and prompt/rubric drift.
  - [x] Model-output contract adherence: required headings, critic verdict shape, negative-space statements, exact WordPress surfaces, and verification-oracle specificity via `evals/harness/validate_wordpress_skill_output.py`.
  - Consistency: lower variance across runs and authors.
  - [x] Deterministic saved-packet oracle for plugin/block/blueprint executor outputs: `evals/harness/validate_wordpress_executor_packet.py`.
  - [x] Packet-to-artifact materialization bridge for plugin/block/Blueprint executor packets: `evals/harness/materialize_wordpress_executor_packet.py`.
  - [x] Deterministic static artifact oracle for generated plugin/block/theme/Blueprint files: `evals/harness/validate_wordpress_artifact.py`.
  - [x] Cheap WPCS-shape artifact gate: plugin static artifacts now fail before runtime if generated PHP has a plugin header without a file-level `@package` tag or obvious short `[]` array literals. This catches the `20260620b` Abilities artifact's WPCS failure class without booting `wp-env`.
  - [x] Combined deterministic executor certification gate: `evals/harness/certify_wordpress_executor_artifact.py`.
  - [x] Deterministic executor repair-prompt loop: failed or blocked certifications now emit fence-safe `repair-prompt.md`, so the next revision pass can consume oracle feedback without a judge rewriting the failure by hand.
  - [x] First ChatGPT-level repair-loop proof: `wordpress-plugin-executor-abilities-ai-repair-loop-20260620c` consumed the WPCS-shape `repair-prompt.md`, repaired the Abilities packet, passed static certification, and then passed the provisioned full plugin runtime profile at `generated-abilities-ai-repair-loop-full-profile-20260620c` including WPCS/PHPCS, Plugin Check, WordPress `7.0` `wp-env`, plugin activation, and `wp_get_ability()` execution.
  - [x] ChatGPT-level baseline lane for invoke-based WordPress smoke suites: `evals/harness/invoke.py` can route condition names beginning `baseline-*` through isolated local Codex CLI, and the WordPress planner/critic/executor smoke `eval.yaml` files now declare `baseline_provider: codex`, `baseline_model_policy: newest-chatgpt-level-at-run-time`, `baseline_model: gpt-5.5`, and `baseline_effort: medium`.
  - [x] Plugin executor ChatGPT baseline smoke: `wordpress-plugin-executor-chatgpt-baseline-isolated-smoke-20260620c` resolved to `gpt-5.5` with `model_policy: newest-chatgpt-level-at-run-time` and passed packet, materialization, current static artifact including `php_wpcs_shape_heuristics`, and `php-lint` gates.
  - [x] Candidate-comparison pilot ChatGPT baseline migration: `evals/harness/run_wordpress_candidate_pilot.py`, `run_pairwise_pilot.py`, and `answer_key_score.py --generate` now route `baseline-*` generation through isolated local Codex (`gpt-5.5` by default) while keeping skill/upstream lanes on explicit isolated Claude prompt surfaces. Boundary: old candidate artifacts remain historical, and a fresh candidate-comparison run is required before claiming new ChatGPT-baseline results.
  - [ ] Fresh candidate-comparison evidence after ChatGPT baseline migration: rerun the selected candidate/pairwise/answer-key path only for a changed measurement target such as output-contract conformance, variance, or oracle-backed code generation. Do not reopen frontier-model review-quality superiority as the target.
  - [x] Plugin executor static golden-packet certification: `evals/results/wordpress-skill-candidate-eval/plugin-executor-static-cert-20260620/scorecard.md`.
  - [x] Historical Claude live plugin executor-output certification: `evals/results/wordpress-plugin-executor-live-cert-20260620c/raw/wordpress-plugin-executor/skill/smoke-wordpress-v1.md` passed saved-output contract and `evals/results/wordpress-skill-candidate-eval/plugin-executor-live-cert-20260620/scorecard.md` passed packet, materialization, static artifact, and `php-lint` gates after configuring the suite for `sonnet` plus `low` effort. This is not the current baseline default.
  - [x] Repeated live executor-output certification: three live plugin outputs passed the certifier (`20260620c`, `20260620d`, `20260620f`). One intermediate output (`20260620e`) failed correctly on missing negative-space language and non-literal file-map paths; the executor contract and fixture were tightened before rerun.
  - [x] Narrow local runtime smoke lane: a disposable plugin fixture passed `php-lint` plus `wp-env` via `--wp-env-root`; see `evals/results/wordpress-skill-candidate-eval/wp-env-runtime-smoke-20260620/RESULT.md`.
  - [x] Reusable runtime smoke harness: `python3 evals/harness/run_wordpress_runtime_smoke.py --write --run-id wp-env-runtime-smoke-harness-20260620 --timeout-sec 300` passed and wrote `evals/results/wordpress-skill-candidate-eval/wp-env-runtime-smoke-harness-20260620/`.
  - [x] Provisioned disposable full plugin runtime profile: `python3 evals/harness/run_wordpress_runtime_smoke.py --provision-full-profile --write --run-id wp-env-runtime-full-profile-20260620 --timeout-sec 300` passed WPCS and Plugin Check and wrote `evals/results/wordpress-skill-candidate-eval/wp-env-runtime-full-profile-20260620/`.
  - [x] Generated plugin PHPUnit full-profile proof: `evals/suites/wordpress-plugin-executor/examples/phpunit-wordpress-v1.materializable-packet.md` passed packet/materialization/static certification into `evals/results/wordpress-skill-candidate-eval/generated-plugin-phpunit-artifact-cert-20260620/generated-plugin`, then passed `python3 evals/harness/run_wordpress_runtime_smoke.py --artifact-path evals/results/wordpress-skill-candidate-eval/generated-plugin-phpunit-artifact-cert-20260620/generated-plugin/acme-runtime-tested --phpunit-smoke --provision-full-profile --write --run-id generated-plugin-phpunit-full-profile-20260620 --timeout-sec 300`. The disposable run activated the generated plugin in WordPress `7.0`, installed artifact-local PHPUnit with Composer, passed `phpunit` (`3 tests, 3 assertions`), and passed WPCS/PHPCS plus Plugin Check.
  - [x] Plugin executor focused modern-surface fixture: `abilities-ai-surface-v1` covers Abilities API registration, guarded AI Client helper, Connectors boundary, and MCP Adapter discovery/execution as a verification boundary. The hardened live output `20260620b` exposed a real WPCS-shape failure; the certifier now catches that failure and emits a repair prompt. The repaired ChatGPT-level packet `20260620c` passes static, WPCS, Plugin Check, activation, and Abilities execution gates.
  - [x] Narrow server-rendered block runtime registration smoke: `python3 evals/harness/run_wordpress_runtime_smoke.py --fixture-kind block --block-name acme/runtime-card --write --run-id wp-env-block-runtime-smoke-20260620 --timeout-sec 300` passed in WordPress `7.0`, activating a disposable block plugin and proving `WP_Block_Type_Registry` registration for `acme/runtime-card`.
  - [x] Narrow editor-side block registry smoke: `python3 evals/harness/run_wordpress_runtime_smoke.py --fixture-kind block --block-name acme/runtime-card --editor-smoke --write --run-id wp-env-block-editor-smoke-20260620 --timeout-sec 180` passed in WordPress `7.0`, opening the post editor with Playwright and proving `window.wp.blocks.getBlockType('acme/runtime-card')` resolves with no page or console errors.
  - [x] End-to-end disposable block editor/render smoke: `python3 evals/harness/run_wordpress_runtime_smoke.py --fixture-kind block --block-name acme/runtime-card --editor-insert-render-smoke --write --run-id wp-env-block-editor-insert-render-smoke-20260620 --timeout-sec 180` passed in WordPress `7.0`, inserting the block, publishing a post, opening the frontend permalink, and proving the server-rendered block text appears with no page or console errors.
  - [x] Generated block-artifact certification and full runtime proof: `evals/suites/wordpress-block-executor/examples/smoke-wordpress-v1.materializable-packet.md` passed the block packet contract, materialized into `evals/results/wordpress-skill-candidate-eval/generated-block-artifact-cert-20260620/generated-block`, passed static block artifact certification, then passed `python3 evals/harness/run_wordpress_runtime_smoke.py --artifact-path evals/results/wordpress-skill-candidate-eval/generated-block-artifact-cert-20260620/generated-block --artifact-kind block --block-build-smoke --editor-insert-render-smoke --provision-full-profile --write --run-id generated-block-full-profile-20260620 --timeout-sec 300`. The runtime harness inferred `acme/runtime-card` from `block.json`, synthesized a disposable wrapper plugin, ran `npm install` plus `npm run build` on the disposable block copy, passed WPCS/PHPCS and Plugin Check for the wrapper, inserted/published the block, and proved the frontend text with no page or console errors.
  - [x] Generated block Interactivity API full-profile proof: `evals/suites/wordpress-block-executor/examples/interactivity-wordpress-v1.materializable-packet.md` passed the block packet contract, materialized into `evals/results/wordpress-skill-candidate-eval/generated-block-interactivity-artifact-cert-20260621/generated-block`, passed static block artifact certification, then passed `python3 evals/harness/run_wordpress_runtime_smoke.py --artifact-path evals/results/wordpress-skill-candidate-eval/generated-block-interactivity-artifact-cert-20260621/generated-block --artifact-kind block --block-build-smoke --editor-insert-render-smoke --interactivity-smoke --provision-full-profile --write --run-id generated-block-interactivity-full-profile-20260621 --timeout-sec 300`. The runtime harness registered the built block metadata, passed WPCS/PHPCS and Plugin Check, inserted/published the block, proved frontend render, and clicked the Interactivity API button to change `context.count` from `0` to `1` with no page or console errors.
  - [x] Generated block deprecation full-profile proof: `evals/suites/wordpress-block-executor/examples/deprecation-wordpress-v1.materializable-packet.md` passed the block packet contract, materialized into `evals/results/wordpress-skill-candidate-eval/generated-block-deprecation-artifact-cert-20260621/generated-block`, passed static block artifact certification, then passed `python3 evals/harness/run_wordpress_runtime_smoke.py --artifact-path evals/results/wordpress-skill-candidate-eval/generated-block-deprecation-artifact-cert-20260621/generated-block --artifact-kind block --block-build-smoke --deprecation-smoke --provision-full-profile --write --run-id generated-block-deprecation-full-profile-20260621 --timeout-sec 300`. The runtime harness created a post from a legacy serialized fixture, opened the editor, verified the migrated current-block `content` attribute, serialized the current block tree, saved current markup with `<strong>Runtime block smoke:</strong>`, and proved frontend text `Runtime block smoke: Legacy runtime smoke` with no page or console errors.
  - [x] Generated MCP Adapter full-profile proof: `evals/suites/wordpress-plugin-executor/examples/mcp-adapter-wordpress-v1.materializable-packet.md` passed the plugin packet contract, materialized into `evals/results/wordpress-skill-candidate-eval/generated-mcp-adapter-artifact-cert-20260621/generated-plugin/acme-mcp-smoke`, passed static plugin artifact certification, then passed `python3 evals/harness/run_wordpress_runtime_smoke.py --artifact-path evals/results/wordpress-skill-candidate-eval/generated-mcp-adapter-artifact-cert-20260621/generated-plugin/acme-mcp-smoke --ability-name acme-mcp-smoke/get-runtime-marker --mcp-adapter-smoke --mcp-adapter-execute-args-json '{"marker":"Runtime MCP smoke"}' --mcp-adapter-expected-output "Runtime MCP smoke" --provision-full-profile --write --run-id generated-mcp-adapter-full-profile-20260621 --timeout-sec 300`. The runtime harness installed the WordPress MCP Adapter plugin zip, listed the default server, called `tools/list` through `wp mcp-adapter serve`, discovered the generated MCP-public ability, executed it through `mcp-adapter-execute-ability`, and passed WPCS/PHPCS plus Plugin Check. The adapter emitted upstream PHP deprecation notices under the local PHP runtime; the command exited `0`, so this is adapter/runtime risk rather than generated-plugin failure.
  - [x] Generated AI Client provider-call full-profile proof: `evals/suites/wordpress-plugin-executor/examples/ai-client-provider-wordpress-v1.materializable-packet.md` passed the plugin packet contract, materialized into `evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-artifact-cert-20260621/generated-plugin/acme-ai-client-smoke`, passed static plugin artifact certification, then passed `python3 evals/harness/run_wordpress_runtime_smoke.py --workdir /tmp/wp-ai-client-runtime-smoke-20260621c --artifact-path evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-artifact-cert-20260621/generated-plugin/acme-ai-client-smoke --ai-client-smoke --ai-client-provider-id acme-ai-client-smoke --ai-client-model-id acme-deterministic-text --ai-client-helper-function 'AcmeAIClientSmoke\generate_summary' --ai-client-prompt "Runtime AI Client smoke" --ai-client-expected-output "AI Client smoke: deterministic provider response" --provision-full-profile --write --run-id generated-ai-client-provider-full-profile-20260621 --timeout-sec 300`. The runtime harness activated the generated deterministic no-auth provider in WordPress `7.0`, verified `wp_ai_client_prompt()`, verified `WordPress\AiClient\AiClient::defaultRegistry()`, confirmed provider registration/configuration, confirmed connector registration, invoked `AcmeAIClientSmoke\generate_summary()`, recorded output `AI Client smoke: deterministic provider response`, and passed WPCS/PHPCS plus Plugin Check.
  - [x] Runtime executor oracle coverage after the repaired plugin, PHPUnit plugin, generated-block, generated-block Interactivity, generated-block deprecation, generated MCP Adapter, and generated AI Client paths: current repaired plugin proof covers WPCS/PHPCS, Plugin Check, activation, and Abilities execution; generated plugin PHPUnit proof covers packet/materialization/static certification, plugin activation, Composer-installed PHPUnit, WPCS/PHPCS, and Plugin Check; generated block proof covers packet/materialization/static certification, block build, wrapper-based `wp-env` registration, WPCS/PHPCS, Plugin Check, editor insertion, save/publish, and frontend server-rendered output; generated block Interactivity proof covers built `viewScriptModule`, static Interactivity surfaces, editor insertion, frontend render, and a Playwright click/state assertion; generated block deprecation proof covers one legacy serialized fixture migrated through WordPress' deprecation path into current saved markup and frontend output; generated MCP Adapter proof covers adapter installation, STDIO tool discovery, public ability discovery, public ability execution, WPCS/PHPCS, and Plugin Check; generated AI Client proof covers a deterministic no-auth provider boundary, connector registration, `wp_ai_client_prompt()`, model preference selection, generated output, WPCS/PHPCS, and Plugin Check. This still does not prove credentialed third-party AI provider behavior, long-run variance, broad integration coverage, or release readiness.
  - [x] Static modern WordPress agent-surface contract: Exact API contracts and candidate risk fixtures now cover `wp_register_ability()`/`wp_abilities_api_init`, `label`/`description`/`category`, `wp_register_ability_category()`/`wp_abilities_api_categories_init`, `input_schema`/`output_schema`, `execute_callback`, `permission_callback`, `wordpress/mcp-adapter`, MCP discovery/execution boundaries, `wp_ai_client_prompt()`, `wp_connectors_init`, `@wordpress/abilities`, and `@wordpress/core-abilities`.
  - [x] Runtime modern WordPress agent-surface oracle: proven for generated Abilities discovery/execution via `wp_get_ability()` in WordPress `7.0`, generated MCP Adapter exposure/execution through `wp mcp-adapter serve`, and deterministic no-auth AI Client/Connectors provider behavior through `wp_ai_client_prompt()` in WordPress `7.0`. Credentialed external-provider behavior remains explicit negative space.

- [x] Fill provenance ledger entries for every adapted upstream passage.
  - Include source repo, commit SHA, license, local file, adapted section, and rationale.
  - Keep reference-only candidates out of copied/adapted prompt text.
  - Current state: no copied or closely adapted upstream passages are included; `reuse-ledger.md` records reference-only candidates and the active in-repo policy blocks direct reuse.

- [x] Update root strategic docs.
  - Add WordPress to `zivtech-meta-skills-plan.md`.
  - Keep `AGENTS.md`, `CLAUDE.md`, `wordpress-skills/AGENTS.md`, and `wordpress-skills/CLAUDE.md` aligned on status and lifecycle.

- [x] Verify installer and registry behavior after protocol maturation and pilot archive.
  - Run `./install.sh --generate-manifest`.
  - Run `./install.sh --verify`.
  - Run `python3 scripts/validate-agent-frontmatter.py`.
  - Run `python3 scripts/validate-wordpress-exact-api-contract.py`.
  - Run strict eval validation for all WordPress suites.
  - Current state: the WordPress Exact API contract gate, skill-output contract oracle, executor packet oracle, packet materializer, and static artifact oracle were added on 2026-06-20; the focused gate bundle passes locally for this pass.

- [x] Decide what "done here" means.
  - Monorepo recovery done: PR #11 is approved and merged into `main` with the
    `validate-package` check passing on the merge candidate.
  - Internal evidence done: mature protocols, documented frontier-review null
    result, Exact API amendment, updated docs, provenance clean, smoke evidence
    for every V1 surface, and oracle-backed executor/runtime proofs for the
    high-risk plugin/block surfaces named above.
  - Benchmark done: redefined away from frontier-review superiority and toward
    contract/oracle evidence. Long-run variance remains an optional future
    measurement target, not a blocker for monorepo recovery.
  - Public-release done: standalone public `wp-meta-skills` repo exists, uses
    the approved history strategy, runs live standalone-package Actions, and
    has public owner approval for metadata, security reporting, evidence
    boundaries, and the cutover/source-of-truth plan.
  - Explicit non-goals for this monorepo recovery PR: credentialed external AI
    provider proof, broad production readiness of generated artifacts, and
    public full-archive hosting. Focused benchmark maturity for the
    security, performance, migration, and Blueprint suites is also not claimed
    by this PR; all four now have focused fixture scaffolding. Security critic,
    performance critic, and migration planner additionally have saved-output
    contract evidence plus deterministic lexical answer-key coverage for the
    focused fixtures plus a main-agent QA review accepting the answer-key run
    with reservations. The performance query/cache archived output now has a
    scoped main-agent semantic annotation, but independent/semantic benchmark
    review remains open.
    Blueprint now has focused static packet certification and one
    self-contained Playground launch smoke plus main-agent QA review, but
    VFS-backed packets still lack the payloads needed for their launch proof
    and the lane still lacks independent review.

## Standalone Public Repo Prep

- [x] Choose release name and scope.
  - Working name: `wp-meta-skills`.
  - Scope: WordPress skills, WordPress docs, WordPress eval suites, and the WordPress-relevant harness/scripts required to validate the package outside this monorepo.
  - Evidence: `wordpress-skills/docs/standalone-extraction-readiness-2026-06-21.md`.

- [x] Prepare extraction plan from `zivtech-meta-skills`.
  - Extract WordPress skill surfaces to root `.claude/agents` and `.claude/skills`.
  - Include WordPress docs under `docs/wordpress/`.
  - Include WordPress eval suites plus harness/scripts needed for validation.
  - Keep paths compatible with Claude/Codex skill discovery.
  - Boundary: the history-preserving mechanism is still undecided.

- [x] Create standalone repository metadata.
  - `README.md`
  - `AGENTS.md`
  - `CLAUDE.md`
  - `LICENSE`
  - `CHANGELOG.md`
  - `SECURITY.md`
  - contribution/reuse policy
  - `EVIDENCE.md`
  - `PROVENANCE.md`
  - `PUBLICATION-CHECKLIST.md`
  - Source: `wordpress-skills/standalone/`.
  - Package root now includes `.gitignore`, Apache-2.0 `LICENSE`, `CHANGELOG.md`,
    `SECURITY.md`, `CONTRIBUTING.md`, `EVIDENCE.md`, `PROVENANCE.md`, and
    `PUBLICATION-CHECKLIST.md`.
  - Boundary: public owner review and post-publication security contact replacement are still needed.

- [x] Define standalone install and verification commands.
  - Include manifest generation/verification or a repo-local equivalent.
  - Document Claude and Codex install locations.
  - Document how sibling repos consume the public package.
  - Evidence: `wordpress-skills/docs/standalone-extraction-readiness-2026-06-21.md`.

- [x] Re-run all WordPress validations in the extracted dry-run package.
  - Agent frontmatter validation.
  - Manifest verification.
  - Strict WordPress eval validation.
  - Candidate-rubric parser smoke.
  - Secret/provenance scan.
  - Dry-run path: `/tmp/wp-meta-skills-extraction-20260621-233205`.
  - Passed: manifest verification, agent frontmatter validation, WordPress Exact API validation, strict selected WordPress suite validation, and 85 extracted-package harness tests.
  - Scoped secret scan found no real credentials; the only literal-assignment match was the documented `ANTHROPIC_API_KEY="<anthropic-api-key>"` placeholder in `evals/harness/README.md`.
  - Boundary: this dry run preceded the standalone staging repository and
    live standalone CI run.

- [x] Add reproducible pruned package builder.
  - Builder: `scripts/build-wp-meta-skills-package.py`.
  - Command: `python3 scripts/build-wp-meta-skills-package.py --output /tmp/wp-meta-skills-pruned-20260621 --force --generate-manifest`.
  - Output: `/tmp/wp-meta-skills-pruned-20260621`.
  - Package footprint: 346 files, 2.3M, 18 harness files, and 12 harness test files.
  - Passed in the pruned package: manifest verification, agent frontmatter validation, WordPress Exact API validation, strict selected WordPress suite validation, and the 125-test WordPress harness bundle.
  - Scoped secret scan found no real credentials; the only literal-assignment matches were copies of the documented `ANTHROPIC_API_KEY="<anthropic-api-key>"` placeholder.

- [x] Decide first-draft public history/release strategy.
  - Decision: clean import the generated package with `PROVENANCE.md` preserved.
  - Reason: a raw `wordpress-skills` subtree split omits root harness files,
    validation scripts, `install.sh`, and selected evidence copied from
    `evals/results/`.
  - Local rehearsal: `wordpress-skills/docs/public-repo-rehearsal-2026-06-21.md`
    documents a clean-import repo initialized on `main` from the generated
    package, followed by manifest, frontmatter, Exact API, strict selected
    suite, and 125-test harness validation.
  - If maintainers require history preservation later, use a post-commit
    path-aware filtering strategy over all package source areas and validate the
    resulting repository with the same package gates.
  - Rehearsal: `git subtree split --prefix=wordpress-skills HEAD` passed for committed history and returned `ef7e00b2f848ee57f2f008714855fe440b78d892`.
  - Boundary: maintainer approval of this clean-import strategy, or a verified
    path-aware history-preserving alternative, is still required before public
    release.

- [x] Add standalone CI for the pruned package validation bundle.
  - Workflow source: `wordpress-skills/standalone/.github/workflows/validate.yml`.
  - Generated package path: `/tmp/wp-meta-skills-pruned-20260621/.github/workflows/validate.yml`.
  - Current live staging validation evidence is tracked in the
    public-release approval issue:
    public issue tracker.
  - Boundary: public visibility approval and any post-publication run/tag still
    have not happened.

- [x] Add monorepo PR validation for the generated package.
  - Workflow source: `.github/workflows/wordpress-meta-skills.yml`.
  - It builds the pruned standalone package, then validates package manifest,
    agent frontmatter, WordPress Exact API contracts, strict selected WordPress
    eval suites, and the focused WordPress harness bundle.
  - It now runs on relevant PR events and on `main`/`codex/**` branch pushes
    for the same WordPress/package paths so the current branch head keeps an
    attached validation surface.
  - Live PR check: `validate-package` has passed on PR #11. Use
    `gh pr checks 11` for the current run URL and latest status.
  - Boundary: this gives PR #11 a monorepo package-validation check surface; it
    is not a substitute for owner approval to publish the private
    `wp-meta-skills` staging repository.

- [x] Select public evidence surfaces.
  - Manifest source: `wordpress-skills/standalone/EVIDENCE.md`.
  - Covers package extraction, static contracts, plugin PHPUnit, block build/editor/frontend render, block Interactivity, block deprecation, MCP Adapter, deterministic no-auth AI Client provider-call evidence, and selected high-risk saved-output contract evidence.
  - Generated package includes six selected runtime proof scorecards and six matching runtime JSON files under `evidence/wordpress-skill-candidate-eval/`.
  - Generated package also includes selected saved-output and output-contract
    archives for `wordpress-security-critic`, `wordpress-performance-critic`,
    `wordpress-planner.migration`, and `wordpress-blueprint-executor` under
    `evidence/wordpress-high-risk-evals/`.
  - Boundary: full result archives are not bundled in the standalone package; before publication, publish selected result directories or convert evidence paths to public URLs.

- [x] Commit local recovery slices.
  - Clean review branch: `codex/wordpress-meta-skills-recovery`.
  - `19fab3e chore: add WordPress standalone release packaging`.
  - `bab24bb test: add WordPress oracle validation gates`.
  - `ab718e6 docs: update WordPress recovery handoff state`.
  - `3a46a0c docs: correct WordPress recovery handoff state`.
  - Tracked worktree is clean after these substantive recovery commits.
    Use `git log origin/main..HEAD` for the live local count.
  - Monorepo PR: https://github.com/zivtech/zivtech-meta-skills/pull/11.
    It is ready for review; live state at this checkpoint is
    `reviewDecision=REVIEW_REQUIRED` and `mergeStateStatus=BLOCKED`.
    Use `gh pr view 11` and `gh pr checks 11` for current review/check state.
  - Review routing: a `zivtech/crew` team review request failed with GitHub
    HTTP 422 because GitHub did not treat that team as a valid collaborator
    reviewer for this repo. Individual review requests are now assigned to
    `grndlvl`, `misterjones`, and `pmzivtech`, the collaborator overlap between
    the monorepo and standalone staging repo. Current reviewer and approval
    state is tracked in PR #11 and standalone approval issue #1.
  - Boundary: this is a monorepo recovery branch, not the standalone public
    `wp-meta-skills` repository.

- [x] Create private clean-import `wp-meta-skills` staging repository.
  - Repo: https://github.com/zivtech/wp-meta-skills.
  - Visibility: staging.
  - Initial clean-import commit:
    `8798b2e11ba5335ca5452be8bb01ddd9b09a0d03`.
  - Package path used for import:
    `<local scratch path omitted>`.
  - Pre-import gates passed: package manifest verification, agent frontmatter,
    WordPress Exact API, selected strict eval-suite validation, 125-test harness
    bundle, and scoped placeholder-only secret scan.
  - Current live standalone GitHub Actions validation evidence is tracked in
    the public-release approval issue:
    public issue tracker.
  - Boundary: this is not public release. Public visibility, owner review, and
    final history/evidence approval are still pending.

- [x] Add standalone cutover/source-of-truth plan.
  - Plan source: `wordpress-skills/standalone/CUTOVER.md`.
  - Generated package includes the root `CUTOVER.md` file.
  - Public-release checklist includes it in the review packet and
    approval gates.
  - Boundary: the plan is not approved yet. It becomes operative only after
    owner approval, PR merge, public visibility approval, and final standalone
    Actions pass.

- [ ] Publish `wp-meta-skills` as its own public repo.
  - Requires maintainer approval of the standalone metadata and clean-import
    strategy.
  - Requires maintainer approval of `CUTOVER.md` so future WordPress skill work
    has one source of truth after release.
  - Private staging repo exists and validates; this item requires approval to
    make the repo public or create the public release surface from it.
  - Public-release checklist:
    public issue tracker.
  - Approval issue assignees: `grndlvl`, `misterjones`, and `pmzivtech`.
  - Requires publishing selected full result archives or converting evidence
    paths to public artifact URLs, unless those archives stay explicitly out of
    scope for the first public draft.
