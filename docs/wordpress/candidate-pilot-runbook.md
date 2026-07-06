# WordPress Candidate Discrimination Pilot Runbook

Updated: 2026-06-20.

This runbook describes how to execute the WordPress candidate discrimination pilot without treating unrun scaffolding as evidence.

## Completion Gate

The pilot is complete only when all of these artifacts exist:

- Four pilot fixtures: `security-boundary-risk`, `block-development-risk`, `content-model-ambiguous`, and `performance-ops-clean`.
- Four conditions: `baseline-zero-shot`, `baseline-few-shot`, `raw_upstream_candidate`, and `zivtech_prototype`.
- Three runs per condition, producing 48 output artifacts.
- Metadata per output: model/version, prompt path, fixture ID, run index, condition order, judge model, and scoring config.
- Weighted score JSON per output using this suite's `criteria` plus `domain_signals` rubric path.
- Separation summary: known-weak vs known-strong delta is `>= 0.2`, or the suite switches to blind pairwise judging.
- Judge agreement report, or an explicit `internal-only, uncalibrated single-judge` label.

## Preflight

```bash
cd /path/to/zivtech-meta-skills

python3 scripts/validate-eval-suite-integrity.py \
  --strict-suites wordpress-skill-candidate-eval \
  --allow-known-gaps

python3 scripts/validate-wordpress-exact-api-contract.py

codex --version
codex exec --model gpt-5.5 --sandbox read-only --ignore-user-config --skip-git-repo-check --ephemeral --ignore-rules --color never "Return only OK"
```

## One-Command Absolute Pilot Runner

This runner generates all four conditions, writes per-output
metadata and scores, and creates top-level `manifest.json`, `summary.json`,
`scorecard.md`, and `internal-only-decision.md` files. Baseline generation now
uses isolated local Codex/ChatGPT by default; Zivtech and upstream candidate
lanes use explicit isolated Claude prompt surfaces, and scoring still uses a
single local Claude judge. Treat fresh runs as internal-only unless a separate
multi-judge or human agreement gate is added.

```bash
python3 evals/harness/run_wordpress_candidate_pilot.py \
  --run-id wordpress-candidate-pilot-YYYYMMDD-HHMMSS \
  --runs 3 \
  --resume
```

## Baseline Output Generation

`evals/harness/invoke.py` can generate the baseline lanes.

```bash
RUN_ID="wordpress-candidate-pilot-$(date +%Y%m%d-%H%M%S)"
SUITE="wordpress-skill-candidate-eval"

for RUN in 1 2 3; do
  for FIXTURE in security-boundary-risk block-development-risk content-model-ambiguous performance-ops-clean; do
    for CONDITION in baseline-zero-shot baseline-few-shot; do
      python3 evals/harness/invoke.py \
        --run-id "$RUN_ID/r$RUN" \
        --suite "$SUITE" \
        --fixture "$FIXTURE" \
        --condition "$CONDITION" \
        --mode critic \
        --timeout-sec 600 \
        --max-retries 2
    done
  done
done
```

Current baseline policy for invoke-compatible WordPress runs: condition names
beginning `baseline-*` use isolated local Codex CLI with
`baseline_provider: codex`, `baseline_model_policy:
newest-chatgpt-level-at-run-time`, currently `baseline_model: gpt-5.5`, and
`baseline_effort: medium`. `run_wordpress_candidate_pilot.py`,
`run_pairwise_pilot.py`, and
`answer_key_score.py --generate` now follow the same split for `baseline-*`
generation while keeping skill/upstream lanes on isolated Claude prompts.
Historical Claude/Sonnet candidate artifacts remain historical evidence only.

## Zivtech Prototype Output Generation

Use the suite runners for Zivtech prototype generation. Do not call
`claude -p --agent` manually for candidate evidence: that path was the confirmed
contamination vector because it lets Claude discover repo/user `.claude` config.

The current runners read the relevant agent prompt file, inject that prompt as
message content, then run Claude from a scratch cwd with scratch HOME/XDG and an
empty strict MCP config:

```bash
python3 evals/harness/run_wordpress_candidate_pilot.py \
  --run-id wordpress-candidate-pilot-YYYYMMDD-HHMMSS \
  --runs 3

python3 evals/harness/run_pairwise_pilot.py \
  --run-id pairwise-candidate-target-YYYYMMDD-HHMMSS \
  --runs 3
```

Record `agent_injection: content`, `runtime: local_claude_cli_isolated`, prompt
path, model, and isolation posture in metadata for absolute candidate-pilot
runs. For pairwise runs, use the checkpoint provenance counts in
`pairwise-summary.json` to distinguish current-run cache, reused generations,
Codex baselines, and isolated Claude candidate generation.

## Raw Upstream Candidate Output Generation

Materialize upstream candidates in `/tmp`, not in this repo. For the official comparator lane:

```bash
TMP="/tmp/wp-agent-skills-aa735ea"
PROJECT="/tmp/wp-agent-skills-pilot-project"

git clone https://github.com/WordPress/agent-skills.git "$TMP"
git -C "$TMP" checkout aa735ea7111c7924ee988306bcef70439e17dec9
node "$TMP/shared/scripts/skillpack-build.mjs" --clean
mkdir -p "$PROJECT"
node "$TMP/shared/scripts/skillpack-install.mjs" \
  --dest="$PROJECT" \
  --targets=claude \
  --skills=wordpress-router,wp-plugin-development,wp-rest-api,wp-block-development,wp-performance
```

Record the upstream prompt path, commit SHA, selected upstream skill, and local install destination in each output metadata file.

## Scoring With Local Claude CLI

Use `evals/harness/score_with_claude_cli.py` to preserve the repaired weighted-rubric extraction from `llm_judge.py` while avoiding direct SDK calls.

```bash
python3 evals/harness/score_with_claude_cli.py \
  --output "$OUT/security-boundary-risk.md" \
  --rubric "$ROOT/evals/suites/$SUITE/rubrics/security-boundary-risk.rubric.yaml" \
  --fixture-id security-boundary-risk \
  --condition zivtech_prototype \
  --model claude-opus-4-6 \
  --json-out "$OUT/security-boundary-risk.score.json"
```

For WordPress V1 evidence runs, do not fall back to `ANTHROPIC_API_KEY` or direct SDK judging. If local Opus is unavailable, stop and record the blocker.

## Current Verdict

The candidate-discrimination arc is closed as **directional-internal only**:

- Absolute scoring (`wordpress-candidate-pilot-20260616-live`) failed discrimination and exposed contaminated `zivtech_prototype` generation.
- Blind pairwise plus rubric-anchored judging (`pairwise-pilot-20260617-061925`, `pairwise-cert-1`, `pairwise-cert-2-xfamily`) did not certify reliable separation from a strong few-shot prompt.
- Answer-key diagnostics localized the remaining measurable gap to exact WordPress API naming, not detection recall or false-positive control.

Do not run the 27-fixture benchmark for a frontier-model review-quality superiority claim. Reopen only for a changed measurement target, such as cheaper-model lift, output-contract conformance, variance reduction, or executor/oracle-backed code generation. Current improvement rationale is recorded in `docs/skill-improvement-research-2026-06-20.md`.
