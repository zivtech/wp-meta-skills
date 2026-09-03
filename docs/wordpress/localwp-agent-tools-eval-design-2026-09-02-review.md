# Review of the localwp-agent-tools value-eval design (2026-09-02)

Adversarial review of `localwp-agent-tools-eval-design-2026-09-02.md` (and the `evals/suites/localwp-agent-tools-value/` scaffold). **Verdict: REVISE.** The skeleton is right — seeded faults, deterministic end-state oracle, pre-registered lift table, capability-matched control, archive-before-read. But two load-bearing pieces would, as written, produce a headline that measures the wrong mechanism, and the PoC oracle would fail every realistic run. Build the stack image / headless entrypoint / runner now (they don't change); do NOT freeze `prereg.md` or build `oracle.py` until the findings below are folded in.

## Critical

1. **The primary contrast measures the wrong mechanism.** The design binds the "product claim" (p<0.05 ∧ Δ≥0.20) to **T–C0**, but T–C0 conflates three mechanisms — M1 (zero-config WP-CLI), M2 (named tools), M3 (generated `CLAUDE.md`) — and is dominated by M1, which nobody disputes. The claim being marketed ("agents debug better with our tools") is M2, which only **T–C1** isolates. Shipping T–C0 as the headline is the same "real-but-mislabeled effect" trap as the prior BLOCKED benchmark (N5). **Fix:** make **T–C1 the primary** for the tool-quality claim and T–C0 a co-primary labeled *provisioning*, split α 0.025/0.025, and freeze a two-number headline template ("zero-config WP-CLI: Δ=__; named tools beyond WP-CLI: Δ=__") so there's no post-hoc "lead with whichever is fair."

2. **The parity gate that would license the word "Local" is statistically vacuous.** With Lane L at R=5, "success-rate difference > 0.30" means |k₁−k₂|≥2, which fires spuriously ~34% per comparison → ~98% across the 12 comparisons under *perfect* parity. It would force a pre-reg deviation almost every run. **Fix:** replace it with a **deterministic tool-output equivalence check** — seed the same fault in both lanes, call each tool with identical args, diff outputs modulo the absolute-path prefix (R=1, CI-gateable); demote Lane L agent runs to descriptive. (Real Local isn't installed on this machine, so the agent-based Lane L is blocked regardless.)

## Major (fixes are specific and mostly cheap)

3. **Oracle fails legitimate runs.** The no-collateral log check forbids fatals after `agent_start_ts`; any agent that reproduces the blank page (curls the URL) logs a fresh fatal → auto-fail. Fix: take the log offset *after* the agent exits, oracle issues its own request.
4. **Cheat-suite hole.** A stub in the *plugin* dir (vs the tested theme dir) passes every check; static markup with golden titles passes (regex checks presence, not content). Fix: assert formatted-date content + a post-hoc dynamic nonce-event probe; add the missing cheats.
5. **`wp_debug_toggle` leaves un-restorable `wp-config.php` residue**, so a T agent using the tool as designed fails the byte-unchanged collateral check. Fix: golden defines all debug constants; compare `wp-config.php` semantically, not byte-wise.
6. **C1 shim is spuriously handicapped** — it lacks the `--path` auto-append that T's `wp_cli` has, so C1's first command fails from the wrong cwd. This inflates T–C1 (the M2 claim). Fix: shim mirrors `wpcli.ts` (`--path` when absent).
7. **T-ctx doesn't isolate M3** — the generated `CLAUDE.md` tells the agent to call tools T-ctx doesn't have, so T-ctx underperforms and M2 is over-credited; `mcp_invoked` as an M3 alarm is dead on arrival (the context file instructs tool use). Fix: T-ctx uses a tool-stripped context; retire `mcp_invoked` as the M3 signal.
8. **C0 underspecified** on the three parameters that set its difficulty (phar location, network egress, mysql client). Pin them, or C0 is either trivially C1 or artificially crippled.
9. **Turn/wall-clock caps gate the primary asymmetrically** (T pays MCP round-trips). Report pass@turn curves; make wall-clock non-binding; state the primary as "pass within 60 turns."
10. **Pilot tuning rule is directional toward T** (bigger "haystack" hurts C0, irrelevant to T). Pre-register haystack size; only arm-symmetric tuning.
11. **Two-stage stop** carries uncorrected type-I inflation (~0.06–0.08). Simulate and report realized α.
12. **The "no 'Local' in the writeup" rule is prose, not tooling** — in a project whose log already shows a headline that traveled without its correction. Fix: the scorecard generator refuses to emit "Local" without the Lane-L / parity artifacts present.
13. **Flagship fixture likely saturates** for a frontier model in all arms (signal moves into turns, which is barred from claims). Pre-register saturation-as-a-result; add fixtures where the bit differs.

## What's missing (highest value)

- **Fixtures where the tool plausibly LOSES**, exploiting its real code paths: (a) `wp-config.php` in the parent dir → `read_wp_config`/`edit_wp_config`/`wp_debug_toggle` all report "not found" while `wp_cli` still works (misdirection); (b) a dead `object-cache.php` drop-in → `wp_cli`/`get_site_info`/`site_health_check` all hang to timeout; (c) fatal routed to `error.log` while a fresh `debug.log` full of harmless notices misleads `read_error_log`'s newest-file heuristic.
- **php.ini parity** in the stack contract: fixture 1's "blank page" symptom is only true if `display_errors=Off`; if Local ships it On, the fatal prints in the browser and the flagship lift evaporates. Resolve before freezing the prompt.
- **An independent author for the expected-lift table** (the current monotonicity check is self-confirming — same person wrote the fixtures and the predictions).

## The single biggest way the result could still be wrong (even if executed perfectly)

The attribution chain: T–C0 comes in large (M1, already believed); T–C1 comes in moderate but *inflated* by C1's `--path` friction (#6) and by M3 riding inside T; T-ctx runs with the tool-referencing context, gets confused, lands near C0 (#7) → author concludes "the context file isn't it" → credits the T–C1 gap to **M2** → "agents debug better with our named tools" ships. Every step follows the spec; the conclusion is wrong. Findings 1, 6, 7 are the chain; fix all three or the headline is untrustworthy.

## Build order

- **Safe to build now:** stack image, headless entrypoint (~40 lines, `main.ts` minus Electron), the runner, the MCP tool-contract smoke.
- **Blocked until fixes folded:** `oracle.py` (needs #3/#4/#5), `prereg.md` freeze (needs #1/#2/#6/#7/#8), and committing `eval.yaml` (needs a `tool-value-ab` profile added to `scripts/validate-eval-suite-integrity.py`).
- **Blocked on environment:** the agent-based Lane L parity/descriptive runs (Local not installed, ~1h).
