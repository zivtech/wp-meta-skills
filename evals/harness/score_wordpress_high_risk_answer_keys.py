#!/usr/bin/env python3
"""Score high-risk WordPress saved outputs against rubric answer keys.

This is a deterministic answer-key coverage check for already-archived
high-risk WordPress outputs. It reads each suite rubric's `domain_signals`,
checks the saved outputs for must-detect items, expected WordPress APIs, and
must-not-claim anti-patterns, then writes a compact scorecard.

Boundary: this is lexical answer-key evidence. It is not an LLM judge, human
review, Playground/runtime proof, variance measurement, or benchmark
superiority proof.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit(f"Unable to import PyYAML: {exc}") from exc


ROOT = Path(__file__).resolve().parents[2]
SUITES_ROOT = ROOT / "evals" / "suites"
RESULTS_ROOT = ROOT / "evals" / "results"
DEFAULT_OUT_DIR = RESULTS_ROOT / "wordpress-high-risk-answer-key-20260621"
DEFAULT_SAVED_RUNS = {
    "wordpress-security-critic": "wordpress-security-critic-saved-outputs-20260621",
    "wordpress-performance-critic": "wordpress-performance-critic-saved-outputs-20260621",
    "wordpress-planner.migration": "wordpress-planner-migration-saved-outputs-20260621",
}
DEFAULT_CONDITIONS = ("skill", "baseline-zero-shot", "baseline-few-shot")
STOPWORDS = {
    "a",
    "all",
    "an",
    "and",
    "are",
    "as",
    "be",
    "before",
    "by",
    "can",
    "do",
    "does",
    "for",
    "from",
    "in",
    "is",
    "it",
    "later",
    "make",
    "makes",
    "missing",
    "must",
    "need",
    "needs",
    "not",
    "of",
    "on",
    "or",
    "provided",
    "requires",
    "safe",
    "should",
    "the",
    "this",
    "to",
    "without",
}
NEGATION_MARKERS = (
    "not ",
    "no ",
    "does not ",
    "do not ",
    "doesn't ",
    "is not ",
    "are not ",
    "cannot ",
    "can't ",
    "without ",
    "outside ",
    "not claiming ",
    "not prove ",
    "not proof ",
    "not provided ",
)


@dataclass(frozen=True)
class ItemResult:
    item: str
    matched: bool
    evidence: str | None
    score: float
    negated: bool = False


@dataclass(frozen=True)
class OutputScore:
    suite: str
    fixture_id: str
    condition: str
    output_path: str
    rubric_path: str
    recall: float | None
    api_coverage: float | None
    specificity: float | None
    composite: float | None
    detected_count: int
    must_detect_count: int
    api_matched_count: int
    api_count: int
    anti_claim_count: int
    anti_count: int
    must_detect: list[ItemResult]
    expected_apis: list[ItemResult]
    must_not_claim: list[ItemResult]


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("=>", " ")
    text = text.replace("->", " ")
    text = re.sub(r"[^a-z0-9_]+", " ", text)
    return " ".join(text.split())


def tokens(text: str) -> list[str]:
    return [token for token in normalize(text).split() if token and token not in STOPWORDS]


def evidence_excerpt(text: str, matched_tokens: list[str]) -> str | None:
    if not matched_tokens:
        return None
    lower = text.lower()
    positions = [lower.find(token.lower()) for token in matched_tokens if lower.find(token.lower()) >= 0]
    if not positions:
        return None
    start = max(min(positions) - 60, 0)
    end = min(max(positions) + 160, len(text))
    return " ".join(text[start:end].split())


def phrase_score(item: str, response: str) -> tuple[float, str | None]:
    item_norm = normalize(item)
    response_norm = normalize(response)
    if item_norm and item_norm in response_norm:
        return 1.0, evidence_excerpt(response, tokens(item))

    item_tokens = tokens(item)
    if not item_tokens:
        return 0.0, None
    response_tokens = set(tokens(response))
    matched = [token for token in item_tokens if token in response_tokens]
    score = len(matched) / len(item_tokens)
    return score, evidence_excerpt(response, matched)


def item_detected(item: str, response: str, *, threshold: float = 0.55) -> ItemResult:
    score, evidence = phrase_score(item, response)
    return ItemResult(
        item=item,
        matched=score >= threshold,
        evidence=evidence,
        score=round(score, 4),
    )


def api_detected(api: str, response: str) -> ItemResult:
    response_norm = normalize(response)
    api_tokens = [token.rstrip("_") for token in tokens(api.replace("*", ""))]
    matched = bool(api_tokens) and all(token in response_norm for token in api_tokens)
    score = 1.0 if matched else 0.0
    return ItemResult(
        item=api,
        matched=matched,
        evidence=evidence_excerpt(response, api_tokens) if matched else None,
        score=score,
    )


def is_negated_item_context(response: str, item: str) -> bool:
    lower = response.lower()
    item_tokens = tokens(item)
    positions = [lower.find(token.lower()) for token in item_tokens if lower.find(token.lower()) >= 0]
    index = min(positions) if positions else -1
    if index < 0:
        return False
    window = lower[max(0, index - 120): index + 80]
    return any(marker in window for marker in NEGATION_MARKERS)


def anti_claimed(item: str, response: str) -> ItemResult:
    item_norm = normalize(item)
    response_norm = normalize(response)
    score = 1.0 if item_norm and item_norm in response_norm else 0.0
    evidence = evidence_excerpt(response, tokens(item)) if score else None
    negated = is_negated_item_context(response, item)
    # Anti-patterns are claim-shaped and easy to false-positive with lexical
    # matching, so require the exact normalized phrase. Semantic anti-claim
    # review belongs to the later QA/test-critic pass.
    matched = bool(score) and not negated
    return ItemResult(
        item=item,
        matched=matched,
        evidence=evidence,
        score=round(score, 4),
        negated=negated,
    )


def mean(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def rubric_path_for(suite: str, fixture_id: str) -> Path:
    path = SUITES_ROOT / suite / "rubrics" / f"{fixture_id}.rubric.yaml"
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def saved_output_path(run_id: str, suite: str, condition: str, fixture_id: str) -> Path:
    return RESULTS_ROOT / run_id / "raw" / suite / condition / f"{fixture_id}.md"


def fixture_ids_for_saved_run(run_id: str, suite: str, conditions: list[str], include_smoke: bool) -> list[str]:
    ids: set[str] = set()
    for condition in conditions:
        raw_dir = RESULTS_ROOT / run_id / "raw" / suite / condition
        for path in raw_dir.glob("*.md"):
            if include_smoke or path.stem != "smoke-wordpress-v1":
                ids.add(path.stem)
    return sorted(ids)


def score_output(suite: str, run_id: str, fixture_id: str, condition: str) -> OutputScore:
    output_path = saved_output_path(run_id, suite, condition, fixture_id)
    if not output_path.exists():
        raise FileNotFoundError(output_path)
    rubric_path = rubric_path_for(suite, fixture_id)
    rubric = load_yaml(rubric_path)
    signals = rubric.get("domain_signals") or {}
    response = output_path.read_text(encoding="utf-8")

    must_detect_items = list(signals.get("must_detect") or [])
    expected_apis = list(signals.get("expected_wordpress_apis") or [])
    must_not_claim_items = list(signals.get("must_not_claim") or signals.get("anti_patterns") or [])

    detect_results = [item_detected(item, response) for item in must_detect_items]
    api_results = [api_detected(api, response) for api in expected_apis]
    anti_results = [anti_claimed(item, response) for item in must_not_claim_items]

    detected_count = sum(result.matched for result in detect_results)
    api_matched_count = sum(result.matched for result in api_results)
    anti_claim_count = sum(result.matched for result in anti_results)

    recall = (detected_count / len(detect_results)) if detect_results else None
    api_coverage = (api_matched_count / len(api_results)) if api_results else None
    specificity = (1 - anti_claim_count / len(anti_results)) if anti_results else None
    composite = mean([recall, api_coverage, specificity])

    return OutputScore(
        suite=suite,
        fixture_id=fixture_id,
        condition=condition,
        output_path=rel(output_path),
        rubric_path=rel(rubric_path),
        recall=recall,
        api_coverage=api_coverage,
        specificity=specificity,
        composite=composite,
        detected_count=detected_count,
        must_detect_count=len(detect_results),
        api_matched_count=api_matched_count,
        api_count=len(api_results),
        anti_claim_count=anti_claim_count,
        anti_count=len(anti_results),
        must_detect=detect_results,
        expected_apis=api_results,
        must_not_claim=anti_results,
    )


def summarize(scores: list[OutputScore]) -> dict[str, Any]:
    by_suite_condition: dict[str, dict[str, Any]] = {}
    for suite in sorted({score.suite for score in scores}):
        for condition in sorted({score.condition for score in scores if score.suite == suite}):
            rows = [score for score in scores if score.suite == suite and score.condition == condition]
            by_suite_condition[f"{suite}::{condition}"] = {
                "suite": suite,
                "condition": condition,
                "count": len(rows),
                "recall": mean([row.recall for row in rows]),
                "api_coverage": mean([row.api_coverage for row in rows]),
                "specificity": mean([row.specificity for row in rows]),
                "composite": mean([row.composite for row in rows]),
                "detected_count": sum(row.detected_count for row in rows),
                "must_detect_count": sum(row.must_detect_count for row in rows),
                "api_matched_count": sum(row.api_matched_count for row in rows),
                "api_count": sum(row.api_count for row in rows),
                "anti_claim_count": sum(row.anti_claim_count for row in rows),
                "anti_count": sum(row.anti_count for row in rows),
            }
    return by_suite_condition


def fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_scorecard(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# WordPress High-Risk Answer-Key Scorecard",
        "",
        f"- Run: `{summary['run_id']}`",
        f"- Created: `{summary['created_at']}`",
        f"- Suites: {', '.join(f'`{suite}`' for suite in summary['suites'])}",
        f"- Conditions: {', '.join(f'`{condition}`' for condition in summary['conditions'])}",
        "",
        "## Boundary",
        "",
        summary["evidence_boundary"],
        "",
        "## Suite And Condition Means",
        "",
        "| Suite | Condition | n | Recall | API coverage | Specificity | Composite |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["by_suite_condition"].values():
        lines.append(
            "| {suite} | {condition} | {count} | {recall} | {api} | {spec} | {comp} |".format(
                suite=row["suite"],
                condition=row["condition"],
                count=row["count"],
                recall=fmt(row["recall"]),
                api=fmt(row["api_coverage"]),
                spec=fmt(row["specificity"]),
                comp=fmt(row["composite"]),
            )
        )

    lines.extend(["", "## Per-Fixture Scores", ""])
    for score in summary["scores"]:
        lines.append(
            "- `{suite}` / `{fixture}` / `{condition}`: composite `{comp}`, "
            "recall `{recall}`, API `{api}`, specificity `{spec}`".format(
                suite=score["suite"],
                fixture=score["fixture_id"],
                condition=score["condition"],
                comp=fmt(score["composite"]),
                recall=fmt(score["recall"]),
                api=fmt(score["api_coverage"]),
                spec=fmt(score["specificity"]),
            )
        )

    lines.extend(
        [
            "",
            "## Not Claimed",
            "",
            "- This does not replace QA/test-critic review.",
            "- This does not prove finding quality, exploitability, production impact, or migration readiness.",
            "- This does not prove the skill lanes outperform current ChatGPT-level baselines.",
            "- This does not score `wordpress-blueprint-executor`; that lane still needs a recorded Playground launch smoke before runtime claims.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_suite_run(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("suite run must be SUITE=RUN_ID")
    suite, run_id = value.split("=", 1)
    suite = suite.strip()
    run_id = run_id.strip()
    if not suite or not run_id:
        raise argparse.ArgumentTypeError("suite and run ID must be non-empty")
    return suite, run_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="wordpress-high-risk-answer-key-20260621")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--suite-run",
        action="append",
        type=parse_suite_run,
        help="Map a suite to a saved-output run: SUITE=RUN_ID. Defaults to the known 20260621 high-risk runs.",
    )
    parser.add_argument(
        "--conditions",
        default=",".join(DEFAULT_CONDITIONS),
        help="Comma-separated conditions to score.",
    )
    parser.add_argument(
        "--include-smoke",
        action="store_true",
        help="Include smoke-wordpress-v1 fixtures. Defaults to focused non-smoke fixtures only.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    suite_runs = dict(args.suite_run or DEFAULT_SAVED_RUNS.items())
    conditions = [condition.strip() for condition in args.conditions.split(",") if condition.strip()]
    if not conditions:
        raise SystemExit("At least one condition is required")

    scores: list[OutputScore] = []
    fixtures_by_suite: dict[str, list[str]] = {}
    for suite, saved_run in suite_runs.items():
        fixtures = fixture_ids_for_saved_run(saved_run, suite, conditions, args.include_smoke)
        fixtures_by_suite[suite] = fixtures
        for fixture_id in fixtures:
            for condition in conditions:
                scores.append(score_output(suite, saved_run, fixture_id, condition))

    summary = {
        "run_id": args.run_id,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "suites": sorted(suite_runs),
        "saved_runs": suite_runs,
        "conditions": conditions,
        "include_smoke": bool(args.include_smoke),
        "fixtures_by_suite": fixtures_by_suite,
        "evidence_boundary": (
            "Deterministic lexical answer-key coverage over archived saved outputs. "
            "It uses rubric domain_signals for must-detect items, expected WordPress "
            "APIs, and must-not-claim anti-patterns. It is not semantic LLM judging, "
            "human review, variance measurement, runtime proof, or benchmark "
            "superiority evidence."
        ),
        "by_suite_condition": summarize(scores),
        "scores": [asdict(score) for score in scores],
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "answer-key-summary.json", summary)
    write_scorecard(args.out_dir / "scorecard.md", summary)
    print(f"Wrote {rel(args.out_dir / 'answer-key-summary.json')}")
    print(f"Wrote {rel(args.out_dir / 'scorecard.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
