# Verification Targets: Maintainer Decisions - 2026-07-02

Maintainer (Alex) answered the open questions from the five deep-dive build
briefs in-session on 2026-07-02. These are now the decided defaults; the
briefs' "maintainer questions" sections are resolved as follows.

## Strategy

1. **Build order: API-existence lint first.** Then (by effort-to-payoff):
   security gate static profile, WooCommerce static scanner, update-safety
   oracle, builder-to-blocks verifier as the flagship project.
2. **Licensing posture: GPL-3.0 relicense approved and executed
   2026-07-03** (approved in principle 2026-07-02; final approval and
   execution 2026-07-03, before the public visibility flip). Rationale:
   this is FOSS marketing for Zivtech's WordPress capability, not a
   licensing play. `LICENSE`, README, CLAUDE.md reuse policy,
   `license-reuse-policy.md`, `provenance-policy.md`, and the reuse ledger
   were updated together. Practical consequence: committing GPL-compatible
   data (e.g. a wp-hooks snapshot) is now permissible with a reuse-ledger
   entry; the lint currently still reads wp-hooks from the vendor tree at
   run time, which remains fine.
3. **Paid components: buy licenses now.** WPBakery (CodeCanyon item 242431,
   ~$64) and Divi (Elegant Themes membership, ~$89/yr) get purchased for a
   local-only CI lane. Licensed copies are supplied via flag at runtime and
   are NEVER committed to the repo. Premium plugin update zips likewise
   user-supplied.
4. **Version policy: pinned + opt-in live.** CI gates run pinned
   WordPress/WooCommerce/builder versions for reproducibility; an explicit
   `--live` mode tracks latest-stable (mirrors meta-router's
   `verify.sh --live` precedent). Periodic pin-bump chore accepted.

## Gate strictness

5. **API lint unknown-hook severity: hard fail + allowlist** from day one,
   with a plugin-slug/namespace allowlist knob; third-party namespaces
   (e.g. `woocommerce_*` before the Woo hooks DB lands) handled via the
   allowlist rather than by downgrading the gate.
6. **Security gate: hard gate for the unambiguous.**
   `WordPress.DB.Prepared*`/`EscapeOutput` errors and security-relevant
   suppression abuse (the `--ignore-annotations` diff) block certification;
   Semgrep audit hits, PHPStan warnings, and Plugin Check policy notes stay
   advisory evidence for the critic.
7. **Fleet vulnerability triage (Lane B): V2 in this repo.** Lane A (code
   review + gate) ships first; triage lands later with WPVulnerability as
   the default free feed and recorded-feed fixtures for determinism.

## Target-specific

8. **Update-safety oracle default mode: batch + bisect on fail.** Update
   everything, gate once; bisect for attribution only on failure. Default
   replay tier remains plugin-set synthetic (no site content leaves the
   site); sample/full content replay is opt-in.
9. **Builder-to-blocks mapping target: core blocks only + TODO flattens.**
   Tabs/sliders/forms resolve to accordion restructures, static flattens
   with waivers, or visible TODO blocks — no third-party block dependency
   in converted output. (A per-site allowlist can be revisited later; the
   verifier already accepts a declared allowlist parameter.)
10. **Conversion verifier ships as the fourth executor kind** inside the
    packet → materialize → certify pipeline (repair-prompt/repair-loop reuse
    comes free), not as a standalone CLI first.
11. **WooCommerce transition critic V1 scope: plugin readiness only.**
    Site-level audit (theme overrides + all active plugins) is V2. HPOS
    smoke default: no-sync (strictest, cheapest); the sync/compat matrix is
    an optional flag, not V1 default.
12. **API lint implementation: shell out to PHPStan.** Phase 1 = subprocess
    `phpstan` + wordpress-stubs + wp-compat, parse JSON into the finding
    schema; gate reports `blocked` where PHP tooling is absent, consistent
    with the existing phpcs gate. The static profile is not held to a
    stdlib-only invariant.

## Remaining defaults (not separately asked; adopt unless overridden)

- Evidence-packet schemas (`update-verdict.json`, `conversion-verdict.json`,
  `wordpress-security-gate/v1`, `woocommerce-transition-scan/v1`,
  `api-lint.json`) carry a `schema`/`schema_version` field from day one;
  no separate spec repo for now.
- Symbol-DB freshness: committed compiled snapshot + scheduled CI staleness
  check that fails when upstream tags advance.
- Visual diffs stay advisory everywhere; never in `failing_gates` without an
  explicit strict flag.
