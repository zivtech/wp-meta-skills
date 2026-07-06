# Pilot Results

Status: executed; absolute-score discrimination failed.

Test-critic gate: ACCEPT-WITH-RESERVATIONS for pilot execution only.

Candidate screening: completed on 2026-06-16 in `evals/results/wordpress-skill-candidate-eval/2026-06-16-candidate-screening.md`.

Scoring readiness: parser-level blocker repaired on 2026-06-16. The generic LLM judge now extracts this suite's weighted `criteria` and fixture-specific `domain_signals` instead of returning `No criteria defined in rubric.`

Pilot run: `evals/results/wordpress-skill-candidate-eval/wordpress-candidate-pilot-20260616-live/`.

Artifacts:
- 48 raw outputs.
- 48 metadata JSON files.
- 48 local Opus score JSON files.
- `manifest.json`, `summary.json`, `scorecard.md`, and `internal-only-decision.md`.

Scoring path: local Claude CLI only, using `claude -p --model claude-opus-4-6` via `evals/harness/score_with_claude_cli.py`. Do not use the direct Anthropic SDK/API key path for this WordPress pilot.

Pilot result:
- `baseline-zero-shot`: 99.51 mean composite.
- `baseline-few-shot`: 99.51 mean composite.
- `raw_upstream_candidate`: 100.0 mean composite.
- `zivtech_prototype`: 88.23 mean composite.
- Known-strong minus known-weak normalized delta: `-0.113`.
- Required normalized delta: `0.2`.
- Verdict: pilot did not pass; absolute scoring is saturated and/or miscalibrated for this comparison.

Pilot gate before full benchmark:
- Completed for four pilot fixtures and four conditions across three runs.
- Separation was lower than required.
- Switch to blind pairwise preference before making adoption, superiority, or reuse decisions.

Runbook: `wordpress-skills/docs/candidate-pilot-runbook.md`.

No full-run claims are made by this suite. The current results are internal-only, uncalibrated single-judge evidence until agreement is measured or explicitly waived for an internal-only decision.
