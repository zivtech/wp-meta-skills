# Deep Dive: WordPress API-Existence & Deprecation Lint - 2026-07-02

Target 5 from `docs/wordpress-assist-research-plan-2026-07-02.md`. Status:
research brief, not an approved spec. Legend: [fetched] = page/file
retrieved; [data-verified] = raw data downloaded and inspected;
[snippet-only] = search snippet; [local] = read from this repo.

Headline finding, source-verified: the closest existing tool,
[johnbillion/wp-compat](https://github.com/johnbillion/wp-compat) (MIT,
PHPStan extension, data current for WP 7.0), **silently skips unknown
symbols and unknown hook names** (`if ( ! isset( $this->symbols[$name] ) )
return [];` in `src/Rules/SinceVersionRule.php` [fetched]) and only inspects
`add_action`/`add_filter`, not `do_action`/`apply_filters`. Hallucination
detection — the AI-era failure mode — is exactly the check nobody ships.

## 1. Symbol-database sources

- **php-stubs/wordpress-stubs** [fetched]: core functions/classes/interfaces,
  generated from source; **tags match WP releases** (latest 7.0.0, May 2026);
  MIT; preserves `@since`/`@deprecated` docblocks; no hooks, no globals.
  (php-stubs/wordpress-globals is "born deprecated" — do not build on it.)
- **szepeviktor/phpstan-wordpress** [fetched]: MIT, PHPStan 2.0+, active.
  Adds dynamic return types, `apply_filters()` docblock inference, core
  constants, HookDocsRule (validates docblocks where hooks are *defined*).
  **Does not validate hook names passed to `add_action`/`add_filter`** —
  README-confirmed.
- **wp-hooks/wordpress-core** [data-verified]: `hooks/actions.json` +
  `hooks/filters.json` — **728 actions + 1,844 filters (2,572 hooks), 239
  dynamic names** with interpolation placeholders
  (`save_post_{$post->post_type}`). Per-hook `doc.tags` carry `since` and
  `param` (→ arg counts). Semver releases map to WP versions (1.12.0 = WP
  7.0). Regenerable via [wp-hooks/generator](https://github.com/wp-hooks/generator)
  [fetched]. **License GPL-3.0 — see §8.** Deprecated hooks are absent from
  the JSON (verified: 0 hooks from `deprecated.php`) — deprecated-hook data
  must come from a core scrape.
- **johnbillion/wp-compat** [data-verified]: `symbols.json` = **7,776
  symbols (3,969 functions + 3,807 methods) with `since`** (probes:
  `get_template_hierarchy → 6.1.0`, `wp_register_ability → 6.9.0`). Reads
  `Requires at least` from plugin headers; respects `function_exists()`
  guards. Hook since-data comes from wp-hooks ^1.12 (composer.json verified).
- **WooCommerce**: [php-stubs/woocommerce-stubs](https://github.com/php-stubs/woocommerce-stubs)
  [fetched] tags track WC releases (latest v10.9.1, June 2026, MIT).
  **A WooCommerce hooks JSON does not exist publicly** — running
  wp-hooks/generator over each WC source tag becomes a small owned build
  artifact.
- **Deprecation data**: WPCS `WordPress.WP.DeprecatedFunctionsSniff`
  [fetched raw]: hardcoded arrays `'name' => ['alt' => 'replacement()',
  'version' => 'x.y.z']` (e.g. `wp_login → wp_signon()` 2.5.0), complete
  through WP 6.9.0-RC2; sibling sniffs DeprecatedClasses/Parameters/
  ParameterValues. Core's `deprecated.php` files +
  `apply_filters_deprecated()`/`do_action_deprecated()` callsites are ground
  truth for deprecated hooks. PHPStan route:
  `phpstan/phpstan-deprecation-rules` + stubs' `@deprecated`.
- WP-Parser (official code-reference parser) outputs WordPress CPT entries,
  not a data file — wrong shape for a lint DB [fetched].

## 2. Coverage matrix

| Hallucination class | PHPStan+stubs | wp-compat | WPCS | @wordpress/eslint-plugin | Gap |
|---|---|---|---|---|---|
| Nonexistent PHP function/class | ✅ level 0 | skipped | ❌ | — | covered — wire it in |
| **Nonexistent hook name** (add_action/do_action/apply_filters) | ❌ | ❌ silently ignored (source-verified) | ❌ | — | **NOVEL — nothing ships this** |
| **Wrong hook arg count** (`add_action('save_post', $cb, 10, 5)` vs `args: 3`) | ❌ | ❌ | ❌ | — | **NOVEL** (`args` exists in hooks JSON) |
| Hook newer than Requires header | ❌ | ✅ core only | ❌ | — | Woo + do_action callsites missing |
| Function newer than Requires header | ❌ | ✅ core only | ❌ | — | Woo missing |
| Deprecated function w/ replacement | ✅ (no replacement text) | ❌ | ✅ incl. replacement, min-version-aware | — | covered |
| **Deprecated hook** | ❌ | ❌ | ❌ | — | **NOVEL** (needs `apply_filters_deprecated` scrape) |
| Hallucinated REST route/option name | ❌ | ❌ | partial (caps sniff) | — | mostly site-defined — out of scope, say so |
| Hallucinated `@wordpress/*` import/export | — | — | — | ❌ (only `no-unsafe-wp-apis` prefixes) | gap; TS types incomplete — advisory tier |

## 3. The novel checks

New module `evals/harness/wp_api_lint.py` (importable + CLI), consuming a
compiled symbol DB:

- **(a) Hook existence**: extract string-literal first args of
  `add_action|add_filter|do_action(_ref_array)?|apply_filters(_ref_array)?`
  → lookup → `unknown_hook` finding with deterministic fuzzy suggestion
  (`difflib.get_close_matches`; verified on real data:
  `wp_enqueue_script_loader → wp_enqueue_scripts`). Dynamic handling:
  artifact-side interpolation/concatenation → advisory; DB-side dynamic
  patterns stripped to prefixes and prefix-matched (verified:
  `save_post_product` maps to the `save_post_{$post->post_type}` family).
  Hooks the artifact itself defines + slug-prefixed hooks go on an
  allowlist first.
- **(b) Function/class/method existence + version range**: symbol set =
  wordpress-stubs ∪ woocommerce-stubs ∪ PHP builtins ∪ artifact-defined;
  `since` from wp-compat symbols.json (core) + generated Woo data; compare
  against `Requires at least:` / `WC requires at least:`; respect
  `function_exists()` guards. Phase-1 shortcut: subprocess
  `phpstan --error-format=json` with stubs + wp-compat — existence and core
  range come free.
- **(c) Deprecation-with-replacement**: compile the WPCS deprecation arrays
  into the DB; findings cite the exact successor. Deprecated hooks via a
  one-time scrape of `apply_filters_deprecated()` callsites in pinned
  wp-develop.
- **(d) JS side (phase 3, advisory)**: `import`s from `@wordpress/<pkg>`
  checked against the finite npm package list (~90); named-export existence
  from installed packages' `.d.ts` when `node_modules` exists in the runtime
  profile. Full type-level selector checking deferred.

Finding schema aligns with the existing `Check` dataclass (flows through
`feedback_items` unchanged): per-finding `class` (`unknown_hook |
unknown_function | version_range | deprecated_api | deprecated_hook |
hook_arg_count | unknown_js_package`), `symbol`, `file`/`line`,
`confidence: exact|advisory`, `declared_range`, `introduced_in`,
`deprecated_in`, `replacement`, `suggestions[]`, `evidence`, and DB snapshot
versions.

## 4. Version pinning

Key insight: **one latest snapshot with `since` metadata answers both
checks** — "exists at all" (hallucination) and "exists only since X >
declared minimum" (range). N historical snapshots are only needed for
"existed then, removed now" — rare, covered by the WPCS deprecation lists +
a removed-symbols diff. Scheme: `scripts/build-wp-symbol-db.py` compiles a
single facts-only `evals/harness/data/wp-symbols-<wp>-<wc>.json` from pinned
inputs; commit the snapshot; a scheduled CI staleness check fails when
upstream tags advance (mirrors the meta-router stale-artifact pattern).
Declared range resolves as `[Requires-at-least, snapshot version]`.

## 5. Repo fit [local]

- `scripts/validate-wordpress-exact-api-contract.py` — confirmed: validates
  **prompts and rubrics, not code**, via ~40 hand-listed contract tokens +
  shape regexes. The shape regex `^[a-z][a-z0-9_]+$` would accept a
  hallucinated snake_case name — it validates form, not existence.
- `evals/harness/validate_wordpress_artifact.py` — already contains a
  hand-rolled micro-wp-compat: the AI-surface heuristics version-gate
  `wp_register_ability`/`wp_ai_client_prompt` via `_declares_wp_minimum()` +
  `_has_function_exists_guard()`. The general gate replaces this pattern.
- **Slot-in**: add `check_api_existence()` to `structural_checks()` for
  `plugin|block|theme` — static profile, no network, reads the committed
  snapshot, `blocked` if the snapshot is missing (fail-closed like the phpcs
  gate). Optionally `--require-tool phpstan-wp` in `runtime_checks()`.
  Findings flow with zero changes through
  `certify_wordpress_executor_artifact.py` → `feedback_items()` →
  `repair-prompt.md` → the repair loop delivers "Unknown action
  `wp_enqueue_script_loader` — did you mean `wp_enqueue_scripts`?" straight
  to the model. Full findings to `api-lint.json` beside `certification.json`.

## 6. The flywheel

Today's exact-API enforcement is three hand-maintained lists + shape
regexes, and rubric `expected_wordpress_apis` entries are never checked for
real existence. With the symbol DB: `is_exact_surface()` gains an existence
lookup with nearest-match suggestions, rubric entries get certified as real
APIs, contract tokens get freshness-checked (`deprecated_in`?), and the same
`difflib` matcher powers a did-you-mean assist in the repair prompt and any
critic runtime. One DB, three consumers — replacing hand-maintenance with a
rebuildable snapshot.

## 7. Fixture plan

1. **`api-hallucination-bait`**: plugin calling `wp_sanitize_email_address()`
   (nonexistent; near `sanitize_email()`) and hooking
   `wp_enqueue_script_loader` (nonexistent; verified nearest-match →
   `wp_enqueue_scripts`). Exactly two findings, each with ≥1 suggestion;
   repair loop green ≤2 repairs.
2. **`version-range-bait`**: header `Requires at least: 6.0` +
   unconditional `get_template_hierarchy()` (since 6.1.0, verified).
   `version_range` finding naming `introduced_in`; adding a
   `function_exists()` guard or bumping the header must flip it green
   (tests guard logic both ways).
3. **`deprecation-pair`**: clean variant calls `wp_signon()`/`get_terms()`
   → zero findings (false-positive control); bait variant calls
   `wp_login()`/`get_all_category_ids()` → `deprecated_api` with
   `deprecated_in: 2.5.0/4.0.0` and `replacement` verbatim (data verified in
   WPCS sniff source).

## 8. Effort, risks, maintainer questions

**Phases:** P1 (days): PHP existence + core version-range = subprocess
phpstan + stubs + wp-compat, parse JSON into the finding schema; fixtures
1a/2. P2 (~1 wk): hooks DB — compiled snapshot, unknown-hook + fuzzy +
dynamic-prefix + arg-count, deprecation lists; fixtures 1b/3. P3:
WooCommerce data artifact (generator per WC tag) + JS package/export
existence (advisory).

**Risks:**
- *Dynamic-hook false positives*: 239/2,572 core hook names are
  interpolated; artifact-side dynamic first-args degrade to advisory;
  third-party hooks (`woocommerce_*` before P3) must be advisory outside
  known namespaces or the gate torches legitimate integrations. Fixture 3's
  clean control is the guard.
- *DB freshness*: four upstreams on different cadences — single compiled
  snapshot + staleness CI contains it, but it's a standing chore. Upstream
  sustainability: php-stubs and szepeviktor both signal sponsorship
  concerns [fetched].
- *Licensing*: **wp-hooks JSON is GPL-3.0; this repo is Apache-2.0 with a
  conservative reuse policy.** Safe path: facts-only compiled snapshot (hook
  names, versions, arg counts are uncopyrightable facts; strip GPL docblock
  descriptions) + fetch-at-build-time deps, documented per
  `docs/wordpress/license-reuse-policy.md` with a reuse-ledger entry.
- *Scope honesty*: REST routes/option names/most capabilities are
  site-defined — out of scope, stated as negative space.

**Maintainer questions:**
1. License posture: facts-only derived snapshot from GPL-3.0 wp-hooks
   committed under Apache-2.0, or fetch-at-build-time with `blocked`
   offline?
2. Does "static profile = stdlib-only" remain a hard invariant (native
   snapshot lookups), or may P1 shell out to PHPStan+wp-compat?
3. Unknown-hook default severity: fail with an allowlist knob, or
   advisory-until-Woo-data-lands?
