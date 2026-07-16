# WordPress Runtime Oracle Runbook

Updated: 2026-07-16.

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
signals that need reachability and product-context review. Every newly emitted
unmatched suppressed `OutputNotEscaped` occurrence remains a hard fail unless
the existing operator-supplied `--allow-suppression-prefix` policy applies; PHPCS
basename messages cannot distinguish the genuine global
`get_block_wrapper_attributes()` helper from constants, namespaced/local
functions, or imported aliases. New reports therefore emit
`reviewed_safe_api: null`. The security critic may adjudicate genuine-helper
context manually, but the deterministic gate does not downgrade it. Historical
v1 reports with a non-null nullable-string field remain readable but are not
current deterministic proof.

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
  --expected-frontend-selector .wp-block-acme-runtime-card \
  --expected-frontend-text "Runtime block smoke" \
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
`--artifact-kind block`. Direct external-artifact use requires the exact block
name, frontend selector, expected text, evidence ID, and pre-stage artifact
digest; none is inferred:

The supplied artifact path must be canonical and contain no symlink component.
On macOS, use `/private/tmp/...` rather than the `/tmp` symlink. A path-boundary
rejection occurs before WordPress and is not a block failure.

```bash
python3 evals/harness/certify_wordpress_executor_artifact.py \
  --executor block \
  --packet <candidate-output.md> \
  --out-dir <generated-block-dir> \
  --result-dir <result-dir> \
  --overwrite

artifact="<generated-block-dir>"
digest="$(PYTHONPATH=evals/harness python3 - "$artifact" <<'PY'
import sys
from pathlib import Path
from artifact_staging import digest_regular_tree
print(digest_regular_tree(Path(sys.argv[1])))
PY
)"
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path "$artifact" \
  --artifact-kind block \
  --expected-artifact-digest "$digest" \
  --evidence-id generated-block-full-profile-YYYYMMDD \
  --block-build-smoke \
  --block-name vendor/block-name \
  --editor-insert-render-smoke \
  --expected-frontend-selector .wp-block-vendor-block-name \
  --expected-frontend-text "Exact fixture-owned text" \
  --provision-full-profile \
  --strict-full-profile \
  --write \
  --run-id generated-block-full-profile-YYYYMMDD \
  --timeout-sec 300
```

This proves the saved block packet can materialize into files, pass the static
block artifact gate, run `npm install` plus `npm run build` on a disposable
copy, pass a fresh post-build execution-artifact gate, register through a
disposable wrapper in `wp-env`, pass WPCS/PHPCS and Plugin Check for that
wrapper, appear in the editor, insert/save/publish, and render in the same
isolated no-egress runtime.
The build-command gate and emitted-artifact gate are independent required rows;
neither substitutes for the other. It does not prove PHPUnit, deprecation migration,
Interactivity API behavior, cross-browser behavior, MCP Adapter exposure, AI
Client provider-call behavior, or release readiness unless those gates are also
run and pass. The first local proofs are recorded at
`evals/results/wordpress-skill-candidate-eval/generated-block-artifact-cert-20260620/`
and
`evals/results/wordpress-skill-candidate-eval/generated-block-full-profile-20260620/`.

The pre-build static block contract is intentionally narrower than runtime
registration proof. It parses at most 128 `block.json` files and 8 MiB of block
metadata, requires unique valid block names and resolved `file:` edges, and
labels non-`file:` asset values as external handle/module IDs whose registration
is not statically proven. Direct PHP registration evidence is a bounded lexical
candidate only; runtime `WP_Block_Type_Registry` is authoritative. The admitted
package entrypoint grammar is `wp-scripts build`, safe positional paths,
`--source-path=...`, `--output-path=...`, and the pinned boolean options
`--experimental-modules`, `--webpack-copy-php`, `--webpack-no-externals`,
`--blocks-manifest`, and `--webpack-bundle-analyzer`. Unknown options, control
characters, shell operators, traversal, and help/version commands fail.

External generated-block Interactivity and deprecation runtime modes are not
supported by the isolated artifact path. The historical built-in fixture modes
remain diagnostic-only and cannot substitute for the `block-runtime` adapter's
fixture-owned selector/text proof. Historical result directories show what ran
then; they do not establish current support.

### Post-build block execution-artifact proof

For built block runtime, a full artifact proof means all of the following pass:

- the isolated build command completes and returns an authenticated sandbox-output capability;
- one source-anchored metadata layout selects either the exact child
  `build/block.json` or the source fallback, with ambiguity rejected;
- the selected metadata is strict bounded JSON with nonempty string `name`,
  `title`, and `category` values;
- WordPress 7.0.1 metadata references and optional `.asset.php`/RTL companions
  resolve against the pinned core rule table and authenticated manifest;
- every executable-PHP candidate outside excluded namespaces is scanned with
  syntax, secret, API, and security gates, including PHP-tagged files without a
  `.php` suffix; PHPStan and PHPCS receive bounded authenticated `.php` aliases
  whose original path, size, and hash mapping is bound into the artifact proof,
  and findings are remapped to original paths; candidates inside excluded
  namespaces are rejected;
- one minimal no-follow scanner handoff is re-proved around each path-required
  tool and removed afterward;
- the runtime closure contains every non-excluded file under the selected root,
  every present metadata edge outside that root, and every conservative PHP
  candidate outside excluded dependency namespaces;
- source-only synthesis accepts an authenticated caller-input capability only
  when the proof selects the source `block.json` and binds the exact source
  manifest; built synthesis requires authenticated sandbox output;
- the wrapper byte-for-byte matches the shared canonical generator, including
  exactly one executable registration bootstrap for the selected `block.json`,
  passes an independent bounded `php -l`, and binds both checks into
  `wrapper_validation_digest`; and
- the output manifest, graph, candidate set, scan file table, wrapper bytes,
  synthesized manifest, core rule identity, and final
  `execution_proof_digest` remain bound in runtime JSON.

The reviewed admission limits are 1,024 post-build files, 32 MiB of post-build
output, 1 MiB per selected `block.json`, 512 metadata edges, 64 PHP candidates,
JSON depth 32, 8 MiB across the PHP set, 8 MiB per runtime member, and 16 MiB
across the proven runtime closure. A limit breach fails before the scan-handoff copy. PHP lint,
PHPStan, both PHPCS suppression-differential passes, synthesis, closure proof,
and wrapper lint share the runtime preparation deadline; subprocess output is
bounded, scanner result parsing has per-file and aggregate message caps, source
excerpts are read once per file, and a timeout or overflow is `blocked`, never
a partial pass.

The CI boundary measurement runs both combinations that cannot honestly be one
fixture:

```bash
python3 scripts/measure-plan010-artifact-path.py \
  --profile ci \
  --output tmp/plan010-artifact-measurement.json
```

The aggregate profile reaches 1,024 files, 32 MiB output, 1 MiB metadata, 512
edges, 64 PHP candidates/8 MiB, and a 16 MiB closure, including PHP outside the
selected root. The maximum-member profile sends one exact 8 MiB member through
the same public gate, synthesis, and digest-binding path. CI requires each
profile to finish certification within 180 seconds and end to end within 210
seconds, with the maximum observed parent-or-child `ru_maxrss` at or below
1.5 GiB. The JSON records exact top-level bounded tool invocations, proof holds,
streamed copy counts/bytes, digests, toolchain lock identity, and cleanup
receipts, including both PHP scanner-alias copy passes. It does not count
descendants a tool may create and does not claim a
simultaneous process-tree RSS total. These are precommitted CI admission
ceilings, not a production-capacity or performance claim.

This is deliberately conservative, not an exact dynamic-include graph. It does
not prove JavaScript import reachability, `eval()` or runtime-generated code,
runtime-specific PHP short-tag behavior, authorization, Docker/`wp-env`,
WordPress boot, database behavior, browser rendering, concurrency, production
throughput, or release readiness.

For an external generated plugin, use the canonical digest/evidence-bearing
command in `evals/harness/README.md`. The supported isolated profile is plugin
activation, Plugin Check, the container browser, optional artifact-local
PHPUnit, and the strict full profile. The historical external-artifact Abilities,
MCP Adapter, and AI Client special modes are rejected before isolated runtime
preparation; their historical `wp-env` result directories do not establish
current support.

### Repair-loop evidence freshness

The repair loop applies this compatibility matrix before it creates a run
directory or calls a model:

| Executor | Static | Runtime |
|---|---|---|
| Plugin | Supported | `standard`: activation, Plugin Check, isolated container browser |
| Block | Supported | Conditional `block-runtime`: fixture-owned exact block name, wrapper selector, and visible text required |
| Blueprint | Supported | Rejected |

For block runtime, only the exact selected fixture pair may supply
`runtime_assertions.block_name`, `runtime_assertions.frontend_selector`, and
`runtime_assertions.expected_frontend_text`. The loader rejects missing or extra
keys, identity drift, unsafe paths or selectors, non-regular files, and invalid
Unicode. The materialized block name must match before browser launch. The
isolated result must then contain the exact `block-runtime` check inventory:
`wp_cli_activation`, `plugin_check`, `block_registration`, `container_browser`,
and `block_editor_frontend`, followed by the consumer-added `runtime_identity`.
The frontend proof is selector-scoped, requires one visible match, and binds the
Unicode-NFC/whitespace-normalized expected and observed text hashes.

Both plugin and block repair consumers require the pre-stage artifact digest,
post-command staging digest, inspected normalized/created/started/post-oracle
no-egress topology, `sandbox_posture.host_fallback: false`, strict full profile,
and complete compose/export/image/workspace/input/synthesis cleanup. Block also
requires the bounded build, selected graph proof, combined execution-proof
digest, sandbox output cleanup, and scan-handoff cleanup. A missing, malformed,
`fail`, or `blocked` field is non-green. Neither adapter substitutes the
`adversarial-test` canary profile.

Blueprint repair is static-only. Its separate launch-readiness preflight and
browser smoke require Blueprint-specific landing and expected-text inputs; the
repair loop does not infer them from generated prose and does not silently
downgrade Blueprint runtime to static.

The tracked `wordpress-block-executor/smoke-wordpress-v1` fixture now declares
the reviewed `runtime_assertions` mapping for `acme/runtime-card`,
`.wp-block-acme-runtime-card`, and `Runtime block smoke`. That exact fixture is
eligible for the conditional block-runtime adapter. Other block fixtures remain
ineligible unless their own reviewed metadata supplies all three assertion
values; the adapter never borrows or infers them.

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
the isolated no-egress runtime. It executes only the staged destination, then writes only to the explicit
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

To provision and require the full disposable plugin runtime profile, including Composer-installed WPCS and Plugin Check inside `wp-env`, run:

```bash
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --provision-full-profile \
  --write \
  --run-id wp-env-runtime-full-profile-YYYYMMDD \
  --timeout-sec 300
```

For an external `--artifact-path`, use the canonical command above and include
the exact digest, evidence ID, and strict full-profile flag. Historical runs
without the current isolated contract are not current runtime evidence.

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

# Plan 009 generated-code runtime boundary

Generated plugin runtime certification has one entry point:
`wp_env_network_guard.run_staged_runtime()`. The input must be a factory-issued
`SYNTHESIZED_RUNTIME` stage with its Plan 008 evidence ID and artifact digest.
There is no host `wp-env`, host PHP, host Playwright, or ordinary-network
fallback. Missing Docker, an unverified pin, topology drift, inspection drift,
or incomplete cleanup produces `blocked` evidence.

The boundary has two phases. Trusted provisioning downloads only the committed
WordPress core and Plugin Check artifacts, verifies every recorded hash and OCI
platform digest, builds the repository-owned WordPress, database, and browser
images, and stops before the generated artifact exists in a container. The
generated phase exports the already-held staged bytes into a sealed local image
and creates a normalized, inspected Compose topology with five services:
database, WordPress, CLI, gateway, and browser.

Three internal bridge networks enforce the peer allowlist. Each uses Docker's
`com.docker.network.bridge.gateway_mode_ipv4=isolated` driver option, so the
host receives no bridge address. Live inspection requires that exact option,
an IPv4 subnet with no configured gateway, empty endpoint gateway fields, and
no default route inside the WordPress, CLI, or browser container. This mode
requires Docker Engine 28 or newer; older or unparseable daemon versions block
before image provisioning. Database,
WordPress, and CLI share `backend`; only WordPress/CLI can initiate required database traffic.
WordPress and gateway share `application`, where Apache binds only
`wordpress-application:8080`, allowing gateway-to-WordPress traffic while the
gateway listener is unavailable to WordPress. Gateway and browser share
`frontend`, where the gateway binds only `gateway-frontend:8081` for
browser-to-gateway traffic. Generated PHP therefore cannot turn loopback into
an application escape. No service receives host ports, external DNS,
`host.docker.internal`, the Docker socket, proxy variables, or an external
network. The browser policy permits the exact
gateway origin and rejects loopback, RFC1918, link-local/metadata, public IP,
public DNS, database-peer, host-gateway, WebSocket, WebRTC, service-worker,
popup, download, and external-navigation attempts from both frontend and editor
generated JavaScript. A bounded listener on the host's selected non-loopback
IPv4 address is attempted by generated PHP, a raw browser-network probe, and
both generated JavaScript contexts; any connection or queued accept fails the
gate. The listener address itself is not persisted in accepted evidence.

Every final service is non-root, drops all capabilities, uses
`no-new-privileges` and Docker's default seccomp profile, has a read-only root,
and has no bind or volume mount. Mutable paths are explicitly sized tmpfs
profiles with byte and inode ceilings. Each service has a 512 MiB memory and
memory-swap ceiling, 0.5 CPU, 128 PIDs, `nofile=1024`, `nproc=256`, and a 16 MiB
shared-memory ceiling. Daemon logging is `none`; every attached stream is
incrementally bounded and secret-scrubbed. Named generated-code canaries prove
ordinary database storage exhaustion and recovery, tmpfs byte/inode limits,
file/process/CPU limits, PHP and browser OOM handling, PHP/HTTP/browser output
ceilings, and deterministic service recovery. Evidence is accepted only after
exact image, identity, network, mount, tmpfs, resource, seccomp, and cleanup
inspection.

Run the hermetic producer/consumer and topology contracts without Docker:

```bash
python3 -m pytest \
  evals/harness/tests/test_isolated_runtime_contract.py \
  evals/harness/tests/test_wp_staged_runtime.py \
  -m 'not docker_boundary' -q
```

Run the exact pinned Linux runtime separately, once:

```bash
python3 -m pytest \
  evals/harness/tests/test_wp_staged_runtime.py \
  -m docker_boundary -q
```

The second command is a required no-secrets GitHub-hosted Linux gate. A local
macOS run reports blocked by design. A diagnostic run that substitutes an
available MariaDB image can help debug the harness, but it is not acceptance
evidence for the committed MariaDB 11.8.5 digest.

CI gives this gate a separate 35-minute job envelope. The runtime command is
causally terminated at 30 minutes, leaving cleanup time. The job admits only
with at least 20 GiB free and fails if the disk delta remains above 12 GiB after
run-owned containers, networks, and image tags are removed. That final measure
intentionally includes residual layers and build cache.

If a timed-out run reports retained resources, use the exact recovery commands
from its cleanup receipt. For a runner-level emergency cleanup, constrain the
operation to Plan 009 ownership markers:

```bash
docker ps -aq --filter 'name=^/wpisolated' | xargs -r docker rm -f
docker ps -aq --filter label=com.docker.compose.project | \
  xargs -r docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}} {{.Id}}' | \
  awk '$1 ~ /^wpisolated/ {print $2}' | xargs -r docker rm -f
docker network ls --format '{{.Name}} {{.ID}}' | \
  awk '$1 ~ /^wpisolated/ {print $2}' | xargs -r docker network rm
docker image ls --format '{{.Repository}}:{{.Tag}} {{.ID}}' | \
  awk '$1 ~ /^wp-isolated-(wordpress|database|browser|artifact):/ {print $2}' | \
  sort -u | xargs -r docker image rm -f
```

This boundary proves the tested isolation and resource controls for the exact
generated artifact and image set. It does not prove that generated application
behavior is benign, that untested WordPress integrations are correct, or that
a static/WPCS/Plugin Check pass is release readiness. Ordinary repository-owned
fixtures may still use their legacy feasibility path, but that path is not
evidence for generated-artifact runtime certification.
