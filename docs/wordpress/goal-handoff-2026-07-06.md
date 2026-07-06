# Goal Handoff - 2026-07-06

State snapshot for the next working session. Continues
`docs/wordpress/goal-handoff-2026-07-02.md` (read that first for the prior
state). The first 2026-07-06 session reconciled project status and implemented
verification roadmap target #2 (the security gate) up to the PHP-certification
boundary. A continuation pass in a PHP-capable environment finished the
certification work and moved plan 005 to **DONE**. A later continuation merged
that work, tracked the `.agents`/`.codex` registry surfaces on `main`, and
started and merged the P2 security-critic consumption branch.

## 0. Orient first

- **Current branch:** `main`, tracking `origin/main`; run
  `git log -1 --oneline` for the exact current HEAD.
- **Merged state:** PR #2 is merged (`bdfbd1e`), agent registry tracking landed
  in `18e24c0`, and PR #3 is merged (`12c7afe`) with P2
  `security-gate.json` critic consumption.
- **Current branch purpose:** continue from a clean `main`; the next build item
  is the WooCommerce static scanner (#3).
- **Nothing is running.** No background jobs.
- **Continuation environment:** Python 3.13.9, PHP 8.5.5, Composer 2.9.7. The
  earlier no-PHP/Python 3.10 limitation is historical context only; this pass
  exercised the real WPCS toolchain locally.

## 1. Where things stand (the reconciliation)

Full writeup: `docs/wordpress/project-status-2026-07-06.md` (new this session).
Summary of the three workstreams:

- **Public release** — publishable, held only by owner decisions (history-scrub
  strategy, issue #1 sign-offs, enable private vuln reporting). GPL-3.0
  relicense landed in remote commit `0347cb1`.
- **Improvement plans 001–004** — all DONE (`plans/README.md`).
- **Verification-targets roadmap** — item #1 (API-existence lint) shipped in
  `88de9a9`; **item #2 (security gate) is DONE on `main`** via PR #2; P2
  security-critic consumption is DONE on `main` via PR #3; items #3–#5 are not
  started. Order and decisions:
  `docs/wordpress/verification-targets-decisions-2026-07-02.md`.

## 2. What shipped to the working tree this session

**New files:**

- `evals/harness/wp_security_gate.py` — the gate module (static profile).
- `evals/harness/tests/test_wp_security_gate.py` — 20 tests after continuation:
  hermetic parse/diff/classify/schema tests plus real-toolchain integration and
  sniff-inventory coverage (marked `real_security_gate` + skip without WPCS).
- `evals/harness/tests/fixtures/wp_security_gate/` — 4 clean-room fixtures
  (`suppression-abuse`, `prepared-escaped`, `broken-access-control`,
  `clean-control`) + `README.md` + `SCHEMA.md`.
- `docs/wordpress/project-status-2026-07-06.md` — the status reconciliation.
- `docs/wordpress/goal-handoff-2026-07-06.md` — this file.

**Modified (tracked source):**

- `evals/harness/validate_wordpress_artifact.py` — `import wp_security_gate`;
  `check_security_gate(path, timeout_sec)` (mirrors `check_api_existence`);
  registered in `structural_checks` after the api-existence block; surfaced onto
  the result next to `api_lint` (the `if "api_lint" in extras` block).
- `evals/harness/certify_wordpress_executor_artifact.py` — `security-gate.json`
  sidecar in `write_results`, mirroring the `api-lint.json` write; scorecard now
  surfaces `Security gate: ...` and no longer says static passes cannot prove
  WPCS.
- `evals/harness/php-tools/composer.json` + `composer.lock` — exact-pinned
  `squizlabs/php_codesniffer 3.13.5`, `wp-coding-standards/wpcs 3.3.0`,
  `phpcsstandards/phpcsutils 1.2.2`, and `phpcsstandards/phpcsextra 1.5.0`.
- `evals/harness/tests/conftest.py` — the autouse fixture now stubs **both**
  `check_api_existence` and `check_security_gate` to `skip`, each **independently
  gated on its own marker** (`real_api_lint` / `real_security_gate`), so neither
  gate's integration tests perturb the other's.
- `.github/workflows/validate.yml` — added `test_wp_security_gate.py` to the
  pytest bundle (after `test_wp_api_lint.py`).

**Gitignored working docs (`/plans/` — won't appear in `git status`):**

- `plans/005-security-gate-static-profile.md` — the executor-ready plan, updated
  to the certified `WordPress` standard and runtime `installed_paths` proof path.
- `plans/README.md` — 005 row moved to DONE + footnote ² updated with proof.

## 3. The security gate — design as built

`wp_security_gate.py`, schema `wordpress-security-gate/v1`
(`SCHEMA="wordpress-security-gate"`, `SCHEMA_VERSION=1`):

- Runs phpcs `--standard=WordPress` restricted to the seven selected
  security/DB sniffs,
  `--report=json`, **twice**: normally and with `--ignore-annotations`.
- **Suppression differential:** violations present only under
  `--ignore-annotations` were hidden behind `// phpcs:ignore`; a
  security-relevant one that reappears is a hard fail (the "SQLi behind a phpcs
  suppression" AI-codegen failure mode).
- **Status split (decision #6):** hard `fail` on `WordPress.DB.Prepared*` /
  `WordPress.Security.EscapeOutput` **errors** or a reappearing security-relevant
  suppression; everything else is advisory evidence carried for the critic;
  `blocked` when phpcs/WPCS absent; `skip` when no PHP files.
- Canonical `get_block_wrapper_attributes()` suppressions are recorded as
  reviewed safe WordPress-helper evidence (`reviewed_safe_api`) rather than a
  hard fail; this is narrow exact-API handling, not a blanket
  `EscapeOutput` suppression allowlist.
- Pure, hermetically-tested core (`parse_phpcs_output`, `diff_suppressions`,
  `classify`, `summarize_report`) + a thin subprocess orchestrator
  (`run_security_gate`) + CLI. Scans the explicit file list from
  `iter_php_files` (artifact-relative exclusion) rather than dir+`--ignore`
  globs, so fixtures under a `tests/` ancestor are not wrongly skipped.

## 4. Verification state (what was actually confirmed)

- Full harness suite: **212 passed** after rebasing on API-lint phase 2.
  - `python3 -m pytest evals/harness/tests/ -q`
- `wp_security_gate.py` focused suite: **20 passed**.
  - `python3 -m pytest evals/harness/tests/test_wp_security_gate.py -q`
  - Includes a real-toolchain sniff inventory test proving the configured
    `WordPress` standard registers all seven selected sniffs.
- Real fixture results:
  - `suppression-abuse` → `fail` on reappearing
    `WordPress.DB.PreparedSQL.InterpolatedNotPrepared` suppression, with
    advisory `WordPress.DB.DirectDatabaseQuery.*` findings.
  - `prepared-escaped`, `broken-access-control`, `clean-control` → `pass`
    (direct-query/caching advisories are allowed evidence for the critic).
- Golden regression: all **8 plugin/block materializable examples** certified
  with `security_gate=pass`.
  - The Interactivity block's `get_block_wrapper_attributes()` suppression is
    preserved as reviewed exact-API evidence (`reviewed_safe_api:
    "get_block_wrapper_attributes"`) and no longer hard-fails the gate.
- Composer/toolchain:
  - `composer require --no-interaction squizlabs/php_codesniffer:3.13.5
    wp-coding-standards/wpcs:3.3.0 phpcsstandards/phpcsutils:1.2.2
    phpcsstandards/phpcsextra:1.5.0` resolved and regenerated the lock.
  - Bare `vendor/bin/phpcs -i` does **not** list WordPress standards because
    `allow-plugins: false` disables installer auto-registration; the certified
    proof path is the gate's explicit `--runtime-set installed_paths ... -i`.
  - `composer validate --strict` exits non-zero only because the repo
    intentionally uses exact pins (same warning applies to pre-existing pins).
- `MANIFEST.sha256` does **not** track harness `.py`, so `install.sh --verify`
  is unaffected by these edits (confirmed: 0 matches for `evals/harness`).
- One real bug was found and fixed mid-session: `iter_php_files` had been
  excluding by absolute path parts, which dropped fixtures living under a
  `tests/` ancestor (returned `skip`); switched to artifact-relative parts.
- Continuation fixes from subagent review:
  - Switched from `WordPress-Extra` (5 registered sniffs) to `WordPress` (all 7
    selected sniffs), with a regression test.
  - Added command evidence, `source_excerpt`, `reviewed_suppressed`, and stronger
    sidecar assertions.
  - Mapped downstream `skip` to `skip_check` instead of required pass.

## 5. Remaining work after DONE

Plan 005 is DONE on `main`. P2 is DONE on `main`: `wordpress-security-critic`
consumes `security-gate.json`, requires suppression-review notes,
`validate_wordpress_skill_output.py` accepts optional `--security-gate`, and
the focused `security-gate-consumption-v1` fixture/rubric/sidecar is present.
`run_wordpress_high_risk_saved_outputs.py` auto-detects
`fixtures/<fixture>.security-gate.json` for contract validation. Fresh
saved-output runs are still needed before the new fixture can be included in
score claims.

## 6. Historical commit grouping

- `feat(harness): add WordPress security gate static profile (security_gate)` —
  `wp_security_gate.py`, the `validate_wordpress_artifact.py` +
  `certify_wordpress_executor_artifact.py` wiring, `conftest.py`,
  `php-tools/composer.json` + `composer.lock`, the fixtures,
  `test_wp_security_gate.py`, and the `validate.yml` pytest line.
- These security-gate groups have been merged through PR #2 and PR #3.

## 7. Blockers before the public visibility flip (unchanged from 2026-07-02)

1. History-scrub strategy (squash-reimport or `git filter-repo`) — the real
   blocker; redacted content still lives in early staging commits.
2. Enable GitHub private vulnerability reporting; issue #1 sign-offs; post-flip
   CI then tag.
3. skills.sh registration is queued but not done: keep `skills.sh.json`, confirm
   `DISABLE_TELEMETRY=1 npx -y skills add ./ --list` reports all 14 skills in
   the generated package, then after the repo is public run `npx skills add
   zivtech/wp-meta-skills` without telemetry opt-out, verify the skills.sh repo
   page, and only then add the README badge.

## 8. Next build work (decided order)

1. Rerun saved outputs for `security-gate-consumption-v1` before including it
   in score claims.
2. WooCommerce static scanner (`scan_woocommerce_transition.py`) — #3.
3. Update-safety oracle (`run_wordpress_update_safety_smoke.py`) — #4.
4. Builder→blocks verifier (flagship, fourth executor kind) — #5. Needs the
   licensed WPBakery/Divi zips (purchased 2026-07-02, supplied by flag, never
   committed — confirm the WPBakery zip is downloaded before this phase).

## 9. Gotchas

- `/plans/` is gitignored (`.gitignore:10`) — plans 001–005 and `plans/README.md`
  are local-only working docs and never show in `git status`. That is by design.
- A stale 0-byte `.git/index.lock` appeared mid-session (sandbox mount quirk) and
  was removed; if git commands complain about a lock, `rm -f .git/index.lock`.
- Web research from this sandbox is snippet-limited for most non-GitHub hosts;
  re-verify any snippet-only stat before quoting it externally.

## 10. Orientation for a fresh session

Read: `docs/wordpress/project-status-2026-07-06.md` → this handoff →
`plans/005-security-gate-static-profile.md` →
`docs/wordpress/deep-dive-security-gate-triage-2026-07-02.md`. Evidence
semantics: `docs/wordpress/runtime-oracle-runbook.md`; validation bundle:
`SECURITY.md`.
