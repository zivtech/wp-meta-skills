# WordPress Meta-Skills Goal Handoff - 2026-06-21

## Active Goal

Build truly helpful, testable, and efficient WordPress meta-skills, comparable in usefulness to the a11y and Drupal meta-skills. Do not redefine success around frontier-model review-quality wins; the evidence so far says that target is saturated.

Keep the goal active. Do not call it complete until the WordPress suite has durable, current-baseline, oracle-backed evidence across the important planner/executor/critic surfaces and the remaining runtime gaps are either proven or explicitly scoped out.

Current done definition:

- Final destination boundary: all WordPress work must end in the standalone
  `wp-meta-skills` repository. The monorepo PR is a recovery, review, and
  package-generation bridge; it is not the permanent home of the WordPress
  package.
- Monorepo recovery is done only after PR #11 is approved and merged into
  `main` with `validate-package` passing on the merge candidate.
- Standalone staging now exists as a private clean-import repo at
  https://github.com/zivtech/wp-meta-skills. Public release is done only after
  that repo is approved for public visibility, uses an approved history
  strategy, runs live standalone-package Actions, and has public owner approval
  for metadata, security reporting, evidence boundaries, and the
  cutover/source-of-truth plan in `CUTOVER.md`.
- Standalone public-release approval is tracked in
  public issue tracker.
- Credentialed external AI-provider proof, broad production readiness of
  generated artifacts, public full-archive hosting, and long-run variance
  measurement are not claimed by the monorepo recovery PR.

## Current Repo State

- Repo: `/path/to/zivtech-meta-skills`
- Clean WordPress recovery branch: `codex/wordpress-meta-skills-recovery`
- Private standalone staging repo: https://github.com/zivtech/wp-meta-skills
  on `main`. The live staging commit, validation evidence, release approval
  gates, assignees, and visibility status are tracked in
  public issue tracker.
- Tracked worktree at recovery checkpoint: clean.
- Branch status is live state; use `git status --short --branch` and
  `git log origin/main..HEAD` for the current count and stack. The substantive
  clean-branch recovery stack before this handoff update includes:
  - `19fab3e chore: add WordPress standalone release packaging`
  - `bab24bb test: add WordPress oracle validation gates`
  - `ab718e6 docs: update WordPress recovery handoff state`
  - `3a46a0c docs: correct WordPress recovery handoff state`
- Historical note: these changes first landed locally on
  `codex/paul-gadue-stem-cell-skills`, but that branch also contains unrelated
  stem-cell commits. Use `codex/wordpress-meta-skills-recovery` as the clean
  WordPress monorepo review branch.
- Remote monorepo handoff: PR #11 is open and ready for review,
  https://github.com/zivtech/zivtech-meta-skills/pull/11. The PR body carries
  the current monorepo head, current validation link, standalone staging state,
  and explicit remaining gates. Use `gh pr view 11` and `gh pr checks 11` for
  current review/check state.
- Monorepo PR validation workflow source:
  `.github/workflows/wordpress-meta-skills.yml`. It builds the pruned
  standalone package and runs the package-local manifest, metadata, Exact API,
  selected eval-suite, and harness-test gates. It runs on relevant PR events
  and on `main`/`codex/**` branch pushes for the same WordPress/package paths
  so branch heads keep an attached validation surface.
- Live monorepo PR validation: `validate-package` has run on PR #11 and passed.
  Use `gh pr checks 11` for the current run URL and latest status.
- Review-routing state: the `zivtech/crew` team review request failed with
  GitHub HTTP 422, "Reviews may only be requested from collaborators." The
  recovery path is now individual review requests from the collaborator overlap
  on both repos: `grndlvl`, `misterjones`, and `pmzivtech`. Current reviewer
  and approval state is tracked in PR #11 and standalone approval issue #1.
- Standalone cutover plan: `wordpress-skills/standalone/CUTOVER.md` is included
  in the generated package and requires owner approval before public release.
  It keeps the post-release source of truth in `zivtech/wp-meta-skills` and
  limits future monorepo WordPress changes to back-references, archive updates,
  or migration cleanup after cutover.
- Ignored local caches, run logs, and checkpoint directories may remain under
  `.pytest_cache/`, `__pycache__/`, and `evals/results/.../checkpoint/`; these
  are not part of the tracked recovery state.
- Installer manifest was regenerated and committed with the oracle validation
  gates. `./install.sh --verify` passed after regeneration.

## Main Decision Already Made

The old "beat Sonnet/Claude on generic WordPress review quality" framing is the wrong hill. The repo now points new WordPress baseline lanes at the newest ChatGPT-level Codex baseline for `baseline-*` conditions, while preserving historical Sonnet/Opus artifacts as historical evidence.

The useful value proposition is now:

- deterministic output contracts;
- exact WordPress API and verification-surface naming;
- materializable executor packets;
- static and runtime artifact oracles;
- repair prompts from gate failures;
- current WordPress surfaces such as Abilities API, MCP Adapter, AI Client, block build/runtime/editor paths, WPCS, Plugin Check, PHPUnit, and `wp-env`.

## Completed In The Latest Slice

### Generated Plugin PHPUnit Proof

Added and verified a generated plugin PHPUnit lane:

- Packet: `evals/suites/wordpress-plugin-executor/examples/phpunit-wordpress-v1.materializable-packet.md`
- Static certification result: `evals/results/wordpress-skill-candidate-eval/generated-plugin-phpunit-artifact-cert-20260620/`
- Full runtime result: `evals/results/wordpress-skill-candidate-eval/generated-plugin-phpunit-full-profile-20260620/`

Evidence from the full-profile scorecard:

- Status: `pass`
- Narrow gate: `pass`
- Full plugin runtime profile: `pass`
- Plugin activation: `0`
- PHPUnit smoke: `pass`
- Provisioned full profile: `true`

The runtime harness copied the generated `acme-runtime-tested` plugin into disposable `wp-env`, installed artifact-local PHPUnit through Composer, activated the plugin in WordPress `7.0`, passed `phpunit` (`3 tests, 3 assertions`), and passed WPCS/PHPCS plus Plugin Check.

### Harness Tightening

Updated `evals/harness/run_wordpress_runtime_smoke.py` so `--phpunit-smoke` blocks when artifact-local `composer install` fails, even if a global `phpunit` binary could otherwise mask the failure.

Updated tests:

- `evals/harness/tests/test_wordpress_runtime_smoke.py`
- `evals/harness/tests/test_wordpress_artifact_oracle.py`
- `evals/harness/tests/test_wordpress_packet_materializer.py`

Updated docs/status:

- `evals/harness/README.md`
- `evals/suites/wordpress-plugin-executor/README.md`
- `evals/suites/wordpress-plugin-executor/eval.yaml`
- `evals/suites/wordpress-plugin-executor/pilot-results.md`
- `wordpress-skills/docs/lifecycle.md`
- `wordpress-skills/docs/runtime-oracle-runbook.md`
- `wordpress-skills/docs/skill-improvement-research-2026-06-20.md`
- `wordpress-skills/docs/v1-completion-todo.md`

## Verification Already Run

These passed earlier after the PHPUnit harness/doc changes:

```bash
python3 -m pytest evals/harness/tests/test_wordpress_packet_materializer.py evals/harness/tests/test_wordpress_artifact_oracle.py evals/harness/tests/test_wordpress_runtime_smoke.py -q
# 51 passed
```

```bash
python3 -m pytest evals/harness/tests/test_invoke_claude_command.py evals/harness/tests/test_wordpress_runtime_smoke.py evals/harness/tests/test_wordpress_artifact_oracle.py evals/harness/tests/test_wordpress_executor_packet_oracle.py evals/harness/tests/test_wordpress_exact_api_contract.py evals/harness/tests/test_wordpress_executor_artifact_certifier.py evals/harness/tests/test_wordpress_packet_materializer.py evals/harness/tests/test_wordpress_skill_output_contract.py evals/harness/tests/test_answer_key_score.py evals/harness/tests/test_pairwise_pilot.py evals/harness/tests/test_wordpress_candidate_pilot_generation.py -q
# earlier PHPUnit slice: 112 passed; latest bundle below is 118 passed
```

```bash
python3 -m py_compile evals/harness/materialize_wordpress_executor_packet.py evals/harness/validate_wordpress_artifact.py evals/harness/run_wordpress_runtime_smoke.py evals/harness/certify_wordpress_executor_artifact.py
node --check evals/harness/run_wordpress_editor_smoke.js
python3 scripts/validate-wordpress-exact-api-contract.py
python3 scripts/validate-agent-frontmatter.py
python3 scripts/validate-eval-suite-integrity.py --strict-suites wordpress-plugin-executor --strict-suites wordpress-block-executor --strict-suites wordpress-skill-candidate-eval --allow-known-gaps
./install.sh --generate-manifest
./install.sh --verify
git diff --check
```

The strict eval-suite command still reports many repo-wide non-strict issues, but it exited `0` and ended with `Strict validation passed for selected suites.`

A scoped secret scan over the touched WordPress harness/suite/doc/result paths returned no real secrets; the remaining matches were expected environment variable names, default local test-password plumbing, manifest path text containing `token`, and result fields describing the `hardcoded_secrets` gate.

Latest validation after the MCP Adapter runtime slice and documentation update:

```bash
python3 -m pytest evals/harness/tests/test_wordpress_runtime_smoke.py -q
# 30 passed
```

```bash
python3 -m pytest evals/harness/tests/test_invoke_claude_command.py evals/harness/tests/test_wordpress_runtime_smoke.py evals/harness/tests/test_wordpress_artifact_oracle.py evals/harness/tests/test_wordpress_executor_packet_oracle.py evals/harness/tests/test_wordpress_exact_api_contract.py evals/harness/tests/test_wordpress_executor_artifact_certifier.py evals/harness/tests/test_wordpress_packet_materializer.py evals/harness/tests/test_wordpress_skill_output_contract.py evals/harness/tests/test_answer_key_score.py evals/harness/tests/test_pairwise_pilot.py evals/harness/tests/test_wordpress_candidate_pilot_generation.py -q
# 121 passed
```

Also re-ran syntax checks, WordPress Exact API validation, agent frontmatter
validation, strict selected WordPress suite validation, manifest generation and
verification, `git diff --check`, and the same scoped secret scan. All passed;
the strict suite validator still prints known repo-wide non-strict reports but
exits `0` with `Strict validation passed for selected suites.`

## Remaining Negative Space

Still not proven:

- long-run variance reduction across repeated ChatGPT-level baseline vs skill generations;
- public `wp-meta-skills` publication/release readiness;
- credentialed third-party AI provider behavior for OpenAI, Anthropic, Google, or other external API-key providers;
- focused benchmark maturity for the remaining high-risk suites.
  `wordpress-security-critic` now has saved skill/baseline outputs and
  deterministic output-contract archives at
  `evals/results/wordpress-security-critic-saved-outputs-20260621/`; the three
  focused skill outputs passed the output contract 3/3. Deterministic
  answer-key coverage now exists at
  `evals/results/wordpress-high-risk-answer-key-20260621/`; focused skill
  outputs scored composite 0.936. Main-agent QA review now exists at
  `evals/results/wordpress-high-risk-answer-key-20260621/qa-review.md` and
  accepts the run with reservations for internal diagnostic use; independent
  semantic review is still missing. Its baseline lanes did not pass the strict
  skill-output contract. `wordpress-performance-critic`
  now also has saved
  skill/baseline outputs and deterministic output-contract archives at
  `evals/results/wordpress-performance-critic-saved-outputs-20260621/`; the
  three focused skill outputs passed the output contract 3/3, and the legacy
  smoke skill output also passed. Deterministic answer-key coverage exists in
  the shared high-risk answer-key run; focused skill outputs tied
  `baseline-zero-shot` on lexical composite at 0.844, with higher API coverage
  but lower recall. Main-agent QA review now exists and rejects any
  performance-superiority claim from this run. Follow-up inspection of the
  `query-cache-pressure-v1` recall miss found one semantic scorer miss around
  measurement language and one real archived-output gap around the custom-table
  scale evidence boundary; the performance critic prompt was amended for future
  generations without changing archived scores. Scoped semantic annotation now
  exists at
  `evals/results/wordpress-high-risk-answer-key-20260621/performance-query-cache-semantic-annotation.md`
  and records the archived skill output as semantically `3/4` on must-detect
  items, with the custom-table scale-evidence boundary still missing.
  Regenerated post-repair evidence now exists at
  `evals/results/wordpress-performance-critic-query-cache-regenerated-20260621/`;
  the single regenerated `query-cache-pressure-v1` skill output passed the
  output contract 1/1. Deterministic answer-key coverage for that regenerated
  output exists at
  `evals/results/wordpress-performance-critic-query-cache-regenerated-answer-key-20260621/`
  and scored recall 1.000, API coverage 0.700, specificity 1.000, and
  composite 0.900 for this one fixture. This proves the amended prompt can
  produce the repaired boundary language on the focused fixture; it does not
  prove baseline superiority, long-run variance reduction, or independent
  semantic review. Full focused post-repair regeneration now exists at
  `evals/results/wordpress-performance-critic-regenerated-focused-20260621/`;
  generation passed 9/9 across `skill`, `baseline-zero-shot`, and
  `baseline-few-shot`, focused skill outputs passed the output contract 3/3,
  and baseline lanes remained 0/6 on the strict skill-output contract.
  Deterministic answer-key coverage for the regenerated focused run exists at
  `evals/results/wordpress-performance-critic-regenerated-focused-answer-key-20260621/`;
  condition composites were skill 0.915, baseline-zero-shot 0.845, and
  baseline-few-shot 0.862. Independent semantic review is still missing.
  Its baseline lanes did not pass the strict skill-output contract. The
  `wordpress-planner.migration` now also has saved skill/baseline outputs and
  deterministic output-contract archives at
  `evals/results/wordpress-planner-migration-saved-outputs-20260621/`; the
  three focused skill outputs passed the output contract 3/3, and the legacy
  smoke skill output also passed. Deterministic answer-key coverage exists in
  the shared high-risk answer-key run; focused skill outputs scored composite
  0.954. Main-agent QA review now exists and accepts the run with reservations
  for internal diagnostic use; independent semantic review is still missing.
  Its baseline lanes did not pass the strict skill-output contract. The
  `wordpress-blueprint-executor` now has focused saved executor packets and
  deterministic static certification archives at
  `evals/results/wordpress-blueprint-executor-static-cert-20260621/`; the
  three focused packets passed packet contract, materialization, and static
  `blueprint.json` artifact certification 3/3. Launch-readiness preflight now
  exists at
  `evals/results/wordpress-blueprint-executor-launch-preflight-20260621/` and
  is blocked because the generated Blueprints reference VFS plugin/theme ZIP
  payloads that are absent from committed evidence. A separate
  `self-contained-plugin-launch-v1` packet now exists and passed static
  certification at
  `evals/results/wordpress-blueprint-executor-self-contained-static-cert-20260621/`,
  launch-readiness preflight at
  `evals/results/wordpress-blueprint-executor-self-contained-launch-preflight-20260621/`,
  and one browser-observed Playground smoke at
  `evals/results/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/`.
  The smoke reached
  `/wp-admin/admin.php?page=acme-inline-blueprint-smoke` and found
  `Inline Blueprint Smoke Ready`; it recorded that Playground loaded WordPress
  `7.0` while the Blueprint requested `latest`. Main-agent QA review now exists
  at
  `evals/results/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/qa-review.md`
  and accepts the smoke as narrow internal runtime evidence with reservations;
  independent QA/test-critic review and VFS-backed packet launch proof remain
  open.

Current proven runtime lanes now include repaired plugin Abilities execution,
generated plugin PHPUnit, generated block build/editor/frontend render,
generated block Interactivity behavior, generated block deprecation migration,
generated MCP Adapter discovery/execution, and generated AI Client provider-call
behavior through a deterministic no-auth provider. Individual scorecards still
keep artifact-local negative space; for example, the generated MCP Adapter proof
is not itself a PHPUnit, browser/editor, or AI Client proof.

High-risk eval maturation plan:
`wordpress-skills/docs/high-risk-eval-maturation-plan-2026-06-21.md`. Treat it
as the map for future evidence work, not as completed evidence for PR #11.

## Recommended Next Slice

Next context should choose between publication logistics and the remaining
measurement gaps. Do not reopen the old frontier review-quality comparison as
the default target.

Concrete options:

1. Review PR #11 and decide whether to merge the clean monorepo recovery
   branch.
2. Review the private `wp-meta-skills` clean-import staging repo, then decide
   when to approve public visibility.
3. Get maintainer review for the standalone metadata and documented
   clean-import history strategy.
4. Review and approve or amend `CUTOVER.md` so `wp-meta-skills` becomes the
   source of truth after public release, with no ambiguous two-repo ownership.
5. Publish selected full result archives or convert the evidence manifest to
   public artifact URLs.
6. Continue maturing the remaining high-risk eval suites using
   `wordpress-skills/docs/high-risk-eval-maturation-plan-2026-06-21.md` if PR
   or release claims need those surfaces. For `wordpress-performance-critic`,
   one regenerated `query-cache-pressure-v1` skill output and a full focused
   post-repair regeneration now exist. The regenerated focused run has higher
   deterministic composite and API coverage for the skill lane, but independent
   review is still required before benchmark claims. For
   `wordpress-security-critic` and
   `wordpress-planner.migration`, the next benchmark-hardening slice is
   independent QA/test-critic review or manual semantic annotation before any
   public benchmark claim. For
  `wordpress-blueprint-executor`, the next honest measurement slice is
  independent/owner review of the self-contained Playground smoke, or supplying
  the missing VFS payloads only if the VFS-backed packets need runtime claims.
7. Run a new measurement pass for long-run variance, not for frontier-model
   review-quality superiority.
8. Scope credentialed third-party AI-provider testing only if that boundary is
   needed, with no secrets committed.

Why:

- The generated Abilities proof already exercises `wp_get_ability()` in
  WordPress `7.0`, and the generated MCP Adapter proof now exercises the same
  kind of public ability through `wp mcp-adapter serve`, `tools/list`,
  `mcp-adapter-discover-abilities`, and `mcp-adapter-execute-ability`.
- The generated AI Client proof now crosses the provider boundary with
  `wp_ai_client_prompt()->using_model_preference()->generate_text()`, confirms
  provider registration/configuration, confirms connector registration, and
  records deterministic provider output.
- The block-executor runtime gaps are no longer the next bottleneck:
  Interactivity and deprecation now both have generated-artifact runtime proofs.
- The MCP Adapter pass surfaced upstream PHP deprecation notices from the
  adapter internals under the local PHP runtime; the command still returned
  `0` and passed, but those warnings should stay visible as adapter/runtime
  risk rather than silently becoming release-readiness proof.
- The AI Client proof is not a credentialed OpenAI/Anthropic/Google provider
  proof. If that boundary becomes important, scope it as a separate
  credentials-aware test with no secrets committed.
- Security critic, performance critic, migration planner, and Blueprint
  executor have moved from one-fixture smoke to focused fixture scaffolding.
  Security critic, performance critic, and migration planner additionally have
  saved skill/baseline outputs and deterministic output-contract results; the
  three focused skill outputs passed the output contract 3/3 in all three
  suites. They now also have deterministic lexical answer-key coverage at
  `evals/results/wordpress-high-risk-answer-key-20260621/`, which is useful
  signal and now has a main-agent QA review accepting it with reservations, but
  it is still not semantic benchmark review. Performance query/cache now also
  has scoped main-agent semantic annotation over the archived output; this
  reduces ambiguity around the lexical recall miss but does not replace
  independent review or regenerated evidence. Blueprint executor also has static
  packet/materializer/artifact certification for the three VFS-backed focused
  packets plus launch-readiness preflight proving those launch claims are
  blocked on missing VFS payloads. It now has one self-contained packet with
  static certification, launch-readiness preflight, and a browser-observed
  Playground smoke plus a main-agent QA review accepting that smoke with
  reservations. These states are still not benchmark evidence until independent
  review exists, and VFS-backed runtime claims remain blocked until their
  payloads and launch evidence exist. Do not convert any of these states into
  benchmark claims without the
  maturation gates in the high-risk eval plan.
- The standalone staging repository now proves the package can validate in its own
  GitHub repository. It is not yet public release approval.

Current references already used in this handoff:

- WordPress Interactivity API reference: https://developer.wordpress.org/block-editor/reference-guides/interactivity-api/
- Interactivity directives and store: https://developer.wordpress.org/block-editor/reference-guides/interactivity-api/directives-and-store/
- Block metadata reference: https://developer.wordpress.org/block-editor/reference-guides/block-api/block-metadata/
- Block deprecation reference: https://developer.wordpress.org/block-editor/reference-guides/block-api/block-deprecation/
- WordPress MCP Adapter developer post: https://developer.wordpress.org/news/2026/02/from-abilities-to-ai-agents-introducing-the-wordpress-mcp-adapter/
- WordPress AI Client dev note: https://make.wordpress.org/core/2026/03/24/introducing-the-ai-client-in-wordpress-7-0/
- WordPress Connectors API dev note: https://make.wordpress.org/core/2026/03/18/introducing-the-connectors-api-in-wordpress-7-0/

Suggested implementation shape:

1. Re-run the focused and broader validation gates after any doc or harness edit.
2. Keep the generated AI Client packet and result directories intact as evidence.
3. Update downstream status docs to separate no-auth deterministic provider proof
   from credentialed third-party provider behavior.
4. If a next execution slice is needed, choose between public
   `wp-meta-skills` publication logistics, Blueprint executor Playground
   launch evidence, long-run variance measurement, or credentialed-provider
   proof.
5. Keep the MCP Adapter PHP deprecation notices visible as upstream adapter
   runtime risk, not as generated-plugin failure.

## Progress After 2026-06-21 Resume

The generated block Interactivity API oracle is now implemented and proven:

- Packet: `evals/suites/wordpress-block-executor/examples/interactivity-wordpress-v1.materializable-packet.md`
- Static certification result: `evals/results/wordpress-skill-candidate-eval/generated-block-interactivity-artifact-cert-20260621/`
- Full runtime result: `evals/results/wordpress-skill-candidate-eval/generated-block-interactivity-full-profile-20260621/`

Evidence from the full-profile scorecard:

- Status: `pass`
- Narrow gate: `pass`
- Full plugin runtime profile: `pass`
- Block registration smoke: `pass`
- Block build smoke: `pass`
- Interactivity smoke: `pass`
- Editor/browser smoke: `pass`
- Provisioned full profile: `true`

The runtime harness now supports `--interactivity-smoke`, checks static Interactivity surfaces, registers built block metadata when `npm run build` emits `build/block.json`, and drives Playwright through editor insertion, publish, frontend render, and a click/state assertion. The passed proof changed `context.count` from `0` to `1` with no page or console errors.

The generated block deprecation oracle is also now implemented and proven:

- Packet: `evals/suites/wordpress-block-executor/examples/deprecation-wordpress-v1.materializable-packet.md`
- Static certification result: `evals/results/wordpress-skill-candidate-eval/generated-block-deprecation-artifact-cert-20260621/`
- Full runtime result: `evals/results/wordpress-skill-candidate-eval/generated-block-deprecation-full-profile-20260621/`

Evidence from the full-profile scorecard:

- Status: `pass`
- Narrow gate: `pass`
- Full plugin runtime profile: `pass`
- Block registration smoke: `pass`
- Block build smoke: `pass`
- Block deprecation smoke: `pass`
- Editor/browser smoke: `pass`
- Provisioned full profile: `true`

The runtime harness now supports `--deprecation-smoke`, checks the generated
artifact's static deprecation surfaces, creates a post from the legacy serialized
fixture, opens the editor, verifies the exact migrated `content` attribute,
serializes the current block tree, saves current markup, and proves frontend
text `Runtime block smoke: Legacy runtime smoke` with no page or console errors.

Intermediate negative space at this point in the sequence:

- AI Client proof had not landed yet at this intermediate point;
- long-run variance reduction across repeated ChatGPT-level baseline vs skill generations is still not proven;
- standalone public `wp-meta-skills` extraction readiness had not landed yet at this intermediate point.

The generated MCP Adapter oracle is now implemented and proven:

- Packet: `evals/suites/wordpress-plugin-executor/examples/mcp-adapter-wordpress-v1.materializable-packet.md`
- Static certification result: `evals/results/wordpress-skill-candidate-eval/generated-mcp-adapter-artifact-cert-20260621/`
- Full runtime result: `evals/results/wordpress-skill-candidate-eval/generated-mcp-adapter-full-profile-20260621/`

Evidence from the full-profile scorecard:

- Status: `pass`
- Narrow gate: `pass`
- Full plugin runtime profile: `pass`
- Plugin activation: `0`
- Abilities smoke: `pass`
- MCP Adapter smoke: `pass`
- Provisioned full profile: `true`

The runtime harness now supports `--mcp-adapter-smoke`, installs the current
MCP Adapter plugin zip in disposable `wp-env`, lists the default adapter server,
calls `tools/list` over `wp mcp-adapter serve`, discovers the generated
`acme-mcp-smoke/get-runtime-marker` ability, and executes it through
`mcp-adapter-execute-ability` with marker output `Runtime MCP smoke`. The run
also passed WPCS/PHPCS and Plugin Check for the generated plugin. The adapter
execution emitted upstream PHP deprecation notices from MCP Adapter internals
under the local PHP runtime, but the adapter command exited `0` and the oracle
passed.

The generated AI Client provider-call oracle is now implemented and proven:

- Packet: `evals/suites/wordpress-plugin-executor/examples/ai-client-provider-wordpress-v1.materializable-packet.md`
- Static certification result: `evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-artifact-cert-20260621/`
- Full runtime result: `evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-full-profile-20260621/`

Evidence from the full-profile scorecard:

- Status: `pass`
- Narrow gate: `pass`
- Full plugin runtime profile: `pass`
- Plugin activation: `0`
- AI Client smoke: `pass`
- Provisioned full profile: `true`

The runtime harness now supports `--ai-client-smoke`, checks static AI Client
provider surfaces, activates a generated deterministic no-auth provider in
WordPress `7.0`, calls `wp --user=admin eval`, verifies
`wp_ai_client_prompt()` and `WordPress\AiClient\AiClient::defaultRegistry()`,
confirms provider registration/configuration, confirms connector registration,
invokes `AcmeAIClientSmoke\generate_summary()`, and records output
`AI Client smoke: deterministic provider response`. The run also passed
WPCS/PHPCS and Plugin Check for the generated plugin.

Updated negative space after the AI Client proof:

- long-run variance reduction across repeated ChatGPT-level baseline vs skill generations is still not proven;
- public `wp-meta-skills` publication/release readiness is still not proven;
- credentialed third-party AI provider behavior is still not proven.

The standalone `wp-meta-skills` extraction dry run is now implemented and
validated:

- Readiness doc: `wordpress-skills/docs/standalone-extraction-readiness-2026-06-21.md`
- Dry-run package: `/tmp/wp-meta-skills-extraction-20260621-233205`
- Passed in the extracted package: manifest generation/verification, agent
  frontmatter validation, WordPress Exact API validation, strict selected
  WordPress eval-suite validation, and 85 extracted-package harness tests.
- Scoped extracted-package secret scan found no real credentials; the only
  literal-assignment match was the documented
  `ANTHROPIC_API_KEY="<anthropic-api-key>"` placeholder in
  `evals/harness/README.md`.

The extraction dry run exposed and fixed a real path coupling bug: the exact API
contract validator plus candidate/pairwise pilot harnesses still assumed
`wordpress-skills/.claude`. They now prefer the monorepo layout when present and
fall back to root `.claude` in an extracted package.

The reproducible pruned package builder is now implemented and validated:

- Builder: `scripts/build-wp-meta-skills-package.py`
- Pruned package: `/tmp/wp-meta-skills-pruned-20260621`
- Command: `python3 scripts/build-wp-meta-skills-package.py --output /tmp/wp-meta-skills-pruned-20260621 --force --generate-manifest`
- Package footprint: 346 files, 2.3M, 18 harness files, and 12 harness test files.
- Root metadata included: `LICENSE` with Apache-2.0 text, `CHANGELOG.md`,
  `SECURITY.md`, `CONTRIBUTING.md`, `CUTOVER.md`, `EVIDENCE.md`,
  `PROVENANCE.md`, and `PUBLICATION-CHECKLIST.md`.
- Standalone CI workflow included at `.github/workflows/validate.yml`.
- Curated evidence bundle included under
  `evidence/wordpress-skill-candidate-eval/` with six selected runtime proof
  scorecards and six matching runtime JSON files.
- Passed in the pruned package: manifest verification, agent frontmatter
  validation, WordPress Exact API validation, strict selected WordPress
  eval-suite validation, and the 125-test WordPress harness bundle.
- Scoped pruned-package secret scan found no real credentials; the only
  literal-assignment matches were copies of the documented
  `ANTHROPIC_API_KEY="<anthropic-api-key>"` placeholder.
- Committed-history split probe passed with
  `git subtree split --prefix=wordpress-skills HEAD`, returning
  `ef7e00b2f848ee57f2f008714855fe440b78d892`.
- History strategy is now documented for the first public draft: clean import
  the generated package with `PROVENANCE.md` preserved. A raw
  `wordpress-skills` subtree split is explicitly not enough for the generated
  package because it omits root harness, script, installer, and evidence inputs.
- Local clean-import rehearsal is documented at
  `wordpress-skills/docs/public-repo-rehearsal-2026-06-21.md`; it initialized a
  standalone `main` repo from the generated package and reran the standalone
  validation gates successfully.
- Local source commits are now in place on the clean WordPress recovery branch.
  Use `git log origin/main..HEAD` for the live local count; the substantive
  recovery stack before this handoff update includes:
  - `19fab3e chore: add WordPress standalone release packaging`
  - `bab24bb test: add WordPress oracle validation gates`
  - `ab718e6 docs: update WordPress recovery handoff state`
  - `3a46a0c docs: correct WordPress recovery handoff state`
- The clean branch was replayed from `origin/main` specifically to avoid mixing
  the WordPress recovery stack with the earlier stem-cell branch history.
- The clean branch is pushed as PR #11:
  https://github.com/zivtech/zivtech-meta-skills/pull/11. The PR is ready for
  review, but `gh pr view 11` reports `reviewDecision=REVIEW_REQUIRED` and
  `mergeStateStatus=BLOCKED`.
- Post-commit standalone package validation passed from
  `/tmp/wp-meta-skills-pruned-20260621`: manifest verification, agent
  frontmatter validation, WordPress Exact API validation, strict selected
  WordPress suite validation, and the 125-test WordPress harness bundle.

Remaining publication boundary:

- PR #11 exists for the clean monorepo recovery branch and is ready for review,
  but it has not been approved or merged into `main`;
- review has been requested from `grndlvl`, `misterjones`, and `pmzivtech`, but
  no approval has landed yet;
- monorepo PR package-validation has a live passing GitHub Actions result, but
  this only validates the generated package from the monorepo PR branch;
- standalone staging repository exists at
  https://github.com/zivtech/wp-meta-skills and live standalone Actions have
  passed on the current staging head tracked in issue #1;
- the standalone repo has not been approved for public visibility;
- public owner review of the standalone metadata and `CUTOVER.md` has not
  happened;
- maintainer approval of the documented clean-import history strategy, or a
  verified path-aware history-preserving alternative, has not happened;
- public-release approval is now tracked in
  public issue tracker;
- selected lightweight evidence files are bundled, but full result archives are
  not published or converted to public URLs.

## Subagent Notes

Completed subagent evidence used:

- Maxwell recommended finishing the generated plugin PHPUnit proof first. That is now done.
- Descartes audited baseline routing and confirmed the right rule: preserve historical Claude/Sonnet results, but make new baseline lanes provider-aware and Codex/ChatGPT-level by default.

Two later explorers were spawned for block interactivity and MCP/AI Client feasibility but were closed before completion when this handoff decision was made. Do not rely on them.

One older agent close attempt for `019ee643-7761-7932-81eb-4e207bcf0e68` aborted during turn interruption; check subagent state at the start of the next context if needed.

## First Commands For Next Context

Start with single-purpose commands:

```bash
git branch --show-current
git status --short
sed -n '1,220p' wordpress-skills/docs/goal-handoff-2026-06-21.md
sed -n '1,180p' evals/results/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/scorecard.md
sed -n '1,220p' evals/harness/run_wordpress_blueprint_playground_smoke.js
sed -n '1,220p' evals/harness/run_wordpress_editor_smoke.js
sed -n '1,220p' evals/harness/run_wordpress_runtime_smoke.py
```

Then inspect the current MCP and AI Client proofs only if choosing another
runtime measurement target:

```bash
sed -n '1,220p' evals/suites/wordpress-plugin-executor/examples/mcp-adapter-wordpress-v1.materializable-packet.md
sed -n '1,160p' evals/results/wordpress-skill-candidate-eval/generated-mcp-adapter-full-profile-20260621/scorecard.md
sed -n '1,220p' evals/results/wordpress-skill-candidate-eval/generated-mcp-adapter-full-profile-20260621/runtime-smoke.json
sed -n '1,220p' evals/suites/wordpress-plugin-executor/examples/ai-client-provider-wordpress-v1.materializable-packet.md
sed -n '1,160p' evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-full-profile-20260621/scorecard.md
sed -n '1,220p' evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-full-profile-20260621/runtime-smoke.json
```

Do not start by rerunning the old frontier review-quality comparison. That path already produced a directional null and is not the next useful measurement target.
