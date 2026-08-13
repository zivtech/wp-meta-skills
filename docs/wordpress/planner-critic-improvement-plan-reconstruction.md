# Planner-Critic Improvement Plan — Reconstruction

Reconstructed: 2026-08-13. **This is not the source document. The source document is lost.**

## Why this file exists

Several landed changes cite "recommendation NN of the planner-critic improvement plan"
([`wordpress-environment-probe/SKILL.md:60`](../../.claude/skills/wordpress-environment-probe/SKILL.md)).
That plan is not in the repository, is not in `plans/` (which holds only the unrelated July
006–019 series and is gitignored), and is not in any session transcript store on this machine.
It was never tracked, so it evaporated.

Recommendations 06 and 09 were implemented anyway, because whoever executed them had the
document open. What remained — 01, 02, 03, 04, 05, 07, 08 — became references without
referents. Anyone picking the work up has to grep the repository to discover that rec 01 is
even *knowable*, and cannot tell that 03/04/05/08 are unknowable rather than merely unread.

This file records what is recoverable, with the evidence for each claim, so the next person
starts from the reconstruction instead of redoing it or silently inventing a spec.

**Every row below is either cited or marked unrecoverable. Do not add an uncited row.**

## What is known

| Rec | Title / content | Confidence | Evidence |
| --- | --- | --- | --- |
| **01** | **Critic Phase-0 evidence gate.** The critic reviews by reading; it does not run its verification tools. Rec 01 makes evidence-gathering a Phase-0 obligation. | **Named verbatim** | `corpus-pilot-results.md:140`; capability statement "the critic still can't run tools" at `corpus-prereg.md:119` and `corpus-pilot-results.md:131` |
| **02** | **Reproduction as price of admission.** A finding is not admissible unless it can be reproduced. | **Named verbatim** | `corpus-pilot-results.md:140` |
| **03** | — | **Unrecoverable.** Grouped with 01/02 as work the corpus baseline would measure, so presumably a critic-prompt change. Nothing more. | `corpus-prereg.md:25` ("recs 01/02/03") |
| **04, 05, 08** | — | **Unrecoverable.** No reference of any kind anywhere in the repository. | none |
| **06** | **WordPress environment probe + capability manifest.** Read-only probe emitting a machine-readable manifest; `BLOCKED`/`UNKNOWN` never satisfy a requirement. | **Landed** | `wordpress-environment-probe/SKILL.md:60`; PR #5 |
| **07** | **Unrecoverable as a specification.** Its *surface* is inferable: the probe reports seven blockers whose remediation it explicitly defers to rec 07, so rec 07 is some form of environment provisioning/remediation. That is an inference from remediation hints, **not a recovered spec.** | **Inferred only** | 8 `rec 07` sites in `evals/harness/probe_wordpress_environment.py`; 2 in `tests/fixtures/capability_manifest/golden-wp-env-docker.json` |
| **09** | **Critic evaluation corpus.** T/J/C tranches, suite-aware scorer, integrity gates. Measures the current critic to baseline recs 01/02/03 against. | **Landed** | `corpus-prereg.md:1`; PR #9 |

### The rec 07 surface, for reference only

The probe emits these blockers and defers each fix to rec 07. This is what rec 07 would
have to cover; it is **not** a licence to write a spec and call it rec 07.

| Severity | Blocker | Deferred remediation |
| --- | --- | --- |
| CRITICAL | No validated WP-CLI invocation prefix | Start the local environment / run from project root |
| MAJOR | WordPress not installed or unreachable | Install or start the site |
| MAJOR | Neither phpcs nor phpstan answered | `composer install` |
| MAJOR | No publicly exposed MCP ability observed | `composer require wordpress/mcp-adapter` |
| MAJOR | Abilities API not confirmed by probe | `--allow-eval`, or install `wp-cli ability-command` |
| MINOR | Plugin Check WP-CLI command did not answer | `wp plugin install plugin-check` |
| MINOR | No `@wordpress/env` or `@wp-playground/cli` | `npm install @wordpress/env` |

## Current state of the work

Recs 01 and 02 are **defined but blocked**, in a chain with one human-only link:

1. ✅ Corpus authored and landed (rec 09, PR #9).
2. ✅ Judge-family confound controlled (PR #13) — `--judge-mode balanced`.
3. ⛔ **Independent baseline-strength review** — [`baseline-strength-review.md`](../../evals/suites/wordpress-critic/baseline-strength-review.md).
   Open. Requires a human who did not author the fixtures or baselines. **This is the only
   blocking link, and nothing downstream can proceed past it.**
4. ⛔ Full 24-fixture judged run. No usable baseline exists yet: the only recorded run was a
   3-fixture `--fast` slice that failed its own discrimination self-check (−0.12 against a
   required ≥ 0.20), and its raw artifacts were destroyed by a worktree cleanup on
   2026-08-12 (see below). Its findings survive in `corpus-pilot-results.md`.
5. ⛔ Recs 01 and 02, measured against that baseline.

Recs 03, 04, 05, 07 and 08 are not blocked. They are **gone**. If that work matters, the
correct move is a fresh audit producing a *tracked* plan — not reverse-engineering a
plausible spec and attaching a number to it that nobody can check.

## How this was lost, and the two changes that follow

The plan lived in an untracked file. So did the pilot run: `evals/results/` is gitignored,
the pilot ran in a disposable worktree, and `git worktree remove` deleted the directory
including its ignored contents. `git status --short` reported the worktree clean, because by
design it does not show ignored files — the check that was run could not have caught it.

Two consequences, both now addressed:

- **Roadmaps and decisions belong in tracked files.** The July 006–019 series survived only
  because it carried a tracked ledger and tracked review packets alongside the gitignored
  plan files. The August recommendations had no such record, and that is the entire reason
  this reconstruction exists.
- **Expensive evidence must survive routine cleanup.** Use
  [`scripts/safe-worktree-remove.py`](../../scripts/safe-worktree-remove.py) instead of
  `git worktree remove`; it refuses to destroy unsaved run artifacts and can archive them
  first. Regenerating a judged run costs real API spend and hours, which is exactly the
  category of thing a "clean" worktree check should not silently discard.

## Picking this up

- **To move recs 01/02:** get the baseline-strength review done. It is 30–45 minutes of a
  human's time and everything else waits on it.
- **To do anything else:** run a fresh audit and write the plan into a tracked file with a
  ledger, the way 006–019 did it. Do not attempt to reconstitute 03/04/05/07/08 from
  inference; a fabricated spec carrying a real recommendation number is worse than an
  acknowledged gap, because the number implies a provenance it does not have.
