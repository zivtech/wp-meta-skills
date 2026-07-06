# Deep Dive: Update-Safety Oracle - 2026-07-02

Target 1 from `docs/wordpress-assist-research-plan-2026-07-02.md`. Status:
research brief, not an approved spec. Web claims are marked [fetched] (page
retrieved) vs [snippet-only] (search snippet; host proxy-blocked during
research). Local repo facts were read directly from files.

Product shape: an open, vendor-neutral "update verdict" oracle — replay a
site's plugin updates in wp-env and emit a deterministic, machine-readable
evidence packet (activation, fatal-log diff, critical-page render checks).
Nothing open-source produces this today; every verdict-producing product is
proprietary and production-side.

## 1. Anatomy of update failure

| # | Failure class | Deterministic signal | Detectability |
|---|---|---|---|
| 1 | PHP fatal on update/activation | Non-zero exit from `wp plugin activate`/`update`; new `PHP Fatal error`/`Uncaught` lines in `debug.log`; front page HTTP 500; core fatal-error handler since 5.2 ([make.wordpress.org recovery mode](https://make.wordpress.org/core/2019/04/16/fatal-error-recovery-mode-in-5-2/) [snippet-only]) | High — exit codes + log grep + HTTP status |
| 2 | Deprecated/changed API on new WP/PHP | New `E_DEPRECATED`/`_doing_it_wrong`/"called incorrectly" lines diffed vs baseline. Precedent: WP 6.7 `_load_textdomain_just_in_time` notice hit WooCommerce, Rank Math, CF7, Yoast ([woocommerce#52435](https://github.com/woocommerce/woocommerce/issues/52435), [Woo dev advisory](https://developer.woocommerce.com/2024/11/11/developer-advisory-translation-loading-changes-in-wordpress-6-7/) [snippet-only]) | High for exercised code paths — notices fire only on rendered paths, so the critical-URL walk defines coverage |
| 3 | DB migration failure | New `WordPress database error` lines; plugin version-option mismatch (e.g. `wp option get woocommerce_db_version`); admin redirect to upgrade screen | Medium — generic signals deterministic; version-option checks need per-plugin manifest knowledge |
| 4 | JS breakage | Playwright console/pageerror listeners on critical URLs and editor — the repo's `--editor-smoke` already does exactly this | High for uncaught exceptions; exception-free logic bugs invisible |
| 5 | Layout/visual regression | Screenshot pixel diff (BackstopJS/pixelmatch) vs pre-update baseline with masks + threshold — the mechanism WP Umbrella/Kinsta/WP Engine sell | Medium/flaky — advisory, not blocking |
| 6 | Silent functional breakage (forms stop sending) | Per-declared-flow only: Playwright submits a manifest-declared form, asserts success marker; mail capture via mu-plugin hooking `wp_mail`/`phpmailer_init` | Low generically, high per declared flow — needs `flows[]` in manifest |
| 7 | Cron breakage | `wp cron event list --format=json` diff; `wp cron event run --due-now` exit + fatal check | High — fully machine-readable |
| 8 | Translation breakage | Class-2 notice diff | High as advisory |
| 9 | License/update-server issues | Mostly not replayable (premium updater phones home without license). Manifest must declare `unreplayable` | Low |
| 10 | REST/admin-ajax breakage | `GET /wp-json/` 200 + parseable JSON; admin-ajax heartbeat non-5xx; `wp-login.php` 200 | High |

Design consequence: classes 1, 2, 3, 7, 8, 10 are cheap and deterministic and
cover the white-screen/fatal/notice-storm work Codeable-tier debugging
concentrates on. Classes 4-5 need Playwright (already a repo dependency),
class 6 needs manifest-declared flows, class 9 is a documented boundary.

## 2. Existing tooling and the confirmed gap

- **WP Umbrella Safe Updates**: 7-step (compat check → restore point →
  pre-screenshot → update → HTTP 200 validation → screenshot compare →
  conditional rollback). Production-side, SaaS, proprietary, no
  machine-readable verdict ([features page](https://wp-umbrella.com/features/safe-updates/) [snippet-only]).
- **ManageWP Safe Updates**: restore point + before/after screenshots +
  auto-rollback on 4xx/5xx. Proprietary ([managewp.com](https://managewp.com/features/safe-updates/) [snippet-only]).
- **MainWP 5.1 rollback**: HTTP-status-only check, auto-restore on failure;
  GPL dashboard but no log diff, no VRT, no evidence packet
  ([mainwp.com KB](https://mainwp.com/kb/does-mainwp-have-safe-updates/) [snippet-only]).
- **WP Engine Smart Plugin Manager**: one-by-one updates, proprietary
  ML-driven VRT, auto-rollback with per-plugin attribution. Host-locked
  ([wpengine.com](https://wpengine.com/smart-plugin-manager/) [snippet-only]).
- **Kinsta automatic updates**: ScreenshotOne pixel comparison of homepage +
  4 sitemap pages, CSS masks, backup restore. Proprietary
  ([kinsta.com docs](https://kinsta.com/docs/wordpress-hosting/wordpress-plugins-themes/wordpress-plugins-themes-automatic-updates/) [snippet-only]).
- **Pantheon's open workflow**: the closest open pattern — Multidev update +
  [BackstopJS](https://github.com/garris/BackstopJS) (MIT) page compare with
  0%-tolerance blocking ([pantheon.io blog](https://pantheon.io/blog/automating-wordpress-core-and-plugin-updates-visual-regression-testing) [snippet-only]).
  Output is a CI failure, not a structured verdict.
- **wp doctor** ([wp-cli/doctor-command](https://github.com/wp-cli/doctor-command)
  [fetched]): configurable checks with `success/warning/error` + `--format=json`
  + custom YAML checks — the strongest open machine-readable primitive, but
  point-in-time health, not before/after update-diff semantics.
- **Core**: fatal handler + recovery mode (5.2), zip rollback when the update
  *process* fails ([WordPress/rollback-update-failure](https://github.com/WordPress/rollback-update-failure)
  [snippet-only]) — never when the updated code breaks the site.

**Gap confirmed:** no open-source tool produces a machine-readable
update-safety verdict with evidence. Verdict-producing products are all
proprietary, production-side, and check a strict subset of §1 (HTTP status +
screenshots; none diff fatal logs, cron, REST, or notices). The wire-format
vacuum is real.

## 3. The replay problem

Capture is fully machine-readable today: `wp plugin list --format=json`,
`wp theme list --format=json`, `wp core version`, `php -v`, `wp db export`,
`wp export` (WXR).

Replay tiers, in fidelity order:

1. **Plugin-set synthetic replay (recommended default)** — wp-env with the
   site's exact plugin slugs + pinned versions (`wp plugin install <slug>
   --version=<X>`; old zips at
   `https://downloads.wordpress.org/plugin/<slug>.<version>.zip`), pinned core
   (`"core": "WordPress/WordPress#6.7.1"`) and PHP (`"phpVersion"`),
   `WP_DEBUG_LOG` on, default content. Catches classes 1, 2, 3, 7, 8, 10 —
   essentially all PHP-level fatals and notice storms, where update breakage
   concentrates.
2. **+ options/content sample** — WXR sample or N representative pages so
   critical URLs render real templates; whitelisted options subset. Adds
   class 4/5 coverage.
3. **Full replay** — sanitized `wp db import` + wp-content rsync. Highest
   fidelity, heavy, PII-laden; opt-in tier only.
4. **Playground/SQLite pre-filter** — `@wp-playground/cli` + blueprint;
   cheapest (no Docker), but the [SQLite driver](https://github.com/WordPress/sqlite-database-integration)
   has documented plugin-activation SQL errors despite ~99% unit-suite pass
   ([new-driver announcement](https://make.wordpress.org/playground/2025/06/13/introducing-a-new-sqlite-driver-for-wordpress/)
   [snippet-only]), and PHP.wasm lacks real cron/mail semantics. Fast lane,
   never the verdict of record — matches the repo's existing
   Playground-vs-wp-env split.

Minimum viable fidelity = tier 1 + exact core/PHP pins + baseline log diffing.
Not replayable (manifest `unreplayable[]`): premium plugin update payloads
(user must supply zips), server config (object-cache drop-ins, PHP
extensions, real cron), external integrations, multisite/CDN/WAF.

## 4. Repo fit

The existing `evals/harness/run_wordpress_runtime_smoke.py` (2,286 lines)
already contains ~60% of the machinery: `CommandRun` dataclass,
`write_wp_env_config()`, `wp_env_cli_command()`, Playwright editor smoke,
pass/fail/**blocked** evidence semantics, `negative_space` lists, and
`write_result()` emitting `runtime-smoke.json` + `scorecard.md`.

**Recommendation: new sibling script**
`evals/harness/run_wordpress_update_safety_smoke.py`, importing shared
helpers. The lifecycle differs fundamentally: current harness is
*provision → check once*; the oracle is *provision → baseline capture →
mutate (update) → re-check → diff*. Proposed flags:

```
--site-manifest <manifest.json>        # plugins/theme/core/php/critical URLs/flows
--update-plugin <slug>                 # repeatable
--update-zip <slug>=<path.zip>         # premium/unlisted update artifacts
--critical-url <path>[=<expected-text>]
--visual-diff / --strict-visual
--content-mode {none,sample,full}
--db-dump <path>  --wxr <path>
--workdir / --keep-running / --timeout-sec / --write / --run-id
```

Evidence packet `update-verdict.json` mirrors `runtime-smoke.json`'s shape
(`status`, `pass`, `generated_at`, `commands`, per-gate `{id, status, detail}`
checks, `negative_space`) and deliberately matches the `certify_fn` return
contract in `run_executor_repair_loop.py` (`{"passed", "failing_gates",
"failures", "gate_vector"}`) so verdicts plug into `orchestrate()` and the
`repair-prompt.md` pattern unchanged. Sketch:

```json
{
  "status": "fail", "pass": false, "replay_tier": "plugin-set",
  "wp_core_version": "6.7.1", "php_version": "8.1",
  "updates_requested": [{"slug": "...", "from_version": "...", "to_version": "...", "source": "wporg|zip"}],
  "baseline": {"plugins": [], "cron_events": [], "urls": []},
  "gates": {
    "update_applied":  {"status": "pass"},
    "site_liveness":   {"status": "pass"},
    "fatal_log_diff":  {"status": "fail", "new_fatal_lines": ["PHP Fatal error: ..."]},
    "notice_log_diff": {"status": "advisory", "count": 3},
    "db_error_diff":   {"status": "pass"},
    "critical_urls":   {"status": "pass"},
    "rest_admin_ajax": {"status": "pass"},
    "cron_diff":       {"status": "pass"},
    "visual_diff":     {"status": "advisory"}
  },
  "failing_gates": ["fatal_log_diff"],
  "gate_vector": {"fatal_log_diff": "fail"},
  "negative_space": ["not a production-parity proof", "not premium-license update proof",
                     "not declared-flow functional proof", "not server-config proof"]
}
```

New suite dir `evals/suites/wordpress-update-safety/`; runbook gains an
"Update-Safety Gate" section.

## 5. Gate sequence

0. Provision replay — failure = `blocked`, never `fail`.
1. Baseline capture: plugin list, debug.log snapshot, cron list, front page +
   critical URLs (HTTP status, expected text, console errors, screenshot),
   `/wp-json/`. URLs already failing at baseline downgrade to no-regression
   semantics.
2. Apply update (`wp plugin update --version=` or `--update-zip`). Gate
   `update_applied` blocking.
3. Activation/liveness (blocking): plugin still active; `wp eval 'echo "ok";'`
   exits 0; front page < 500.
4. Fatal/DB log diff (blocking); notice/deprecation diff (advisory, verbatim
   lines included).
5. Critical URL checks (blocking for status regression, missing expected
   text, new uncaught JS exceptions; advisory for console warnings).
6. REST/admin-ajax/admin health (blocking), optional Playwright wp-admin
   login reusing the editor-smoke login path.
7. Cron diff (blocking if `--due-now` run fatals; advisory for event-set
   changes — plugins legitimately change events on update).
8. Visual diff (advisory by default; blocking only under `--strict-visual`,
   with per-URL `mask_selectors` and `diff_threshold` from the manifest).
9. Verdict: `pass` = all blocking gates pass; `fail` with `failing_gates`
   attribution; `blocked` = provisioning gap.

## 6. Skill surface

- **`wordpress-update-safety-executor`** — operates the oracle. Input: a site
  manifest (`wp_core_version`, `php_version`, `plugins[{slug, version,
  source, update_to, zip_path?}]`, `theme`, `critical_urls[{url,
  expected_text, mask_selectors[], diff_threshold?}]`, `flows[]?`,
  `unreplayable[]`), generated from one WP-CLI capture command the skill
  teaches. Output: the exact harness invocation, interpretation of
  `update-verdict.json`, and on `fail` a repair-guidance packet (which
  plugin/gate failed, verbatim fatal lines, remediation commands: hold/pin
  via `wp plugin update <slug> --version=<from>`, hotfix snippet for known
  classes, "contact vendor + hold" for premium).
- **`wordpress-update-safety-critic`** (or an update-verdict review mode on
  `wordpress-critic`) — read-only reviewer: claims must not exceed
  `negative_space`, advisories must not be silently dropped, blocked ≠ pass.
- Claims discipline: a green verdict proves "this update, in this replay
  tier, at these pins, on these URLs" — not production-parity.

## 7. Fixture plan (`evals/suites/wordpress-update-safety/fixtures/`)

1. **`clean-update`** (real, pinned — expected `pass`): e.g. Akismet
   `--version=5.3` → `5.3.1`; both zips cached in-repo/CI against wp.org
   removals. Proves no false positives.
2. **`fatal-on-update`** (synthetic — expected `fail` on `fatal_log_diff` +
   `site_liveness`): fixture plugin `acme-update-fatal` with two checked-in
   zips — v1.0.0 clean, v1.1.0 throwing an uncaught exception on
   `plugins_loaded`. Deterministic forever; doubles as the rollback-guidance
   eval case.
3. **`conflict-pair`** (synthetic core + real advisory companion):
   (a) `acme-conflict-a` v1 defines `function acme_shared_helper()`; the
   update to `acme-conflict-b` v2 redeclares it unconditionally → fatal only
   when both are active — the canonical two-plugin conflict, with attribution
   to the `acme-conflict-b` update step. (b) Real advisory companion: pin a
   pre-advisory WooCommerce on WP ≥ 6.7 to deterministically produce the
   `_load_textdomain_just_in_time` notice → expected `pass` with non-empty
   advisories, proving the advisory channel fires without blocking.
   Synthetic-first rationale: real fatal-conflict version pairs are unstable
   fixtures; the synthetic pair pins the failure class, not the incident.

## 8. Effort, risks, open questions

**Phases:** P1 manifest schema + provision/baseline/update/liveness/log-diff
gates + verdict writer (already exceeds MainWP/ManageWP check depth). P2 URL +
console + REST/cron/db gates. P3 advisory visual diff. P4 fixtures + eval
suite + skill surface + repair-loop integration. P5 capture-side docs +
runbook section.

**Risks:** Docker/wp-env dependency (accepted repo tradeoff; `blocked` status
+ Playground pre-filter lane); premium plugins (user-supplied zips, never
committed to this Apache-2.0 repo; partial-coverage representation needed);
visual-diff flakiness (advisory-by-default, masks, fixed viewport); fixture
rot (cache zips); runtime cost (wp-env start 1-3 min; 20-30 plugins ×
sequential verdicts is tens of minutes — batching strategy matters).

**Open questions for maintainers:**

1. Attribution vs speed: per-plugin sequential updates (precise blame, slow)
   or batch-with-bisect-on-fail as default? Shapes the flag surface and
   packet schema.
2. Data boundary: is the plugin-set synthetic tier the default verdict of
   record (no site content leaves the site), with sample/full replay strictly
   opt-in? Decides whether the manifest schema needs PII/sanitization
   guidance from day one.
3. Standardization ambition: publish `update-verdict.json` as a versioned
   JSON Schema (`"schema_version": 1`) so third parties (MainWP extensions,
   CI actions) can emit/consume it — in this repo or a spec-only repo?
