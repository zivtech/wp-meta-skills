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

## Negative space

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
