# Goal Handoff - 2026-07-02

State snapshot for the next working session. Everything below lives on
branch `claude/wp-meta-skills-public-readiness-fjr0d1` (pushed; based on
`main` @ `14d906d`).

## What happened this session

1. **Public-readiness review completed** —
   `docs/public-readiness-review-2026-07-02.md`. Name check (keep
   `wp-meta-skills` slug; README retitled "WP Meta Skills" for trademark +
   collision reasons), license check (Apache-2.0 fine; but see decision 2
   below — GPL-3.0 relicense now approved in principle), full leak sweep,
   all runnable publication gates re-verified green (manifest, frontmatter,
   exact-API, strict suites, 148 harness tests).
2. **Readiness fixes applied and pushed** (commit `865b759`): redacted
   personal paths + an unrelated plugin name from 15 evidence/docs files;
   SECURITY.md now points at GitHub private vulnerability reporting;
   CLAUDE.md/AGENTS.md doc links repaired; stale license-policy language
   reconciled; CONTRIBUTING.md fixed for standalone layout; QUALITY_GAPS.md
   cleaned; MANIFEST regenerated.
3. **Research plan** — `docs/wordpress-assist-research-plan-2026-07-02.md`:
   twelve ranked WordPress pain areas; headline finding: the ecosystem is
   saturated with AI generators and ships essentially zero verifiers.
4. **Five build-brief deep dives** (commit `5d51e7d`), one per priority
   target, under `docs/wordpress/deep-dive-*.md`:
   update-safety oracle; security gate + triage; builder-to-blocks
   verifier; WooCommerce transition gates; API-existence lint.
5. **All 12+ open maintainer questions answered by Alex in-session** —
   recorded in `docs/wordpress/verification-targets-decisions-2026-07-02.md`.
   Headlines: build API lint first; GPL-3.0 relicense approved in principle;
   buy WPBakery/Divi licenses; pinned + opt-in live; hard gates for
   unknown hooks and unambiguous security findings; batch+bisect update
   mode; core-blocks-only conversion; conversion as fourth executor kind;
   Woo critic plugin-scope V1; API lint may shell to PHPStan.

## Blockers before the public visibility flip (from the readiness review)

1. **History strategy — DECIDED 2026-07-03: squash.** Reimport the scrubbed
   tree as a fresh root commit on `main` (PROVENANCE.md's clean-import
   strategy). Sequence: merge this branch into `main`, then create the
   fresh root from the merged tree and force-push `main`. Exact commands
   are staged in this handoff's companion note from the remote session;
   execution requires owner/main-branch permission.
2. ~~GPL-3.0 relicense~~ **Executed 2026-07-03** (commit on this branch):
   LICENSE is GPL-3.0; README, CLAUDE.md, license-reuse-policy.md,
   provenance-policy.md, reuse ledger, decisions doc, and the readiness
   review all updated together. Committing GPL-compatible data snapshots is
   now permissible with a ledger entry.
3. Enable GitHub private vulnerability reporting in repo settings when
   public; owner sign-offs tracked in issue #1; post-flip CI run, then tag.

## Next build work (in decided order)

1. ~~API-existence lint~~ **Phases 1+2 shipped 2026-07-02** — by two
   sessions in parallel, then merged. The local session shipped P1
   (PHPStan level 0 + pinned `php-tools` Composer toolchain + wp-compat,
   real scope analysis, api-lint.json in the certifier). The remote session
   built the same lane independently and its work was refit on top as
   phase 2: a native engine over the committed MIT-only snapshot
   `evals/harness/data/wp-symbols.json` (`deprecated_api` findings naming
   exact successors always; existence/version-range takeover at regex tier
   when the toolchain is absent, so no-toolchain environments degrade with
   explicit negative space instead of going blocked), plus an
   `unknown_hook` engine with did-you-mean suggestions reading wp-hooks
   data from the vendor tree at run time (GPL data never committed, per the
   reuse ledger). Every report carries an `engines` availability map.
   Remaining for this lane (P3): hook arg-count check, deprecated-hook
   scrape, WooCommerce symbol data, JS `@wordpress/*` checks (advisory),
   snapshot staleness CI. Coordination rule after the near-collision: check
   `git fetch` + this handoff before starting a lane, and record lane
   ownership here first.
2. Security gate static profile (`run_wordpress_security_gate.py`:
   PHPCS security sniffs + the `--ignore-annotations` suppression diff).
3. WooCommerce static scanner (`scan_woocommerce_transition.py`).
4. Update-safety oracle (`run_wordpress_update_safety_smoke.py`).
5. Builder-to-blocks verifier (fourth executor kind).

## Pending on Alex (external)

- ~~Purchase WPBakery and Divi~~ **Done 2026-07-02.** Both licenses
  purchased; two Divi versions (keep both: Divi 4 = shortcode storage, Divi
  5 = JSON storage — the extractor needs both parsers) plus the Divi UI kit
  are downloaded to a local plugins directory on Alex's machine, outside
  any repo clone. Do not commit the zips or the local path anywhere in this
  repository; gates receive licensed copies via a runtime flag
  (deep-dive-builder-to-blocks-verifier, fixture (b) lane). Confirm the
  WPBakery zip is also downloaded from the CodeCanyon downloads page before
  the builder-verifier phase needs it.
- Approval-issue #1 sign-offs and the history-strategy execution above.

## Orientation for a fresh session

Read in this order: `docs/public-readiness-review-2026-07-02.md` →
`docs/wordpress-assist-research-plan-2026-07-02.md` →
`docs/wordpress/verification-targets-decisions-2026-07-02.md` → the deep
dive for whichever target you're building. Validation bundle commands are in
SECURITY.md; evidence semantics in
`docs/wordpress/runtime-oracle-runbook.md`. Note: web research from this
sandbox is snippet-limited for most non-GitHub hosts (egress proxy) — the
deep dives mark [fetched] vs [snippet-only] accordingly; re-verify
snippet-only numbers before quoting them externally.
