#!/usr/bin/env python3
"""Score an eval output with local Claude CLI and the repo rubric parser.

This wrapper preserves the weighted rubric extraction in llm_judge.py while
avoiding direct Anthropic SDK calls. It is intended for candidate-comparison
pilots where local Opus through `claude -p` is the required judging route.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment preflight
    raise SystemExit("PyYAML is required: pip install pyyaml") from exc

from llm_judge import (  # noqa: E402
    CriterionResult,
    JudgeResult,
    _compute_scores,
    _extract_criteria_from_rubric,
    _parse_json_from_response,
    judge_result_to_dict,
)


DEFAULT_MODEL = "claude-opus-4-6"


JUDGE_PROMPT = """\
You are a rigorous evaluation judge for AI-generated WordPress skill outputs.

## Task
Score the skill output against each rubric criterion listed below.

## Skill Output
{output_text}

## Rubric Criteria
{criteria_json}

## Instructions
For each criterion, return:
- criterion_id: the exact criterion_id from the rubric
- met: true if the output satisfies the criterion
- confidence: 0.0 to 1.0
- reasoning: 1-2 sentences citing specific evidence from the output

For false_positive_trap criteria, met=true means the trap was triggered and is bad.

Return only valid JSON with this exact schema:
{{
  "scores": [
    {{
      "criterion_id": "...",
      "met": true,
      "confidence": 0.0,
      "reasoning": "..."
    }}
  ],
  "overall_notes": "2-3 sentence summary"
}}
"""


def load_rubric(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def call_claude(prompt: str, model: str, timeout_sec: int) -> str:
    command = [
        "claude",
        "-p",
        "--model",
        model,
        "--tools",
        "",
        "--permission-mode",
        "bypassPermissions",
    ]
    completed = subprocess.run(
        command,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout_sec,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "claude CLI judge failed with exit code "
            f"{completed.returncode}: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def score_output(
    output_text: str,
    rubric: dict[str, Any],
    fixture_id: str,
    condition: str,
    model: str,
    timeout_sec: int,
    attempts: int = 3,
) -> JudgeResult:
    criteria = _extract_criteria_from_rubric(rubric)
    result = JudgeResult(fixture_id=fixture_id, condition=condition, model_used=model)
    if not criteria:
        result.composite_score = 100.0
        result.judge_notes = "No criteria defined in rubric."
        return result

    prompt = JUDGE_PROMPT.format(
        output_text=output_text[:12000],
        criteria_json=json.dumps(criteria, indent=2),
    )
    last_error: Exception | None = None
    parsed: dict[str, Any] | None = None
    for attempt in range(1, attempts + 1):
        retry_prompt = prompt
        if attempt > 1:
            retry_prompt = (
                prompt
                + "\n\nYour previous response was not parseable JSON. "
                "Return only a strict JSON object with double-quoted keys and "
                "no markdown fences, prose, comments, trailing commas, or "
                "JavaScript-style values."
            )
        raw = call_claude(retry_prompt, model=model, timeout_sec=timeout_sec)
        try:
            parsed = _parse_json_from_response(raw)
            break
        except Exception as exc:  # noqa: BLE001 - preserve last parse failure for operator context
            last_error = exc

    if parsed is None:
        raise RuntimeError(
            f"Claude judge did not return parseable JSON after {attempts} attempt(s): "
            f"{last_error}"
        )
    scores = parsed.get("scores") or []
    score_map = {item.get("criterion_id"): item for item in scores if isinstance(item, dict)}

    for criterion in criteria:
        score = score_map.get(criterion["criterion_id"], {})
        missing = not score
        confidence = float(score.get("confidence", 0.0 if missing else 0.5))
        result.criteria.append(
            CriterionResult(
                criterion_id=criterion["criterion_id"],
                category=criterion["category"],
                description=criterion["description"],
                met=bool(score.get("met", False)),
                confidence=confidence,
                reasoning=str(
                    score.get("reasoning")
                    or "Criterion missing from local Claude judge response."
                ),
                weight=float(criterion.get("weight", 1.0)),
                flagged_for_review=missing or confidence < 0.6,
            )
        )

    result.human_review_required = any(item.flagged_for_review for item in result.criteria)
    result.judge_notes = str(parsed.get("overall_notes", ""))
    _compute_scores(result, rubric)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Score an eval output using local Claude CLI and repo rubric parsing."
    )
    parser.add_argument("--output", type=Path, required=True, help="Candidate output markdown file.")
    parser.add_argument("--rubric", type=Path, required=True, help="Rubric YAML file.")
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout-sec", type=int, default=600)
    parser.add_argument("--json-out", type=Path, help="Write score JSON to this path.")
    parser.add_argument(
        "--dry-run-criteria",
        action="store_true",
        help="Parse rubric criteria and print them without calling Claude.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rubric = load_rubric(args.rubric)

    if args.dry_run_criteria:
        criteria = _extract_criteria_from_rubric(rubric)
        print(json.dumps({"criteria_count": len(criteria), "criteria": criteria}, indent=2))
        return 0

    if not args.output.exists():
        raise SystemExit(f"Output file does not exist: {args.output}")

    output_text = args.output.read_text(encoding="utf-8")
    result = score_output(
        output_text=output_text,
        rubric=rubric,
        fixture_id=args.fixture_id,
        condition=args.condition,
        model=args.model,
        timeout_sec=args.timeout_sec,
    )
    payload = judge_result_to_dict(result)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
