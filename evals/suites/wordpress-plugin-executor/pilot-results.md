# Pilot Results

Status: smoke fixture repaired, static golden-packet certification executed, repeated historical Claude skill outputs certified through `php-lint`, isolated ChatGPT-level baseline generation added, a modern Abilities/AI surface fixture proved through generated-artifact `wp-env` ability execution, and generated plugin PHPUnit, MCP Adapter, and AI Client packets proved through the full provisioned plugin profile. The first deterministic evaluator-feedback repair loop repaired the Abilities artifact's WPCS-shape failure with `gpt-5.5` and passed the full provisioned plugin profile.

Evidence:

- Fixture: `evals/suites/wordpress-plugin-executor/fixtures/smoke-wordpress-v1.md`
- Golden packet: `evals/suites/wordpress-plugin-executor/examples/smoke-wordpress-v1.materializable-packet.md`
- Modern-surface fixture: `evals/suites/wordpress-plugin-executor/fixtures/abilities-ai-surface-v1.md`
- Modern-surface golden packet: `evals/suites/wordpress-plugin-executor/examples/abilities-ai-surface-v1.materializable-packet.md`
- PHPUnit golden packet: `evals/suites/wordpress-plugin-executor/examples/phpunit-wordpress-v1.materializable-packet.md`
- Static golden-packet certification: `evals/results/wordpress-skill-candidate-eval/plugin-executor-static-cert-20260620/scorecard.md`
- Modern-surface golden-packet certification: `evals/results/wordpress-skill-candidate-eval/plugin-executor-abilities-ai-static-cert-20260620/scorecard.md`
- Live executor output: `evals/results/wordpress-plugin-executor-live-cert-20260620c/raw/wordpress-plugin-executor/skill/smoke-wordpress-v1.md`
- Live output certification: `evals/results/wordpress-skill-candidate-eval/plugin-executor-live-cert-20260620/scorecard.md`
- Repeated live executor output: `evals/results/wordpress-plugin-executor-live-cert-20260620d/raw/wordpress-plugin-executor/skill/smoke-wordpress-v1.md`
- Repeated live output certification: `evals/results/wordpress-skill-candidate-eval/plugin-executor-live-cert-20260620d/scorecard.md`
- Contract-failure specimen: `evals/results/wordpress-plugin-executor-live-cert-20260620e/raw/wordpress-plugin-executor/skill/smoke-wordpress-v1.md`
- Repaired repeated live executor output: `evals/results/wordpress-plugin-executor-live-cert-20260620f/raw/wordpress-plugin-executor/skill/smoke-wordpress-v1.md`
- Repaired repeated live output certification: `evals/results/wordpress-skill-candidate-eval/plugin-executor-live-cert-20260620f/scorecard.md`
- Modern-surface live executor output: `evals/results/wordpress-plugin-executor-abilities-ai-live-cert-20260620a/raw/wordpress-plugin-executor/skill/abilities-ai-surface-v1.md`
- Modern-surface live output certification: `evals/results/wordpress-skill-candidate-eval/plugin-executor-abilities-ai-live-cert-20260620a/scorecard.md`
- Hardened modern-surface live executor output: `evals/results/wordpress-plugin-executor-abilities-ai-live-cert-20260620b/raw/wordpress-plugin-executor/skill/abilities-ai-surface-v1.md`
- Hardened modern-surface live output certification: `evals/results/wordpress-skill-candidate-eval/plugin-executor-abilities-ai-live-cert-20260620b/scorecard.md`
- Superseding WPCS-shape failure certification: `evals/results/wordpress-skill-candidate-eval/plugin-executor-abilities-ai-wpcs-shape-fail-20260620/scorecard.md`
- Superseding WPCS-shape repair prompt: `evals/results/wordpress-skill-candidate-eval/plugin-executor-abilities-ai-wpcs-shape-fail-20260620/repair-prompt.md`
- ChatGPT-level WPCS-shape repair output: `evals/results/wordpress-plugin-executor-abilities-ai-repair-loop-20260620c/raw/wordpress-plugin-executor/repair/abilities-ai-surface-v1.md`
- ChatGPT-level WPCS-shape repair certification: `evals/results/wordpress-skill-candidate-eval/plugin-executor-abilities-ai-repair-loop-20260620c/scorecard.md`
- Generated modern-surface runtime ability smoke: `evals/results/wordpress-skill-candidate-eval/generated-abilities-ai-runtime-hardened-20260620b/scorecard.md`
- Generated modern-surface full runtime profile failure: `evals/results/wordpress-skill-candidate-eval/generated-abilities-ai-runtime-full-profile-20260620b/scorecard.md`
- Generated modern-surface repair-loop full runtime profile pass: `evals/results/wordpress-skill-candidate-eval/generated-abilities-ai-repair-loop-full-profile-20260620c/scorecard.md`
- Generated PHPUnit packet certification: `evals/results/wordpress-skill-candidate-eval/generated-plugin-phpunit-artifact-cert-20260620/scorecard.md`
- Generated PHPUnit full runtime profile pass: `evals/results/wordpress-skill-candidate-eval/generated-plugin-phpunit-full-profile-20260620/scorecard.md`
- Generated AI Client provider packet certification: `evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-artifact-cert-20260621/scorecard.md`
- Generated AI Client provider full runtime profile pass: `evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-full-profile-20260621/scorecard.md`
- Isolated ChatGPT-level baseline smoke: `evals/results/wordpress-plugin-executor-chatgpt-baseline-isolated-smoke-20260620c/raw/wordpress-plugin-executor/baseline-zero-shot/smoke-wordpress-v1.md`
- Isolated ChatGPT-level baseline metadata: `evals/results/wordpress-plugin-executor-chatgpt-baseline-isolated-smoke-20260620c/raw/wordpress-plugin-executor/baseline-zero-shot/smoke-wordpress-v1.metadata.json`
- Isolated ChatGPT-level baseline certification: `evals/results/wordpress-skill-candidate-eval/plugin-executor-chatgpt-baseline-zero-shot-smoke-20260620c/scorecard.md`
- Golden-packet command: `python3 evals/harness/certify_wordpress_executor_artifact.py --executor plugin --packet evals/suites/wordpress-plugin-executor/examples/smoke-wordpress-v1.materializable-packet.md --out-dir evals/results/wordpress-skill-candidate-eval/plugin-executor-static-cert-20260620/generated-plugin --result-dir evals/results/wordpress-skill-candidate-eval/plugin-executor-static-cert-20260620 --overwrite`
- Live-output command: `python3 evals/harness/certify_wordpress_executor_artifact.py --executor plugin --packet evals/results/wordpress-plugin-executor-live-cert-20260620c/raw/wordpress-plugin-executor/skill/smoke-wordpress-v1.md --out-dir evals/results/wordpress-skill-candidate-eval/plugin-executor-live-cert-20260620/generated-plugin --result-dir evals/results/wordpress-skill-candidate-eval/plugin-executor-live-cert-20260620 --require-tool php-lint --overwrite`

Static golden result: packet gate `pass`, materialization gate `pass`, static artifact gate `pass`.

Modern-surface golden result: packet gate `pass`, materialization gate `pass`, static artifact gate `pass`, `plugin_ai_surface_heuristics` `pass`, and `php -l` `pass`. The fixture exercises `wp_register_ability()`, `wp_abilities_api_init`, ability schemas, `permission_callback`, guarded `wp_ai_client_prompt()`, `wp_connectors_init`, and MCP Adapter discovery/execution as a verification boundary.

Historical Claude skill-generation result: after default invocation timed out, the suite was configured for `sonnet` plus `low` effort. Three bounded live invocations passed the saved-output contract, packet-only gate, materialization gate, static artifact gate, static modern-AI surface heuristic, and `php -l`:

- `wordpress-plugin-executor-live-cert-20260620c`: 134.49s.
- `wordpress-plugin-executor-live-cert-20260620d`: 176.95s.
- `wordpress-plugin-executor-live-cert-20260620f`: 60.12s.

One intermediate repeat, `wordpress-plugin-executor-live-cert-20260620e`, returned in 109.55s but failed correctly: it omitted explicit negative-space language and used a directory-tree-style `## Generated File Map` without exact relative path tokens. The executor contract and fixture now require literal relative file paths and an explicit "not claimed" verification boundary.

Modern-surface live generation result, superseded by the hardened gate: `wordpress-plugin-executor-abilities-ai-live-cert-20260620a` returned in 203.55s and originally passed the then-current saved-output contract, packet-only gate, materialization gate, static artifact gate, `plugin_ai_surface_heuristics`, and `php -l`. After the Abilities API heuristic was hardened to require `label`, `description`, and `category`, the materialized `20260620a` artifact fails with missing `label` and `category`; this is a real caught defect, not a judge artifact.

Hardened modern-surface result: `wordpress-plugin-executor-abilities-ai-live-cert-20260620b` returned in 293.93s and passed saved-output, packet, materialization, hardened static AI-surface heuristics, and `php -l` under the then-current gate. Its generated plugin also passed `wp-env` on WordPress `7.0`, plugin activation, `wp core version`, and a `wp_get_ability()` execution smoke returning `{"post_id":4,"title":"Runtime Ability Smoke","summary":"Runtime excerpt summary."}`. The provisioned full profile then failed WPCS/PHPCS while Plugin Check passed; WPCS reported missing `@package`, short array syntax, double-arrow alignment, and a missing function parameter doc. The current static artifact gate now catches the same high-signal failure earlier: `plugin-executor-abilities-ai-wpcs-shape-fail-20260620` passes packet and materialization but fails `php_wpcs_shape_heuristics` on missing `@package` and short arrays. The failed cert now emits `repair-prompt.md` so the next executor revision can consume the oracle feedback directly.

Repair-loop result: `wordpress-plugin-executor-abilities-ai-repair-loop-20260620c` used the generated `repair-prompt.md` with local Codex CLI `gpt-5.5`, `model_reasoning_effort=medium`, read-only sandboxing, ignored user config/rules, and prompt-only output capture. The model added a file-level `@package`, converted PHP short arrays to `array()`, filled the missing return/docblock shape, and kept the required executor packet headings. Static certification passed packet contract, materialization, `php_wpcs_shape_heuristics`, static security/AI-surface heuristics, and `php-lint`. The full runtime profile `generated-abilities-ai-repair-loop-full-profile-20260620c` then passed WordPress `7.0` `wp-env`, plugin activation, `wp_get_ability()` execution with the runtime summary output, WPCS/PHPCS, and Plugin Check. This is the first concrete evidence that the WordPress executor skill value can live in deterministic gate -> repair prompt -> re-certify loops rather than generic frontier-review judging.

ChatGPT-level baseline result: `wordpress-plugin-executor-chatgpt-baseline-isolated-smoke-20260620c` used local Codex CLI with `gpt-5.5`, `model_policy: newest-chatgpt-level-at-run-time`, temp cwd isolation, `--ignore-user-config`, `--ignore-rules`, and prompt-only instructions. The zero-shot baseline returned in 43.1s and passed packet, materialization, current static artifact including `php_wpcs_shape_heuristics`, and `php -l`. This means the simple fixture is not discriminative for skill advantage at the deterministic-gate layer; future comparisons need harder fixtures or runtime/WPCS/variance gates.

Generated PHPUnit result: `generated-plugin-phpunit-full-profile-20260620` copied the materialized `acme-runtime-tested` plugin into disposable `wp-env`, installed artifact-local PHPUnit with Composer, activated the plugin in WordPress `7.0`, passed `phpunit` (`3 tests, 3 assertions`), and passed WPCS/PHPCS plus Plugin Check. This proves the generated plugin PHPUnit lane can be evaluated without hand-reconstructing files from prose.

Generated MCP Adapter result: `generated-mcp-adapter-full-profile-20260621` copied the materialized `acme-mcp-smoke` plugin into disposable `wp-env`, installed the WordPress MCP Adapter plugin zip, listed the default adapter server, called `tools/list` through `wp mcp-adapter serve`, discovered `acme-mcp-smoke/get-runtime-marker`, executed it through `mcp-adapter-execute-ability`, and passed WPCS/PHPCS plus Plugin Check. The adapter command emitted upstream PHP deprecation notices under the local PHP runtime but exited `0`.

Generated AI Client provider result: `generated-ai-client-provider-full-profile-20260621` copied the materialized `acme-ai-client-smoke` plugin into disposable `wp-env`, activated a deterministic no-auth AI Client provider in WordPress `7.0`, confirmed `wp_ai_client_prompt()`, provider registration/configuration, connector registration, and expected generated output `AI Client smoke: deterministic provider response`, then passed WPCS/PHPCS plus Plugin Check.

Negative space: this certifies a small repeated historical Claude skill-output sample, one simple saved golden packet, one modern generated artifact through Abilities execution, one superseding static WPCS-shape failure, one successful ChatGPT-level repair-loop pass, one isolated ChatGPT-level baseline smoke, one generated plugin PHPUnit full-profile proof, one generated MCP Adapter runtime proof, and one deterministic no-auth AI Client provider proof. It does not prove broad model quality, long-run variance, browser/editor behavior, credentialed external AI provider behavior, or release readiness. This suite remains experimental until stronger runtime gates and a `test-critic` review are run where decision-grade claims are needed.
