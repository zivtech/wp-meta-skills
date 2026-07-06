# WordPress Planner -> Executor -> Critic Lifecycle

## Default Flow

1. `/wordpress-planner` or focused planner creates the implementation plan.
2. Deterministic skill-output oracle validates the saved planner response before execution.
3. Focused executor generates an artifact packet from the approved plan.
4. Deterministic packet oracle validates saved plugin/block/blueprint executor output when that lane applies.
5. Packet materializer converts plugin/block/Blueprint packets into generated files when that lane applies.
6. Deterministic artifact oracle validates generated plugin/block/theme/Blueprint files.
7. Focused critic reviews the plan and generated artifact.
8. Deterministic skill-output oracle validates the saved critic response before model-judge scoring or publication.
9. Executor revises only after critic findings are resolved or accepted as explicit tradeoffs.

## Flow Matrix

| Work Type | Plan | Execute | Review |
|---|---|---|---|
| Plugin | `/wordpress-planner.plugin` | `/wordpress-plugin-executor` | `/wordpress-security-critic` plus `/wordpress-critic` |
| Block | `/wordpress-planner.block` | `/wordpress-block-executor` | `/wordpress-critic` plus `/wordpress-performance-critic` when dynamic |
| Theme | `/wordpress-planner.theme` | `/wordpress-theme-executor` | `/wordpress-theme-critic` |
| Blueprint/repro | `/wordpress-planner` | `/wordpress-blueprint-executor` | `/wordpress-critic` |
| Content model | `/wordpress-planner.content-model` | `/wordpress-plugin-executor` or `/wordpress-theme-executor` | `/wordpress-critic` |
| Migration | `/wordpress-planner.migration` | implementation-specific packet | `/wordpress-critic` |

## Deterministic Executor Packet Gate

Before spending critic or judge time on saved executor packets, run the cheap local packet oracle:

```bash
python3 evals/harness/validate_wordpress_executor_packet.py --executor plugin --packet <candidate-output.md>
python3 evals/harness/validate_wordpress_executor_packet.py --executor block --packet <candidate-output.md>
python3 evals/harness/validate_wordpress_executor_packet.py --executor blueprint --packet <candidate-output.md>
```

This gate checks output headings, file maps or Blueprint JSON, exact WordPress surfaces, runnable verification oracles, safety constraints, and critic handoff. It is not a quality benchmark by itself; it prevents malformed packets from entering a more expensive review loop.

## Packet Materialization Gate

For plugin, block, and Blueprint executors, convert the saved packet into files before artifact validation:

```bash
python3 evals/harness/materialize_wordpress_executor_packet.py --executor plugin --packet <candidate-output.md> --out-dir <generated-plugin-dir>
python3 evals/harness/materialize_wordpress_executor_packet.py --executor block --packet <candidate-output.md> --out-dir <generated-block-dir>
python3 evals/harness/materialize_wordpress_executor_packet.py --executor blueprint --packet <candidate-output.md> --out-dir <generated-blueprint-dir>
```

This gate rejects non-materializable output: unsafe paths, duplicate file paths, unsupported file suffixes, missing fenced file contents, or prose between a path heading and its code fence. It proves the saved executor packet can become files without human reconstruction. It does not prove the files are correct or runnable.

For the normal inner loop, prefer the combined certifier:

```bash
python3 evals/harness/certify_wordpress_executor_artifact.py --executor plugin --packet <candidate-output.md> --out-dir <generated-plugin-dir> --result-dir <result-dir> --overwrite
python3 evals/harness/certify_wordpress_executor_artifact.py --executor block --packet <candidate-output.md> --out-dir <generated-block-dir> --result-dir <result-dir> --overwrite
python3 evals/harness/certify_wordpress_executor_artifact.py --executor blueprint --packet <candidate-output.md> --out-dir <generated-blueprint-dir> --result-dir <result-dir> --overwrite
```

This command runs the packet gate, materialization gate, and artifact gate together and writes `certification.json` plus `scorecard.md` when a result directory is supplied.

## Deterministic Skill Output Gate

For saved planner, executor, or critic responses, run the output-contract oracle:

```bash
python3 evals/harness/validate_wordpress_skill_output.py --skill wordpress-planner.plugin --output <candidate-output.md>
python3 evals/harness/validate_wordpress_skill_output.py --skill wordpress-critic --output <candidate-output.md>
```

This gate checks required headings, valid critic verdicts, exact WordPress surfaces, concrete verification terms, negative-space language, placeholder markers, and generic WordPress labels. It measures output contract discipline; it does not prove the underlying plan or review is correct.

## Deterministic Artifact Gate

After materializing generated files, run the artifact oracle:

```bash
python3 evals/harness/validate_wordpress_artifact.py --artifact-type plugin --path <generated-plugin-dir>
python3 evals/harness/validate_wordpress_artifact.py --artifact-type block --path <generated-block-dir>
python3 evals/harness/validate_wordpress_artifact.py --artifact-type theme --path <generated-theme-dir>
python3 evals/harness/validate_wordpress_artifact.py --artifact-type blueprint --path <generated-blueprint-dir>/blueprint.json
```

Use explicit runtime tools for environment-backed claims, and reserve `--profile runtime` for the full default runtime contract:

```bash
python3 evals/harness/validate_wordpress_artifact.py --artifact-type plugin --path <generated-plugin-dir> --profile runtime --require-tool phpunit
python3 evals/harness/validate_wordpress_artifact.py --artifact-type block --path <generated-block-dir> --profile runtime --require-tool wp-env --wp-env-root <wp-env-project-root>
```

Static artifact validation is useful but limited. It checks structure, JSON validity, plugin headers, safety patterns, and WordPress-specific heuristics. It does not prove WPCS, Plugin Check, wp-env, PHPUnit, editor smoke, or frontend smoke unless runtime tools are explicitly required and pass.

To prove the disposable `php-lint` plus `wp-env` runtime lane itself:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py --write --run-id wp-env-runtime-smoke-YYYYMMDD --timeout-sec 300
```

To provision and require the full disposable plugin runtime profile:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py --provision-full-profile --write --run-id wp-env-runtime-full-profile-YYYYMMDD --timeout-sec 300
```

To prove a generated plugin artifact with a PHPUnit suite, certify/materialize the packet, then run the generated plugin through the disposable runtime harness:

```bash
python3 evals/harness/certify_wordpress_executor_artifact.py --executor plugin --packet <candidate-output.md> --out-dir <generated-plugin-dir> --result-dir <result-dir> --overwrite
python3 evals/harness/run_wordpress_runtime_smoke.py --artifact-path <generated-plugin-dir>/<plugin-slug> --phpunit-smoke --provision-full-profile --write --run-id generated-plugin-phpunit-full-profile-YYYYMMDD --timeout-sec 300
```

This proves packet validation, materialization, static artifact certification, plugin activation in `wp-env`, artifact-local Composer install when `composer.json` exists, PHPUnit, WPCS/PHPCS, and Plugin Check. It does not prove browser/editor behavior, block behavior, MCP Adapter exposure, AI Client provider calls, broad WordPress integration-test coverage, or release readiness.

To prove a generated MCP-public Abilities API plugin through the WordPress MCP
Adapter, certify/materialize the packet, then run the generated plugin through
the disposable runtime harness:

```bash
python3 evals/harness/certify_wordpress_executor_artifact.py --executor plugin --packet <candidate-output.md> --out-dir <generated-plugin-dir> --result-dir <result-dir> --overwrite
python3 evals/harness/run_wordpress_runtime_smoke.py --artifact-path <generated-plugin-dir>/<plugin-slug> --ability-name vendor/ability-name --mcp-adapter-smoke --mcp-adapter-execute-args-json '{"marker":"Runtime MCP smoke"}' --mcp-adapter-expected-output "Runtime MCP smoke" --provision-full-profile --write --run-id generated-mcp-adapter-full-profile-YYYYMMDD --timeout-sec 300
```

This proves packet validation, materialization, static artifact certification,
plugin activation in `wp-env`, WordPress MCP Adapter installation, STDIO
`tools/list`, public ability discovery, public ability execution through
`mcp-adapter-execute-ability`, WPCS/PHPCS, and Plugin Check for that generated
plugin. It does not prove AI Client provider calls, browser/editor behavior,
PHPUnit behavior, broad integration-test coverage, or release readiness. The
first local proof is
`evals/results/wordpress-skill-candidate-eval/generated-mcp-adapter-full-profile-20260621/`.
That run emitted upstream MCP Adapter PHP deprecation notices under the local PHP
runtime while still exiting `0`; keep those notices visible as adapter/runtime
risk.

To prove a generated deterministic AI Client provider call, certify/materialize
the packet, then run the generated plugin through the disposable runtime harness:

```bash
python3 evals/harness/certify_wordpress_executor_artifact.py --executor plugin --packet <candidate-output.md> --out-dir <generated-plugin-dir> --result-dir <result-dir> --overwrite
python3 evals/harness/run_wordpress_runtime_smoke.py --workdir /tmp/wp-ai-client-runtime-smoke-YYYYMMDD --artifact-path <generated-plugin-dir>/<plugin-slug> --ai-client-smoke --ai-client-provider-id acme-ai-client-smoke --ai-client-model-id acme-deterministic-text --ai-client-helper-function 'AcmeAIClientSmoke\generate_summary' --ai-client-prompt "Runtime AI Client smoke" --ai-client-expected-output "AI Client smoke: deterministic provider response" --provision-full-profile --write --run-id generated-ai-client-provider-full-profile-YYYYMMDD --timeout-sec 300
```

This proves packet validation, materialization, static artifact certification,
plugin activation in `wp-env`, deterministic no-auth AI Client provider
registration/configuration, connector registration, model preference selection,
generated text output, WPCS/PHPCS, and Plugin Check for that generated plugin.
It does not prove credentialed OpenAI/Anthropic/Google provider behavior,
browser/editor behavior, PHPUnit behavior, broad integration-test coverage, or
release readiness. The first local proof is
`evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-full-profile-20260621/`.

To prove a disposable block is visible to both server-side and editor-side block registries:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py --fixture-kind block --block-name acme/runtime-card --editor-smoke --write --run-id wp-env-block-editor-smoke-YYYYMMDD --timeout-sec 180
```

To prove disposable block insertion, save/publish, and frontend server render:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py --fixture-kind block --block-name acme/runtime-card --editor-insert-render-smoke --write --run-id wp-env-block-editor-insert-render-smoke-YYYYMMDD --timeout-sec 180
```

To prove a generated block executor artifact, keep the executor packet block-only
and let the runtime harness synthesize a temporary plugin wrapper:

```bash
python3 evals/harness/certify_wordpress_executor_artifact.py --executor block --packet <candidate-output.md> --out-dir <generated-block-dir> --result-dir <result-dir> --overwrite
python3 evals/harness/run_wordpress_runtime_smoke.py --artifact-path <generated-block-dir> --artifact-kind block --block-build-smoke --editor-insert-render-smoke --provision-full-profile --write --run-id generated-block-full-profile-YYYYMMDD --timeout-sec 300
```

This proves packet materialization, static block artifact certification,
`npm install` plus `npm run build` on a disposable block copy, `wp-env`
registration through the wrapper, WPCS/PHPCS, Plugin Check, editor
insertion/save/publish, and frontend server render. It does not prove PHPUnit,
deprecation migration, Interactivity API behavior, MCP Adapter exposure, AI
Client provider-call behavior, or release readiness unless those gates are also
run and pass.

For a generated block Interactivity API proof, add `--interactivity-smoke` and
use a packet such as
`evals/suites/wordpress-block-executor/examples/interactivity-wordpress-v1.materializable-packet.md`:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py --artifact-path <generated-block-dir> --artifact-kind block --block-build-smoke --editor-insert-render-smoke --interactivity-smoke --provision-full-profile --write --run-id generated-block-interactivity-full-profile-YYYYMMDD --timeout-sec 300
```

This additionally proves built `viewScriptModule` registration, static
Interactivity API surfaces, frontend `data-wp-*` directives, and a Playwright
click/state assertion. The first local proof is
`evals/results/wordpress-skill-candidate-eval/generated-block-interactivity-full-profile-20260621/`.
It does not prove block deprecation migration, MCP Adapter exposure, AI Client
provider-call behavior, cross-browser behavior, or release readiness.

For a generated block deprecation proof, add `--deprecation-smoke` and use a
packet such as
`evals/suites/wordpress-block-executor/examples/deprecation-wordpress-v1.materializable-packet.md`:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py --artifact-path <generated-block-dir> --artifact-kind block --block-build-smoke --deprecation-smoke --provision-full-profile --write --run-id generated-block-deprecation-full-profile-YYYYMMDD --timeout-sec 300
```

This additionally proves a legacy serialized fixture can be loaded in the block
editor, migrated into the expected current-block attribute, saved as current
serialized markup, and rendered on the frontend. The first local proof is
`evals/results/wordpress-skill-candidate-eval/generated-block-deprecation-full-profile-20260621/`.
It does not prove Interactivity API behavior, MCP Adapter exposure, AI Client
provider-call behavior, cross-browser behavior, every historical deprecation
variant, or release readiness.

## Review Checkpoints

- After planning when architecture choices are expensive to reverse.
- After executor generation before code is treated as production-ready.
- After security-sensitive changes involving REST, AJAX, admin actions, SQL, uploads, or credentials.
- After performance-sensitive changes involving queries, caching, remote calls, cron, REST, dynamic blocks, or asset loading.
