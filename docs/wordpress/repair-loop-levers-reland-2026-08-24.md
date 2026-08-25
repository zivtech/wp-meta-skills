# Repair-Loop Levers Re-Land and Lease-Wall Discovery — 2026-08-24

Tracked record of the `feat/wpcs-autofix-and-fence-refix` work (PR #19), following
the [reconstruction doc](planner-critic-improvement-plan-reconstruction.md)'s rule
that roadmap-relevant decisions and evidence live in tracked files.

## Why this work exists

The recorded local-model repair-loop plateau
(`abilities-ai-surface-v1`, plugin executor, runtime profile) ended 2026-06-26 with
three identified levers: fence-aware packet parsing, a WordPress readme.txt format
contract, and phpcbf for the auto-fixable WPCS half. Those landed in the
**monorepo** — but this standalone repo was clean-imported from a ~2026-06-24
monorepo state, so none of them existed here. Verified empirically before
re-implementing: the fence-blind `sections()` bug reproduced on current `main`
(an in-fence `## Description` severs the section and reports the misleading
"no fenced code block found"), and no `phpcbf` reference existed anywhere.

The repo's declared improvement target (CLAUDE.md) includes "cheaper-model lift"
and "executor tasks with deterministic packet, static artifact, and provisioned
runtime WordPress checks" — this is that thread.

## What landed

1. **Fence-aware scanning** (`mask_fences`, `section_spans`, `file_fence_spans` in
   the packet oracle; materializer delegates). Headings are located on
   fence-masked text; spans slice the original. One scanner now backs both
   materialization and packet rewriting.
2. **Deterministic phpcbf auto-fix stage** (`--wpcs-autofix` on
   `run_executor_repair_loop.py`). After a failed certification with `phpcs_wpcs`
   failing, phpcbf (same pinned toolchain and invocation shape as the gate) fixes
   the packet's PHP files; fixed bodies are spliced back and the repaired packet
   is re-certified without spending a model repair slot. Design difference from
   the monorepo variant (phpcbf inside `provision_full_profile`): here the oracle
   stays pure and autofix passes are recorded honestly (`autofix: true` history
   entries under `<slot>-autofix` cert ids; `green_via_autofix`; pass@1 counts
   model output only). A failed autofix pass primes the next model repair with
   the repaired packet and only the residual failures.
3. **readme.txt format contract** in the plugin-executor SKILL.md, the
   `.agents` mirror, the `.claude` agent persona, the `.codex` TOML, and the
   abilities fixture. Note the distribution mechanics: the ollama/gemini provider
   lane feeds the **agent** file as persona (not SKILL.md), the parity validator
   requires all four surfaces byte-consistent, and `MANIFEST.sha256` must be
   regenerated after persona edits.

## The lease-wall discovery (new, this repo only)

Run 1 (`llama70b-abilities-postfence-readme-autofix-20260824`, max_repairs=2)
found a wall nobody had hit: the repair loop's `make_certify` hands the static
certifier a **workspace-lease** directory, and two layers refused the lease's
sentinel file:

- `materialize_packet` counted `.workspace-lease` as prior content →
  "output directory exists and is not empty" — an unfixable, harness-internal
  error fed to the model as repair feedback (the exact actionability sin the
  June work diagnosed).
- After fixing that, `artifact_staging`'s stage policy required every ignored
  name to be a directory; the sentinel is a regular file →
  "ignored root must be a real directory".

Masked until now because packet-gate failures always surfaced first — **the
repair loop's static certification path had never actually passed materialization
in this repo**. (The 20260620/21 certification evidence ran the certifier CLI
directly into plain directories, so it never met a lease.) Both layers fixed,
minimally: only the sentinel may be a regular file; symlinks stay banned; real
prior content still refuses. End-to-end verified with a known-good committed
packet passing `make_certify`'s full static path under a real results lease.

## Run 1 partial evidence (harness-bug-shortened, but informative)

- iter0 failed static on `exact_surfaces` + `verification_oracles`; iter1 cleared
  `exact_surfaces`; iter2 **cleared the entire packet gate** (18 exact surfaces,
  all headings, file map) and died only on the lease wall.
- **The readme contract works on the 70B**: iter2's readme.txt is proper WP
  format (`=== Acme Editorial Assistant ===`, header fields), where the June
  runs produced GitHub-markdown readmes. The recorded 70B failure mode is gone.
- Generation was fast on this hardware (~3 iterations in ~25 minutes, model
  resident at 100% GPU, 32k ctx).

## Run 2 (fair budget) — the ladder, and the Linux boundary

`llama70b-abilities-levers-r2-20260824`: same model/fixture, `--max-repairs 5`,
`--wpcs-autofix`, post-lease-fix harness. Not green, but a steady climb with
zero generation failures: iters 0–3 churned on packet-contract checks
(`exact_surfaces`/`verification_oracles`), iter4 cleared those and failed only
`php_wpcs_shape_heuristics`, and **iter5 cleared the entire static contract and
reached the isolated runtime gate** — the first repair-loop iteration ever to
do so in this repo. The iter5 artifact is qualitatively strong: lint-clean PHP,
a textbook WP-format readme (all header fields, short-description line,
`== Section ==` markers — the June markdown-readme failure mode is extinct),
and a tests directory.

iter5 then failed `runtime_command`, and the reproduction surfaced the real
boundary: `"reason": "isolated generated runtime requires Linux"`. This repo's
post-fork sandbox hardening **blocks generated-code execution on macOS by
design** (`host_fallback: false`) — activation, Plugin Check, and the container
browser only run inside the no-secrets Linux boundary, which CI provides. The
macOS-reachable runtime signal is the pinned-toolchain `phpcs_wpcs` scan, which
ran and failed. Two loop gaps surfaced and were fixed: the nonzero-return-code
path hid `phpcs_wpcs` behind the synthetic `runtime_command` label (so the
autofix trigger never saw it), and the runtime process's stderr was discarded.

**Consequence for the June target:** "realistic local GREEN" is unachievable on
this macOS host for the full runtime profile — not as a model limitation but as
a security design decision this repo made after the fork. The honest local
target is: clear every macOS-achievable gate (packet → materialization → static
artifact → runtime `phpcs_wpcs`, with autofix), and hand activation/Plugin
Check green to the Linux boundary lane.

## Targeted autofix proof on real model output

`iter5-autofix-proof-20260824`: the autofix stage applied to iter5's real
packet fixed 2 files (main plugin + test file) and eliminated the entire
whitespace/formatting violation class — the re-scan shows **0 warnings**. The
17 residual errors are all one class: missing function docblocks, `//` instead
of `/**` for function comments, and inline comments without terminal
punctuation — genuinely non-auto-fixable by phpcbf, and invisible to the model
because the runtime JSON carries no per-violation diagnostics. Response: the
WPCS-shape contract now states the docblock and comment-punctuation rules on
every persona surface (the same preventive pattern that fixed the readme), and
detail persistence in the runtime JSON is recorded below as the next lever.

## Run 3 (surfacing + autofix + extended contract)

`llama70b-abilities-levers-r3-20260824`, `--max-repairs 2`. Not green, and it
stalled earlier than run 2: static-stage churn throughout
(`verification_oracles` at iters 0–1, `plugin_header` at iter2), never reaching
the runtime gate, so the autofix trigger had nothing to act on. Two honest
readings:

- **Variance dominates short budgets.** Run 2 needed all 5 repairs to climb to
  the runtime gate; a 2-repair budget makes reaching it a coin flip. Same
  model, same fixture, same harness — different stall point.
- **The failing-check surfacing works as designed**: run 3's history records
  `['static_command', 'verification_oracles']` and
  `['static_command', 'plugin_header']` where run 2 showed only the synthetic
  `static_command` label.
- **Contract uptake is selective (n=1 caveat).** The readme contract visibly
  changed model behavior (textbook WP readme since run 2), but the newly added
  docblock/comment-punctuation bullet did not: run 3's code still has no
  function docblocks. A salient structural format contract steers this model; a
  style rule buried among ~20 hard-gate bullets apparently does not. The
  deterministic and feedback paths (autofix; persisting real violation lines
  into the repair prompt) remain the reliable levers.

## Run 4 (2026-08-25, diagnostics persistence live) — thesis validated

`llama70b-abilities-diagnostics-20260825`, `--max-repairs 5`, `--wpcs-autofix`,
with PR #20's diagnostics persistence (phpcs report into the runtime JSON,
40-line prompt slice) live. Not green — the Linux-only gates stay blocked on
macOS by design — but the feedback-actionability thesis lands:

- **Three consecutive iterations at the runtime gate** (iters 3–5), vs one in
  run 2 and zero in run 3. The static climb was also faster (packet contract
  cleared by iter2 except `plugin_header`).
- **Autofix fired live twice** (iters 3 and 4), eliminating the whitespace
  class between model turns (12 warnings at iter3 → 0 from iter4 on).
- **The model consumed the diagnostics**: WPCS errors went **65 → 62 → 2**
  across iters 3→5 — a 97% reduction once the repair prompt carried actual
  violation lines instead of a bare "phpcs_wpcs fail". The final 2 errors are
  two missing function docblocks; phpcbf correctly found nothing auto-fixable
  at iter5 (no autofix entry — the residue is non-fixable class), and the run
  was out of repair slots.
- Reading: with diagnostics + autofix, a local 70B closes to within one repair
  slot of a clean `phpcs_wpcs` on the abilities fixture. The June plateau was
  feedback starvation, as diagnosed — not model capability. (n=1 per
  configuration; variance across runs 2–4 stays real.)

- Nothing here claims skill-vs-baseline superiority; this is harness/contract
  repair plus a deterministic-assist measurement lane (consistent with the
  repo's evaluation boundary).
- Plan-002's feedback-widening lever (`_detail_slice`, kill `[:500]` caps) is
  still absent from this repo. The sharper version of that lever, per the
  targeted proof: the runtime smoke's persisted JSON carries check statuses but
  **no per-violation diagnostics** for `phpcs_wpcs`, so the repair prompt is
  feedback-starved for the residual non-fixable errors. Persisting the phpcs
  report detail into the runtime JSON is the next lever.
- The June qwen2.5-coder:32b baseline model is no longer installed locally;
  cross-model claims stay pinned to llama3.3:70b, the surviving recorded model.
- Full-profile GREEN claims for generated artifacts belong to the Linux
  boundary lane (CI's no-secrets runtime job), not to macOS runs.

## Run 5 (2026-08-25, max-repairs 7) — static variance eats the budget

`llama70b-abilities-green7-20260825`, `--max-repairs 7`, `--wpcs-autofix`,
`--timeout-sec 1800`, 8 generations, zero generation failures. Not green
(macOS cannot be, by design), and the raised budget did **not** capture the
local `phpcs_wpcs` clear — for a reason the run decomposes cleanly:

- **Static churn consumed six slots (iters 0–5):** `verification_oracles`
  (a missing WPCS reference term) through iter3, then `plugin_header` at
  iters 4–5 — the header was genuinely absent (the model wrote a file
  docblock but no `Plugin Name:` block), so the feedback was accurate; the
  model simply took two slots to act on it.
- **The runtime phase repeated run 4's mechanics in two slots:** iter6
  reached the runtime gate; autofix fired live (2 files); iter7 ended at
  **3 WPCS errors** (two missing function docblocks, one
  empty-line-before-block-comment that phpcbf reported non-auto-fixable) —
  out of slots.
- Reading: run 4's "one more slot would plausibly clear it" was the right
  endgame diagnosis but the wrong budget model. Static-phase slot
  consumption varies wildly across runs (3, >2, 3, 6 slots on the identical
  configuration); a fresh run re-rolls that variance in front of the
  runtime phase every time. Raising `--max-repairs` further is paying the
  static toll repeatedly to reach a runtime endgame that needs ~2–3
  diagnostics-fed slots.

## The structural response: seeded continuations and the Linux handoff lane

Two additions turn the recorded near-miss states into progress instead of
re-rolls:

1. **`--seed-packet`** on `run_executor_repair_loop.py`: iteration 0
   certifies a saved packet byte-exact (no model call) and repairs continue
   from it. A converged-but-short run resumes at its stall point with the
   full repair budget aimed at the residual failures. Seeded summaries carry
   `seeded`/`seed_packet_sha256` and are continuations, not pass@k evidence.
   Validated in the wild: seeding run 5's iter7 packet reproduced its
   certification state exactly (same 3 errors, same phpcbf non-fixable
   verdict) before the first model repair.
2. **The converged-artifact handoff lane**: `evals/handoff/<id>/`
   (packet + provenance, sha256-bound) plus
   `recertify_wordpress_executor_packet.py` and the
   `converged-artifact-handoff` CI job, which re-runs the exact
   `make_certify` composition inside the no-secrets Linux boundary where
   `wp_cli_activation`, `plugin_check`, and `container_browser` actually
   execute. This is the missing half of every macOS run's certification.
