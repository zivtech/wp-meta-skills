> **Superseded:** This dated snapshot is historical. See the
> [current project status](project-status-current.md).

# Project Status — 2026-07-06

A single reconciled snapshot of where `wp-meta-skills` stands, pulling together
the three parallel workstreams that the dated docs describe separately. Written
for a maintainer (or a fresh session) picking the repo back up.

## One-line position

The repo is **publishable and validated**, held only by owner decisions; the
internal improvement plans (001–004) are **all landed**; and the post-release
build direction — a roadmap of five deterministic verification gates — has its
**first two gates plus the P2 critic-consumption follow-up landed on `main`**:
API-existence lint, the WPCS-backed security gate static profile, and
`wordpress-security-critic` consumption of `security-gate.json`. Roadmap target
#3 is next.

## Branch / commit state

- `main` / `origin/main` includes `f8104dd docs(wordpress): align security gate
  status docs`; run `git log -1 --oneline` for the exact current HEAD.
- PR #2 merged the public-readiness/security-gate work at `bdfbd1e`.
- `18e24c0 chore(agents): track WordPress Codex registries` tracks the
  `.agents` and `.codex` registry surfaces on `main`.
- PR #3 merged P2 security-critic consumption of `security-gate.json`.
- Other historical branches may still exist, but the public-readiness/security
  gate work from `claude/wp-meta-skills-public-readiness-fjr0d1` is merged.

## Workstream A — Public release readiness

Per `docs/public-readiness-review-2026-07-02.md`: **publishable after one
decision.** As of that review, the tree was clean (no secrets, no copied
third-party text), name cleared (`wp-meta-skills` slug kept; README retitled
"WP Meta Skills"), and every locally runnable gate green. The current checkout
is clean on `main` after PR #3. Remaining items are
**owner sign-offs, not engineering:**

1. **Git-history strategy — the real blocker.** Redactions fixed the working
   tree, not history: personal paths shipped in the initial import commit
   `8798b2e`, and an unrelated-plugin stderr leak entered at `c93851c`. Going
   public as-is would expose the pre-redaction content across all 41 staging
   commits. Two clean options, both matching `PROVENANCE.md`: (a)
   squash-reimport the scrubbed tree as a fresh root commit, or (b) rewrite with
   `git filter-repo`. Must be done before the visibility flip.
2. **GPL-3.0 relicense.** Completed by `0347cb1` before public release.
3. Enable GitHub private vulnerability reporting when public; owner sign-offs
   tracked in issue #1; run CI on the public repo, then tag.
4. **skills.sh registration is a post-public step, not yet a claim.** A root
   `skills.sh.json` is now staged for the future repo page, and the release
   checklist records the required post-public `npx skills add
   zivtech/wp-meta-skills` telemetry step, page verification, and README badge
   timing.

The history rewrite acts on the staging repo; remaining sign-offs are owner
decisions.

## Workstream B — Improvement plans 001–004

All four **DONE** (`plans/README.md`): CI now gates the repair-loop test with a
reproducible pinned Python env (001); the repair loop sees full failures with
cleaner feedback, the Gemini key moved to a header, and a phpcbf pass was added
(002); host-exec sandbox isolation + ability-eval injection fix (003); and the
standalone-extraction leftovers (broken links, duplicate doc, phantom paths,
harness README) were finished (004). Residual LOW items (SEC-03, BUG-02/03/04,
TEST-02/03, the documented-broken `--mode executor` path) were explicitly
**considered and parked**, recorded in `plans/README.md` so they are not
re-audited.

## Workstream C — Verification-targets roadmap (the live frontier)

The 2026-07-02 research (`docs/wordpress-assist-research-plan-2026-07-02.md`)
found the ecosystem saturated with AI *generators* and essentially devoid of
*verifiers* — the exact planner→executor→critic + deterministic-gate shape this
repo already has. Alex answered all 12+ build questions in
`docs/wordpress/verification-targets-decisions-2026-07-02.md`, fixing this order:

| # | Target | Status | Notes |
|---|--------|--------|-------|
| 1 | API-existence lint (`wp_api_lint.py`) | **DONE** (`88de9a9`) | PHPStan L0 + wordpress-stubs 7.0.0 + wp-compat 1.5.0; wired as required `api_existence` structural check; fixtures + 16 tests; all 8 golden examples pass the real gate |
| 2 | **Security gate static profile** | **DONE on `main`** (merged via PR #2) | PHPCS security sniffs + `--ignore-annotations` suppression diff; hard-fail on `WordPress.DB.Prepared*`/`EscapeOutput` + reappearing suppressions; direct-query/cache evidence is advisory to the critic; reviewed `get_block_wrapper_attributes()` suppressions are recorded but not hard-failed |
| P2 | Security critic consumes `security-gate.json` | **DONE on `main`** (merged via PR #3) | Updates `.agents`, `.codex`, and `.claude` security critic surfaces; adds optional `--security-gate` output-contract enforcement; adds `security-gate-consumption-v1` fixture/rubric/sidecar |
| 3 | WooCommerce static scanner | pending | HPOS legacy-API scan; plugin-readiness scope for V1 |
| 4 | Update-safety oracle | pending | wp-env replay: activation + fatal-log diff + render; batch+bisect-on-fail |
| 5 | Builder→blocks verifier (flagship) | pending | Fourth executor kind; needs the licensed WPBakery/Divi zips |

External dependency already cleared: **WPBakery and Divi licenses purchased**
(2026-07-02), supplied to gates via runtime flag, never committed. Confirm the
WPBakery zip is downloaded before target #5.

## Verification environment

The first July 6 session had Python 3.10 and no PHP/Composer, so it could only
prove the gate hermetically. The continuation pass ran on **Python 3.13.9**,
**PHP 8.5.5**, and **Composer 2.9.7**, pinned the WPCS toolchain in tracked
Composer state, and exercised the real gate locally.

## Pushed forward this session (2026-07-06)

Security gate #2 is **implemented, PHP/WPCS-certified, merged, and on `main`**,
following the API-lint template. Landed:

- `evals/harness/wp_security_gate.py` — the gate: WPCS security sniffs under
  `--standard=WordPress` + the suppression differential (phpcs run twice, normal
  vs `--ignore-annotations`; reappearing security-relevant suppressions are the
  hard-fail signal), the hard/advisory/blocked/skip split,
  `wordpress-security-gate/v1` schema, and a CLI. Fail-closed to `blocked` when
  PHP/WPCS is absent.
- Certifier-stack wiring in `validate_wordpress_artifact.py`
  (`check_security_gate` + registration + result surfacing at `:610`) and
  `certify_wordpress_executor_artifact.py` (the `security-gate.json` sidecar +
  scorecard line); `tests/conftest.py` now stubs both structural gates
  independently per-marker.
- `evals/harness/php-tools/composer.json` + `composer.lock` — exact-pinned
  `squizlabs/php_codesniffer 3.13.5`, `wp-coding-standards/wpcs 3.3.0`,
  `phpcsstandards/phpcsutils 1.2.2`, and `phpcsstandards/phpcsextra 1.5.0`.
- `evals/harness/tests/test_wp_security_gate.py` — **20 tests passing**
  (parse/diff/classify/status/summary/schema shape, sniff inventory, sidecar
  shape, and real-toolchain fixture/certifier checks); added to the CI pytest
  bundle.
- `plans/005-security-gate-static-profile.md` — the executor-ready plan (kept as
  the spec/record), and `evals/harness/tests/fixtures/wp_security_gate/` — four
  clean-room fixtures + the schema.

Verified here: the full harness suite is green (**212 passed** after rebasing on
API-lint phase 2), the focused
security-gate suite is green (**20 passed**), the WPCS sniff inventory resolves
all seven selected sniffs through explicit runtime `installed_paths`, the
`suppression-abuse` fixture fails on the intended PreparedSQL suppression, the
other three fixtures pass, and all **8 plugin/block materializable examples**
certify with `security_gate=pass`.

## P2 continuation (merged via PR #3)

PR #3 implemented the handoff's P2 item:

- `wordpress-security-critic` prompt surfaces now require `security-gate.json`
  evidence consumption, gate-derived vs critic-derived provenance, and
  suppression-review notes for every `suppressed_annotations[]` entry.
- `validate_wordpress_skill_output.py` accepts optional `--security-gate` and,
  when supplied for `wordpress-security-critic`, requires status, enforced
  rule IDs, suppression file/line evidence, suppression-diff provenance, and
  sidecar negative-space handling.
- The security critic suite has a new focused
  `security-gate-consumption-v1` fixture/rubric plus a
  `.security-gate.json` sidecar that the saved-output runner auto-detects.
  Existing 2026-06-21 saved evidence predates that fixture and must be rerun
  before score claims include it.

## Recommended next actions

1. **Owner:** pick the git-history strategy (squash-reimport is simplest and
   already prescribed), enable private vulnerability reporting, and finish issue
   #1 sign-offs; then the release flip and post-public skills.sh registration
   are mechanical.
2. **Build:** continue the roadmap: WooCommerce scanner (#3), update-safety
   oracle (#4), builder→blocks verifier (#5).
