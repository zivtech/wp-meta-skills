# WordPress Runtime Oracle Runbook

Updated: 2026-07-06.

The WordPress executor evidence stack has three deterministic layers before any LLM judge or critic review:

1. Saved packet contract: validates the executor's markdown output packet.
2. Packet materializer: converts materializable packets into generated files.
3. Generated artifact oracle: validates the files produced from that packet.

## Packet Gate

Use this before spending critic or judge time on a saved executor response:

```bash
python3 evals/harness/validate_wordpress_executor_packet.py --executor plugin --packet <candidate-output.md>
python3 evals/harness/validate_wordpress_executor_packet.py --executor block --packet <candidate-output.md>
python3 evals/harness/validate_wordpress_executor_packet.py --executor blueprint --packet <candidate-output.md>
```

This is a contract gate, not runtime proof. It checks required headings, file maps or Blueprint JSON, exact WordPress surfaces, verification-oracle language, unsafe command patterns, and critic handoff.

## Packet Materialization Gate

Use this after the packet gate and before the artifact gate:

```bash
python3 evals/harness/materialize_wordpress_executor_packet.py --executor plugin --packet <candidate-output.md> --out-dir <generated-plugin-dir>
python3 evals/harness/materialize_wordpress_executor_packet.py --executor block --packet <candidate-output.md> --out-dir <generated-block-dir>
python3 evals/harness/materialize_wordpress_executor_packet.py --executor blueprint --packet <candidate-output.md> --out-dir <generated-blueprint-dir>
```

For plugin and block packets, each generated file must be introduced by `### relative/path.ext` and followed immediately by one fenced code block containing the complete file contents. Paths must be relative and stay inside the artifact root. For Blueprint packets, the `## Generated Blueprint` section must include one fenced JSON object; the materializer writes it to `blueprint.json`.

The four reviewed Plan 009 flagship dependency locks are the sole bounded
exception. Their lock fence contains a fixed approved-profile ID, canonical
lock SHA-256, and exact manifest SHA-256 instead of tens of thousands of lock
lines. The materializer accepts only IDs in its repository registry, verifies
the target path and manifest binding, verifies canonical bytes under
`evals/harness/approved-locks`, and emits those bytes as the lock. Arbitrary
paths, external profiles, and caller-selected canonical files are forbidden.

This is still not runtime proof. It only proves the saved packet can be transformed into files without human interpretation.

## Combined Certification Gate

For saved executor packets, use the combined certifier as the normal inner-loop command:

```bash
python3 evals/harness/certify_wordpress_executor_artifact.py --executor plugin --packet <candidate-output.md> --out-dir <generated-plugin-dir> --result-dir <result-dir> --overwrite
python3 evals/harness/certify_wordpress_executor_artifact.py --executor block --packet <candidate-output.md> --out-dir <generated-block-dir> --result-dir <result-dir> --overwrite
python3 evals/harness/certify_wordpress_executor_artifact.py --executor blueprint --packet <candidate-output.md> --out-dir <generated-blueprint-dir> --result-dir <result-dir> --overwrite
```

Add `--profile runtime` or repeated `--require-tool` flags only when the environment is provisioned for those checks. A `blocked` certification is useful evidence: it means the packet and materialized files reached a runtime dependency the current machine could not satisfy.

When `--result-dir` is provided, failed or blocked certifications write `repair-prompt.md` next to `certification.json` and `scorecard.md`. Use that prompt as the evaluator-feedback input for the next executor revision loop; it is generated from the failing gate IDs, embeds the saved packet in a fence-safe markdown block, and does not require an LLM judge.

## Static Artifact Gate

Use this after materializing generated files into a directory:

```bash
python3 evals/harness/validate_wordpress_artifact.py --artifact-type plugin --path <generated-plugin-dir>
python3 evals/harness/validate_wordpress_artifact.py --artifact-type block --path <generated-block-dir>
python3 evals/harness/validate_wordpress_artifact.py --artifact-type theme --path <generated-theme-dir>
python3 evals/harness/validate_wordpress_artifact.py --artifact-type blueprint --path <generated-blueprint-dir>/blueprint.json
```

The static profile is local and cheap. It checks WordPress-specific structure and safety heuristics:

- plugin headers, destructive command patterns, secret-like assignments, and REST/AJAX/admin/SQL guardrails;
- cheap WPCS-shape checks for plugin PHP, including file-level `@package` in plugin-header files and obvious short `[]` array literals;
- static AI-surface guardrails for Abilities API, MCP Adapter, AI Client, and Connectors usage, including version/feature guards, schemas, permission callbacks, and error-handling boundaries;
- the API-existence lint (`api_existence`, below) for plugin, block, and theme artifacts that contain PHP;
- the security gate (`security_gate`, below) for PHP artifacts, producing `security-gate.json` evidence for deterministic security findings and suppression review;
- block.json validity, required block metadata, and registration or build-script evidence;
- theme headers or theme.json validity;
- Blueprint JSON parseability and non-empty steps.

Static artifact pass does not prove the artifact runs in WordPress. The WPCS-shape check is an early hard stop for failure classes already observed in generated artifacts, not a replacement for full runtime smoke. The security gate is deterministic evidence for selected WPCS security/DB sniffs and suppression abuse; it does not prove authorization, IDOR, or cross-function exploitability.

### API-Existence Lint (`api_existence`)

The `api_existence` structural check combines three engines over every
PHP-bearing plugin, block, or theme artifact:

1. **PHPStan engine** (needs the pinned toolchain): PHPStan level 0 with
   `php-stubs/wordpress-stubs` and `johnbillion/wp-compat` — unknown core
   functions/classes/methods (the AI hallucination failure mode, with
   `difflib` did-you-mean suggestions) and core symbols or hooks newer than
   the declared `Requires at least:` header (guard-aware via real scope
   analysis).
2. **Native symbol engine** (always available): reads the committed MIT-only
   snapshot `evals/harness/data/wp-symbols.json` (rebuild with
   `scripts/build-wp-symbol-db.py`; needs a PHP CLI). Always adds
   `deprecated_api` findings naming the exact successor
   (`wp_login()` → `wp_signon()`); when the toolchain is absent it also
   takes over existence and version-range checks at regex tier, so the gate
   degrades to reduced coverage with explicit negative space instead of
   going fully `blocked`.
3. **Hooks engine** (available with the toolchain): `unknown_hook` findings
   with did-you-mean suggestions, reading hook names at analysis time from
   the Composer vendor tree (`vendor/wp-hooks/wordpress-core`, GPL-3.0 data
   that is never committed — see the reuse ledger). Dynamic hook names and
   names matching only generic dynamic core patterns (`wp_{$field}`-class
   catch-alls) are advisory; specific dynamic patterns
   (`save_post_{$post->post_type}`) allow; artifact-defined hooks, the
   artifact slug prefix, `Requires Plugins:` slugs, and `--allow-prefix`
   namespaces allow.

One-time setup for the PHPStan + hooks engines (PHP >= 8.1 plus Composer;
CI installs this in the validate workflow):

```bash
composer install --working-dir evals/harness/php-tools
```

Standalone usage and full findings report:

```bash
python3 evals/harness/wp_api_lint.py --path <generated-plugin-dir> --out api-lint.json
python3 evals/harness/wp_api_lint.py --path <generated-plugin-dir> --allow-prefix woocommerce_
```

Evidence semantics: `pass` means no exact findings from any engine that ran;
`fail` carries per-finding file/line/suggestion evidence (the certifier
forwards it into `repair-prompt.md` and writes the full report to
`api-lint.json` beside `certification.json`); every report carries an
`engines` map naming what ran and what was unavailable, and unavailable
engines add explicit negative-space lines. `blocked` now means neither the
toolchain nor the committed snapshot was available — blocked is honest
evidence, never a pass.

Standing negative space: string callback existence and PHP constant
existence are not checked; `tests/` directories inside the artifact are
excluded (the `phpunit` runtime gate owns test code); hook arg-count
validation, deprecated-hook data, WooCommerce and other third-party symbol
sets, and JS `@wordpress/*` package checks are later phases; REST routes,
option names, and capabilities are site-defined and out of scope.

### Security Gate (`security_gate`)

The `security_gate` structural check runs the WPCS static security profile over
PHP-bearing plugin, block, or theme artifacts and writes sidecar evidence for
the security critic. It runs PHPCS twice: once normally and once with
`--ignore-annotations`; violations that reappear only in the second run are
recorded as `suppressed_annotations[]`.

Hard-fail evidence:

- `WordPress.DB.PreparedSQL*` errors;
- `WordPress.Security.EscapeOutput*` errors;
- security-relevant suppressions that reappear under `--ignore-annotations`.

Advisory evidence is preserved for the critic, including direct-query/caching
signals that need reachability and product-context review. Reviewed
`get_block_wrapper_attributes()` suppressions are recorded with
`reviewed_safe_api` instead of being treated as blanket allowlist evidence.

One-time setup for the pinned PHPCS/WPCS toolchain:

```bash
composer install --working-dir evals/harness/php-tools
```

Standalone usage:

```bash
python3 evals/harness/wp_security_gate.py --path <generated-plugin-dir> --out security-gate.json
```

Security critic contract validation with a sidecar:

```bash
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-security-critic \
  --output <critic-output.md> \
  --security-gate security-gate.json
```

Saved-output runner behavior: fixture sidecars named
`fixtures/<fixture>.security-gate.json` are auto-detected and threaded into the
output-contract oracle.

Evidence semantics: `pass` means no enforced security findings or
security-relevant suppression abuse from the static profile; `fail` carries
rule/file/line evidence in `findings[]` and `suppressed_annotations[]`;
`blocked` means the pinned PHPCS/WPCS toolchain was unavailable or produced no
parseable JSON; `skip` means no PHP files were present. Every report carries
negative-space lines stating what the gate does not prove.

Standing negative space: no taint or cross-function data-flow analysis; no
authorization/IDOR/capability-correctness judgment; no Plugin Check, PHPStan,
or Semgrep advisory layer in this phase; no block/theme JavaScript scan. Those
remain critic or later-roadmap responsibilities.

## Runtime Tool Gate

Use explicit runtime tool gates only when the machine has the needed toolchain. Missing required tools are reported as `blocked`, not as success. `--require-tool` works in either profile; use it without `--profile runtime` for a narrow proof, and use `--profile runtime` only when you want the artifact type's full default runtime contract.

Narrow plugin smoke example:

```bash
python3 evals/harness/validate_wordpress_artifact.py \
  --artifact-type plugin \
  --path <generated-plugin-dir> \
  --require-tool php-lint \
  --require-tool wp-env \
  --wp-env-root <wp-env-project-root>
```

Full plugin runtime profile currently adds PHPCS/WPCS and Plugin Check, so it will report `blocked` until those tools are installed and configured:

```bash
python3 evals/harness/validate_wordpress_artifact.py \
  --artifact-type plugin \
  --path <generated-plugin-dir> \
  --profile runtime \
  --wp-root <wordpress-root>
```

Block example:

```bash
python3 evals/harness/validate_wordpress_artifact.py \
  --artifact-type block \
  --path <generated-block-dir> \
  --profile runtime \
  --require-tool wp-env \
  --wp-env-root <wp-env-project-root>
```

The runtime profile currently supports:

- `php-lint` with `php -l`;
- `phpcs` / `wpcs` with PHPCS and installed WordPress Coding Standards, including `vendor/bin/phpcs` under the artifact root or `--wp-env-root`;
- `phpunit`;
- `npm-build`;
- `plugin-check` with local `wp plugin check` or `wp-env` WP-CLI fallback when `--wp-env-root` is provided;
- `wp-env` smoke via `npx --yes @wordpress/env run cli -- wp core version`.

For Plugin Check runtime checks that need the plugin's `cli.php`, pass `--plugin-check-require <path-to-plugin-check/cli.php>`. If WP-CLI must run from a specific WordPress root, pass `--wp-root <wordpress-root>`.
For `wp-env` runtime checks, pass `--wp-env-root <wp-env-project-root>` when the generated artifact lives in a plugin, block, or theme subdirectory beneath the project that contains `.wp-env.json` or `package.json`.
For `wp-env` Plugin Check, the Plugin Check plugin must be installed in the environment; the provisioned smoke harness handles this setup.
When default ports are occupied, use `wp-env start --auto-port` or `"autoPort": true` in `.wp-env.json`; the official `@wordpress/env` docs state fixed ports are the default and busy ports fail at start time.

## Disposable Runtime Smoke Harness

Use this when you need to prove the local `php-lint` plus `wp-env` lane without hand-building a fixture:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --write \
  --run-id wp-env-runtime-smoke-YYYYMMDD \
  --timeout-sec 300
```

The harness creates a temporary plugin fixture, starts `@wordpress/env` with `--auto-port`, runs the artifact oracle with `--require-tool php-lint --require-tool wp-env`, records the full plugin runtime profile as informational, stops `wp-env`, and writes `runtime-smoke.json` plus `scorecard.md`.

For a disposable server-rendered block registration smoke, use the block fixture
mode. The harness creates a temporary plugin with `block.json`, a minimal editor
script, and a server render template, activates it in `wp-env`, and verifies the
named block through `WP_Block_Type_Registry`:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --fixture-kind block \
  --block-name acme/runtime-card \
  --write \
  --run-id wp-env-block-runtime-smoke-YYYYMMDD \
  --timeout-sec 300
```

This proves plugin activation, `wp-env`, block metadata parsing, and runtime
block registration for that fixture or generated block plugin. It does not prove
editor insertion, block deprecation behavior, browser rendering, frontend
interactivity, WPCS, Plugin Check, or release readiness unless those checks are
also required and pass. The first local proof is recorded at
`evals/results/wordpress-skill-candidate-eval/wp-env-block-runtime-smoke-20260620/`.

For a narrow editor-side block registry smoke, add `--editor-smoke`. The harness
logs into wp-admin with Playwright, opens the post editor, verifies the editor
root is present, and requires `window.wp.blocks.getBlockType(<block-name>)` to
resolve without page or console errors:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --fixture-kind block \
  --block-name acme/runtime-card \
  --editor-smoke \
  --write \
  --run-id wp-env-block-editor-smoke-YYYYMMDD \
  --timeout-sec 180
```

This proves the disposable block fixture is visible to both server-side block
registration and the editor-side block registry. It does not prove block
insertion, save serialization, frontend rendering, deprecation behavior,
interactivity, WPCS, Plugin Check, or release readiness. The first local proof is
recorded at
`evals/results/wordpress-skill-candidate-eval/wp-env-block-editor-smoke-20260620/`.

For an end-to-end disposable block editor/render smoke, use
`--editor-insert-render-smoke`. The harness inserts the block through the editor
data store, publishes the post, opens the frontend permalink, and requires the
server-rendered block text to appear without page or console errors:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --fixture-kind block \
  --block-name acme/runtime-card \
  --editor-insert-render-smoke \
  --write \
  --run-id wp-env-block-editor-insert-render-smoke-YYYYMMDD \
  --timeout-sec 180
```

This proves insertion, save/publish, and frontend server-rendered output for the
disposable dynamic block fixture. It does not prove deprecation migration,
Interactivity API behavior, cross-browser behavior, WPCS, Plugin Check, or
release readiness. The first local proof is recorded at
`evals/results/wordpress-skill-candidate-eval/wp-env-block-editor-insert-render-smoke-20260620/`.

For a generated block executor artifact, keep the packet block-only and let the
runtime harness synthesize the disposable wrapper plugin. First materialize and
certify the block packet, then pass the generated block directory with
`--artifact-kind block`. When `--block-name` is omitted, the harness infers it
from `block.json`:

```bash
python3 evals/harness/certify_wordpress_executor_artifact.py \
  --executor block \
  --packet <candidate-output.md> \
  --out-dir <generated-block-dir> \
  --result-dir <result-dir> \
  --overwrite

python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path <generated-block-dir> \
  --artifact-kind block \
  --block-build-smoke \
  --editor-insert-render-smoke \
  --provision-full-profile \
  --write \
  --run-id generated-block-full-profile-YYYYMMDD \
  --timeout-sec 300
```

This proves the saved block packet can materialize into files, pass the static
block artifact gate, run `npm install` plus `npm run build` on a disposable
copy, register through a disposable wrapper in `wp-env`, pass WPCS/PHPCS and
Plugin Check for that wrapper, appear in the editor, insert/save/publish, and
render on the frontend. It does not prove PHPUnit, deprecation migration,
Interactivity API behavior, cross-browser behavior, MCP Adapter exposure, AI
Client provider-call behavior, or release readiness unless those gates are also
run and pass. The first local proofs are recorded at
`evals/results/wordpress-skill-candidate-eval/generated-block-artifact-cert-20260620/`
and
`evals/results/wordpress-skill-candidate-eval/generated-block-full-profile-20260620/`.

For a generated block Interactivity API proof, use a block packet that declares
`supports.interactivity`, `viewScriptModule`, `@wordpress/interactivity`, and
frontend `data-wp-*` directives, then add `--interactivity-smoke` to the runtime
profile:

```bash
python3 evals/harness/certify_wordpress_executor_artifact.py \
  --executor block \
  --packet evals/suites/wordpress-block-executor/examples/interactivity-wordpress-v1.materializable-packet.md \
  --out-dir evals/results/wordpress-skill-candidate-eval/generated-block-interactivity-artifact-cert-YYYYMMDD/generated-block \
  --result-dir evals/results/wordpress-skill-candidate-eval/generated-block-interactivity-artifact-cert-YYYYMMDD \
  --overwrite

python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path evals/results/wordpress-skill-candidate-eval/generated-block-interactivity-artifact-cert-YYYYMMDD/generated-block \
  --artifact-kind block \
  --block-build-smoke \
  --editor-insert-render-smoke \
  --interactivity-smoke \
  --provision-full-profile \
  --write \
  --run-id generated-block-interactivity-full-profile-YYYYMMDD \
  --timeout-sec 300
```

When `npm run build` emits a built block metadata file, the disposable wrapper
registers the built block directory so `viewScriptModule` uses the compiled
module asset. `--interactivity-smoke` adds a static Interactivity surface gate
and a Playwright frontend click/state assertion. The first local proof is
recorded at
`evals/results/wordpress-skill-candidate-eval/generated-block-interactivity-artifact-cert-20260621/`
and
`evals/results/wordpress-skill-candidate-eval/generated-block-interactivity-full-profile-20260621/`.
It proves the generated block can publish and render, then change `context.count`
from `0` to `1` through Interactivity API directives. It does not prove block
deprecation migration, MCP Adapter exposure, AI Client provider calls, broad
cross-browser behavior, or release readiness.

For a generated block deprecation proof, use a block packet that includes a
legacy serialized-content fixture plus `deprecation-smoke.json`, then add
`--deprecation-smoke` to the runtime profile:

```bash
python3 evals/harness/certify_wordpress_executor_artifact.py \
  --executor block \
  --packet evals/suites/wordpress-block-executor/examples/deprecation-wordpress-v1.materializable-packet.md \
  --out-dir evals/results/wordpress-skill-candidate-eval/generated-block-deprecation-artifact-cert-YYYYMMDD/generated-block \
  --result-dir evals/results/wordpress-skill-candidate-eval/generated-block-deprecation-artifact-cert-YYYYMMDD \
  --overwrite

python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path evals/results/wordpress-skill-candidate-eval/generated-block-deprecation-artifact-cert-YYYYMMDD/generated-block \
  --artifact-kind block \
  --block-build-smoke \
  --deprecation-smoke \
  --provision-full-profile \
  --write \
  --run-id generated-block-deprecation-full-profile-YYYYMMDD \
  --timeout-sec 300
```

`--deprecation-smoke` creates a draft post from the legacy fixture, opens it in
the block editor, requires the target block to parse as valid current-block
content, verifies the exact migrated attribute named by `deprecation-smoke.json`,
serializes the editor's current block tree, saves the post, and checks both the
current serialized marker and frontend text. The first local proof is recorded
at
`evals/results/wordpress-skill-candidate-eval/generated-block-deprecation-artifact-cert-20260621/`
and
`evals/results/wordpress-skill-candidate-eval/generated-block-deprecation-full-profile-20260621/`.
It proves the generated block can migrate one legacy fixture through WordPress'
block deprecation path into current saved markup and frontend output. It does
not prove Interactivity API behavior, MCP Adapter exposure, AI Client provider
calls, broad cross-browser behavior, every historical deprecation variant, or
release readiness.

To wrap an existing generated plugin artifact in a disposable `wp-env` project, pass `--artifact-path`:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path <generated-plugin-dir>/<plugin-slug> \
  --write \
  --run-id generated-plugin-runtime-smoke-YYYYMMDD \
  --timeout-sec 300
```

For generated plugin artifacts with a PHPUnit suite, add `--phpunit-smoke` and provision the full profile:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path <generated-plugin-dir>/<plugin-slug> \
  --phpunit-smoke \
  --provision-full-profile \
  --write \
  --run-id generated-plugin-phpunit-full-profile-YYYYMMDD \
  --timeout-sec 300
```

When the copied artifact contains `composer.json`, the harness installs artifact-local Composer dependencies before running `phpunit`. This proves plugin activation, artifact-local PHPUnit, WPCS/PHPCS, Plugin Check, and `wp-env` for that generated plugin copy. It does not prove block/editor/browser behavior, MCP Adapter runtime exposure, AI Client provider-call behavior, broad integration coverage, or release readiness. The first local proofs are recorded at `evals/results/wordpress-skill-candidate-eval/generated-plugin-phpunit-artifact-cert-20260620/` and `evals/results/wordpress-skill-candidate-eval/generated-plugin-phpunit-full-profile-20260620/`.

For generated Abilities API plugins, add a named ability smoke. The post-summary execution mode creates a disposable post, resolves the named ability with `wp_get_ability()`, executes it with a `post_id` input, and requires a non-empty summary result:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path <generated-plugin-dir>/<plugin-slug> \
  --ability-name vendor/ability-name \
  --execute-post-summary-ability \
  --write \
  --run-id generated-abilities-runtime-smoke-YYYYMMDD \
  --timeout-sec 300
```

This proves plugin activation, `wp-env`, and Abilities registration/execution for that generated artifact. It does not prove MCP Adapter exposure, AI Client provider calls, browser/editor behavior, WPCS, Plugin Check, or release readiness unless those checks are also required and pass.

For generated MCP-public Abilities API plugins, add `--mcp-adapter-smoke`.
The harness installs the current WordPress MCP Adapter plugin zip in disposable
`wp-env`, lists the default adapter server, calls `tools/list` through
`wp mcp-adapter serve`, discovers the named public ability, and executes it
through `mcp-adapter-execute-ability`:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path <generated-plugin-dir>/<plugin-slug> \
  --ability-name vendor/ability-name \
  --mcp-adapter-smoke \
  --mcp-adapter-execute-args-json '{"marker":"Runtime MCP smoke"}' \
  --mcp-adapter-expected-output "Runtime MCP smoke" \
  --provision-full-profile \
  --write \
  --run-id generated-mcp-adapter-full-profile-YYYYMMDD \
  --timeout-sec 300
```

The first local proof is recorded at
`evals/results/wordpress-skill-candidate-eval/generated-mcp-adapter-artifact-cert-20260621/`
and
`evals/results/wordpress-skill-candidate-eval/generated-mcp-adapter-full-profile-20260621/`.
It proves plugin activation, `wp-env`, MCP Adapter installation, STDIO
`tools/list`, `mcp-adapter-discover-abilities`,
`mcp-adapter-execute-ability`, WPCS/PHPCS, and Plugin Check for the generated
artifact. It does not prove AI Client provider calls, browser/editor behavior,
PHPUnit behavior, long-run model variance, broad integration coverage, or
release readiness. The first pass emitted upstream PHP deprecation notices from
MCP Adapter internals under the local PHP runtime; keep those as adapter/runtime
risk instead of treating the proof as release readiness.

For generated AI Client provider-call plugins, add `--ai-client-smoke`. The
harness calls a generated helper through `wp --user=admin eval`, requires
`wp_ai_client_prompt()`, checks the AI Client provider registry, confirms
provider registration/configuration, confirms connector registration when
`wp_is_connector_registered()` exists, and requires expected provider output:

### Repair-loop evidence freshness

Repair certification is fail closed. Each repair run atomically leases its
`evals/results/<run-id>` directory and refuses an existing run ID. Every
iteration uses fresh artifact, static-certification, and runtime-result
directories. Static evidence records schema version, a fresh opaque evidence
ID, the exact packet SHA-256, and a deterministic no-follow digest of the
materialized regular-file tree. The digest hashes sorted, canonical UTF-8 JSON
Lines records (`path`, decimal `size`, lowercase `sha256`), with one record per
line and a terminating newline.

Runtime repair calls pass the same evidence ID and expected artifact digest.
The runtime harness copies the execution closure into its fresh runtime lease,
independently digests that staged destination, and compares it before starting
`wp-env`. It executes only the staged destination, then writes only to the explicit
`--results-root/<run-id>/runtime-smoke.json`. The repair loop reads that exact
file; it does not search global results or similarly named runs. Green requires
process exit code 0, matching identities and digests, top-level `status:
pass`, and `full_plugin_runtime_profile.status: pass`. Missing, malformed,
stale, `blocked`, and `fail` evidence remain non-green and are reported as
explicit command, result, status, profile, or digest gates.

`--workdir` is an optional caller-owned parent for a newly created unique run
directory. The harness never writes runtime artifacts directly at the parent
root. Read `runtime_root` in the JSON summary to locate the unique child;
`workdir_parent` records the supplied parent. `--keep-artifacts` or
`--keep-running` retains the child. Without either flag, sentinel-verified
cleanup removes only the child.

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

The first local proof is recorded at
`evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-artifact-cert-20260621/`
and
`evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-full-profile-20260621/`.
It proves plugin activation, `wp-env`, deterministic no-auth AI Client provider
registration/configuration, connector registration, model preference selection,
`generate_text()` output, WPCS/PHPCS, and Plugin Check for the generated
artifact. It does not prove credentialed OpenAI/Anthropic/Google provider
behavior, browser/editor behavior, PHPUnit behavior, long-run model variance,
broad integration coverage, or release readiness. A supplied `--workdir`
still receives a Docker-safe unique child name; callers must not rely on files
being written at the parent root.

To provision and require the full disposable plugin runtime profile, including Composer-installed WPCS and Plugin Check inside `wp-env`, run:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --provision-full-profile \
  --write \
  --run-id wp-env-runtime-full-profile-YYYYMMDD \
  --timeout-sec 300
```

`--provision-full-profile` can also be combined with `--artifact-path`. In the 2026-06-20 generated Abilities run, the artifact passed Plugin Check and the Abilities execution smoke, but failed WPCS/PHPCS. The static artifact gate now catches the same obvious failure class earlier through `php_wpcs_shape_heuristics`; that is a valid failed gate and should drive executor repair before another release-readiness claim.

Use `--strict-full-profile` when PHPCS/WPCS and WP-CLI Plugin Check have already been provisioned separately and full plugin runtime certification is the intended gate.

## Evidence Semantics

- `pass`: every required check for the chosen command passed.
- `fail`: the generated artifact violated a required check.
- `blocked`: the artifact could not be evaluated because required runtime tooling or environment state was missing.

Do not use a static artifact pass as evidence for WPCS, Plugin Check, wp-env, PHPUnit, block validation, editor smoke, or frontend smoke claims. Those require the runtime profile or a stronger environment-specific command recorded alongside the artifact.

## Current Primary References

- WordPress Plugin Check documents `wp plugin check` for WP-CLI checks: <https://wordpress.org/plugins/plugin-check/>
- `@wordpress/env` documents `wp-env` as a local WordPress environment for plugin and theme development/testing: <https://developer.wordpress.org/block-editor/reference-guides/packages/packages-env/>
- `@wordpress/scripts` documents `wp-scripts build` entry-point and output-path usage for block build validation: <https://developer.wordpress.org/block-editor/reference-guides/packages/packages-scripts/>
- WordPress block registration documents `block.json` and `register_block_type()`: <https://developer.wordpress.org/block-editor/getting-started/fundamentals/registration-of-a-block/>
- WordPress block deprecation documents deprecated `save`, `migrate`, and `isEligible` behavior: <https://developer.wordpress.org/block-editor/reference-guides/block-api/block-deprecation/>
- WordPress MCP Adapter introduces adapter installation, `wp mcp-adapter serve`, `tools/list`, `mcp-adapter-discover-abilities`, and `mcp-adapter-execute-ability`: <https://developer.wordpress.org/news/2026/02/from-abilities-to-ai-agents-introducing-the-wordpress-mcp-adapter/>
- WordPress AI Client introduces `wp_ai_client_prompt()` and provider-backed text generation: <https://make.wordpress.org/core/2026/03/24/introducing-the-ai-client-in-wordpress-7-0/>
- WordPress Connectors API provides the connector registry surfaced by AI providers: <https://make.wordpress.org/core/2026/03/18/introducing-the-connectors-api-in-wordpress-7-0/>
- WordPress Coding Standards for PHPCS are maintained in WordPressCS: <https://github.com/WordPress/WordPress-Coding-Standards>
# Plan 009 Step 0 feasibility boundary

The feasibility checkpoint is intentionally not production runtime wiring.
It establishes exact fixture and trusted-runner locks, reviewed image/core
inventory, a bounded subprocess transport, repository-owned internal-network
Compose policy, exact non-root Dockerfiles/entrypoints, and a separate GitHub
Actions job with `permissions: {}` and no cache credentials or secrets.

Live quota and topology claims are Linux Docker only. macOS runs static policy,
materialization, and compatibility tests but reports live boundary execution
as blocked. The exact checkpoint commit must pass the no-secrets GitHub-hosted
Linux job before Plan 009 Step 1. Record the workflow URL, commit SHA, runner OS
and architecture, and conclusion; local Docker Desktop evidence is not a
substitute. No generated artifact is present during trusted provisioning.

For every final tmpfs, Step 0 parses `df -Pk` and `df -Pi` totals and rejects a
missing, unparseable, or oversized profile. Byte totals allow one 1 KiB block
of filesystem rounding. Inode totals allow the larger of 16 inodes or 1% of
the reviewed `nr_inodes`. Each distinct byte and inode profile is exhausted
once, must contain the overflow, is cleaned, and must accept a new write
afterward. Sanitized observed totals and recovery results are persisted in the
Step 0 result.
