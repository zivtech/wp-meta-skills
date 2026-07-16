#!/usr/bin/env python3
"""
LLM-as-judge scoring module for the zivtech-meta-skills eval harness.

Replaces semantic-similarity scoring with rubric-aware LLM grading.
Each must_find / should_find criterion is scored independently.
Low-confidence criteria are flagged for human review.

Cost controls:
  - Default judge model: claude-haiku-4-5  (cheap, fast)
  - Disputed / low-confidence re-grade: claude-sonnet-4-6
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Model tiers
# ---------------------------------------------------------------------------

HAIKU_MODEL = "claude-haiku-4-5"
SONNET_MODEL = "claude-sonnet-4-6"

# Confidence threshold below which a criterion is re-graded with Sonnet
LOW_CONFIDENCE_THRESHOLD = 0.6

# Maximum tokens for judge response
MAX_TOKENS_JUDGE = 4096

# Design-tooling benchmark model-critic scoring is Codex-first by user request. Keep this
# Anthropic API judge disabled for that suite unless the operator intentionally opts into
# direct API cost. This does not prohibit Claude Code as an operator workflow.
DESIGN_TOOLING_ALLOW_ENV = "ALLOW_ANTHROPIC_FOR_DESIGN_TOOLING"
DOMAIN_SIGNAL_KEYS = frozenset({
    "expected_wordpress_apis", "expected_surfaces", "must_detect",
    "must_not_claim", "must_not_penalize_or_do",
})

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CriterionResult:
    """Score for a single rubric criterion."""

    criterion_id: str
    category: str  # must_find | should_find | nice_to_find | quality | false_positive_trap
    description: str
    met: bool
    confidence: float  # 0.0 – 1.0
    reasoning: str
    weight: float = 1.0
    flagged_for_review: bool = False
    regraded: bool = False


@dataclass
class JudgeResult:
    """Aggregated result for one (fixture, condition) pair."""

    fixture_id: str
    condition: str
    criteria: list[CriterionResult] = field(default_factory=list)
    # Derived scores (populated by compute_scores())
    must_find_score: float = 0.0       # 0 – 100
    should_find_score: float = 0.0
    nice_to_find_score: float = 0.0
    false_positive_penalty: float = 0.0
    composite_score: float = 0.0
    human_review_required: bool = False
    judge_notes: str = ""
    model_used: str = HAIKU_MODEL


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

CRITERION_JUDGE_PROMPT = """\
You are a rigorous evaluation judge for AI-generated skill outputs.

## Task
Score whether the skill output satisfies the criterion described below.

## Skill Output
{output_text}

## Criterion
- ID: {criterion_id}
- Category: {category}
- Description: {description}
{evidence_hint}

## Instructions
Decide whether the skill output satisfies this criterion.

Return ONLY valid JSON with this exact schema:
{{
  "met": true or false,
  "confidence": 0.0 to 1.0,
  "reasoning": "1-2 sentences citing specific evidence from the output"
}}

Rules:
- "met" is true if the output clearly satisfies the criterion.
- "confidence" reflects how certain you are: 1.0 = certain, 0.5 = genuinely ambiguous.
- "reasoning" must reference specific text from the output, not generic statements.
- For false_positive_trap criteria, "met" = true means the trap WAS triggered (bad).
"""

BATCH_JUDGE_PROMPT = """\
You are a rigorous evaluation judge for AI-generated skill outputs.

## Task
Score the skill output against each rubric criterion listed below.

## Skill Output
{output_text}

## Rubric Criteria
{criteria_yaml}

## Scoring Instructions
For each criterion, provide:
- met: true if the output satisfies the criterion (for false_positive_trap: true = trap triggered)
- confidence: 0.0 to 1.0 (1.0 = certain, 0.5 = genuinely ambiguous)
- reasoning: 1-2 sentences citing specific text from the output

Return ONLY valid JSON with this exact schema:
{{
  "scores": [
    {{
      "criterion_id": "...",
      "met": true or false,
      "confidence": 0.0 to 1.0,
      "reasoning": "..."
    }}
  ],
  "overall_notes": "2-3 sentence summary of the output quality"
}}
"""


# ---------------------------------------------------------------------------
# Rubric parsing
# ---------------------------------------------------------------------------


def _validated_domain_signals(rubric: dict[str, Any]) -> dict[str, list[str]]:
    raw = rubric.get("domain_signals")
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not raw or not set(raw).issubset(DOMAIN_SIGNAL_KEYS):
        raise ValueError("domain_signals must be a nonempty mapping of accepted fields")
    validated: dict[str, list[str]] = {}
    for key, value in raw.items():
        if not isinstance(value, list) or not value:
            raise ValueError(f"domain_signals.{key} must be a nonempty string list")
        if not all(type(item) is str and item.strip() for item in value):
            raise ValueError(f"domain_signals.{key} must contain nonblank strings")
        validated[key] = value
    return validated


def _domain_summary_criteria(signals: dict[str, list[str]]) -> list[dict[str, Any]]:
    criteria: list[dict[str, Any]] = []
    expected_apis = signals.get("expected_wordpress_apis") or []
    if expected_apis:
        criteria.append({
            "criterion_id": "domain_expected_wordpress_apis",
            "category": "domain_wordpress_api",
            "description": (
                "Uses relevant WordPress APIs when applicable, such as "
                f"{', '.join(expected_apis)}. Do not require every listed API "
                "if it is not relevant to the fixture."
            ),
            "evidence_hint": "", "weight": 1.0,
        })
    expected_surfaces = signals.get("expected_surfaces") or []
    if expected_surfaces:
        criteria.append({
            "criterion_id": "domain_expected_surfaces", "category": "quality",
            "description": (
                "Uses relevant artifact or verification surfaces when applicable, "
                f"such as {', '.join(expected_surfaces)}. Do not require every "
                "listed surface when it is irrelevant to the fixture."
            ),
            "evidence_hint": "", "weight": 1.0,
        })
    return criteria


def _domain_item_criteria(signals: dict[str, list[str]]) -> list[dict[str, Any]]:
    criteria: list[dict[str, Any]] = []
    for i, signal in enumerate(signals.get("must_detect") or []):
        criteria.append({
            "criterion_id": f"domain_must_detect_{i+1}",
            "category": "domain_must_detect",
            "description": (
                "Detects or plans around this fixture-specific WordPress risk "
                f"or requirement: {signal}"
            ),
            "evidence_hint": "", "weight": 1.0,
        })
    trap_fields = (
        ("must_not_penalize_or_do", "domain_false_positive_trap_", "Triggers this discouraged behavior, unsafe recommendation, or false positive: "),
        ("must_not_claim", "domain_must_not_claim_trap_", "Makes this unsupported claim: "),
    )
    for field, prefix, description in trap_fields:
        for i, trap in enumerate(signals.get(field) or []):
            criteria.append({
                "criterion_id": f"{prefix}{i+1}",
                "category": "false_positive_trap",
                "description": f"{description}{trap}",
                "evidence_hint": "", "weight": 1.0,
            })
    return criteria


def _domain_signal_criteria(rubric: dict[str, Any]) -> list[dict[str, Any]]:
    signals = _validated_domain_signals(rubric)
    return _domain_summary_criteria(signals) + _domain_item_criteria(signals)


def _explicit_false_positive_criteria(rubric: dict[str, Any]) -> list[dict[str, Any]]:
    criteria: list[dict[str, Any]] = []
    for i, trap in enumerate(rubric.get("false_positive_traps") or []):
        if isinstance(trap, dict):
            criteria.append({
                "criterion_id": trap.get("id", f"FP{i+1}"),
                "category": "false_positive_trap",
                "description": trap.get("description", ""),
                "evidence_hint": "", "weight": float(trap.get("weight", 1)),
            })
    return criteria


def _extract_criteria_from_rubric(rubric: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract a flat list of criteria from a rubric YAML dict.

    Handles both the simple list style (qa-critic) and the
    expected_findings list style (copy-critic / metadata-embedded).
    """
    criteria: list[dict[str, Any]] = []

    # Style A: top-level must_find / should_find / nice_to_find lists
    for category in ("must_find", "should_find", "nice_to_find"):
        items = rubric.get(category) or []
        if isinstance(items, list):
            for i, item in enumerate(items):
                if isinstance(item, dict):
                    criteria.append(
                        {
                            "criterion_id": item.get("id", f"{category}_{i+1}"),
                            "category": category,
                            "description": item.get("description", ""),
                            "evidence_hint": item.get("evidence_requirement", ""),
                        }
                    )

    # Style B: expected_findings list
    for finding in rubric.get("expected_findings") or []:
        cat = finding.get("category", "")
        for i, item in enumerate(finding.get("items") or []):
            if isinstance(item, dict):
                criteria.append(
                    {
                        "criterion_id": item.get("id", f"{cat}_{i+1}"),
                        "category": cat,
                        "description": item.get("description", ""),
                        "evidence_hint": item.get("evidence", ""),
                    }
                )

    # Style C: quality-weighted rubric used by candidate-comparison suites.
    # These criteria are intentionally not forced into must/should/nice buckets;
    # _compute_scores applies the explicit item weights when this style is used.
    for i, item in enumerate(rubric.get("criteria") or []):
        if isinstance(item, dict):
            criteria.append(
                {
                    "criterion_id": item.get("id", f"criteria_{i+1}"),
                    "category": item.get("category", item.get("type", "quality")),
                    "description": item.get("description", ""),
                    "evidence_hint": item.get("evidence_requirement", ""),
                    "weight": float(item.get("weight", 1)),
                }
            )

    # Candidate-comparison rubrics may include fixture-specific domain signals.
    # Turn these into scoreable criteria so the judge cannot reward fluent
    # genericism while missing concrete WordPress risks or recommending unsafe
    # patterns.
    criteria.extend(_domain_signal_criteria(rubric))
    criteria.extend(_explicit_false_positive_criteria(rubric))

    criterion_ids = [item["criterion_id"] for item in criteria]
    if not all(type(item) is str and item.strip() for item in criterion_ids):
        raise ValueError("rubric criteria IDs must be nonblank strings")
    if len(criterion_ids) != len(set(criterion_ids)):
        raise ValueError("rubric criteria produce duplicate criterion IDs")
    return criteria


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------


def _call_judge(
    client: Any,
    prompt: str,
    model: str,
) -> str:
    """Call the Anthropic API and return the raw text response."""
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS_JUDGE,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def _parse_json_from_response(raw: str) -> dict[str, Any]:
    """Extract and parse JSON from a response that may include markdown fencing."""
    # Strip markdown code blocks
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"```", "", cleaned)
    # Find outermost braces
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in response:\n{raw[:400]}")
    return json.loads(match.group())


def _grade_criterion_single(
    client: Any,
    output_text: str,
    criterion: dict[str, Any],
    model: str,
) -> tuple[bool, float, str]:
    """
    Grade a single criterion. Returns (met, confidence, reasoning).
    """
    evidence_hint = ""
    if criterion.get("evidence_hint"):
        evidence_hint = f"- Evidence hint: {criterion['evidence_hint']}"

    prompt = CRITERION_JUDGE_PROMPT.format(
        output_text=output_text[:8000],  # guard context window
        criterion_id=criterion["criterion_id"],
        category=criterion["category"],
        description=criterion["description"],
        evidence_hint=evidence_hint,
    )

    raw = _call_judge(client, prompt, model)
    parsed = _parse_json_from_response(raw)
    met = bool(parsed.get("met", False))
    confidence = float(parsed.get("confidence", 0.5))
    reasoning = str(parsed.get("reasoning", ""))
    return met, confidence, reasoning


def _grade_criteria_batch(
    client: Any,
    output_text: str,
    criteria: list[dict[str, Any]],
    model: str,
) -> list[dict[str, Any]]:
    """
    Grade multiple criteria in a single API call.
    Returns list of {criterion_id, met, confidence, reasoning}.
    """
    import yaml  # optional dep; fall back gracefully

    try:
        criteria_yaml = yaml.dump(criteria, default_flow_style=False)
    except Exception:
        criteria_yaml = json.dumps(criteria, indent=2)

    prompt = BATCH_JUDGE_PROMPT.format(
        output_text=output_text[:8000],
        criteria_yaml=criteria_yaml,
    )

    raw = _call_judge(client, prompt, model)
    parsed = _parse_json_from_response(raw)
    return parsed.get("scores", [])


# ---------------------------------------------------------------------------
# Main scoring entry point
# ---------------------------------------------------------------------------


def score_with_llm_judge(
    output_text: str,
    rubric: dict[str, Any],
    fixture_id: str,
    condition: str,
    client: Any | None = None,
    primary_model: str = HAIKU_MODEL,
    regrade_model: str = SONNET_MODEL,
    use_batch: bool = True,
) -> JudgeResult:
    """
    Score a skill output against a rubric using an LLM judge.

    Args:
        output_text:    The skill's generated output.
        rubric:         Parsed rubric YAML as a dict.
        fixture_id:     Fixture identifier (for result labelling).
        condition:      Condition identifier (skill / baseline-zero-shot / …).
        client:         Anthropic client. Created from ANTHROPIC_API_KEY if None.
        primary_model:  Model for initial grading (default: Haiku).
        regrade_model:  Model for low-confidence re-grading (default: Sonnet).
        use_batch:      Batch all criteria in one call when True (faster/cheaper).

    Returns:
        JudgeResult with per-criterion scores and composite.
    """
    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY environment variable is not set")
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "The optional anthropic SDK is required for the LLM judge lane"
            ) from exc
        client = anthropic.Anthropic(api_key=api_key)

    criteria = _extract_criteria_from_rubric(rubric)
    result = JudgeResult(
        fixture_id=fixture_id,
        condition=condition,
        model_used=primary_model,
    )

    if not criteria:
        # Nothing to grade; return a default full-score result
        result.composite_score = 100.0
        result.judge_notes = "No criteria defined in rubric."
        return result

    # ── Initial grading pass ─────────────────────────────────────────────────
    if use_batch:
        batch_scores = _grade_criteria_batch(client, output_text, criteria, primary_model)
        score_map: dict[str, dict[str, Any]] = {
            s["criterion_id"]: s for s in batch_scores if isinstance(s, dict)
        }
    else:
        score_map = {}

    for crit in criteria:
        cid = crit["criterion_id"]

        if use_batch and cid in score_map:
            s = score_map[cid]
            met = bool(s.get("met", False))
            confidence = float(s.get("confidence", 0.5))
            reasoning = str(s.get("reasoning", ""))
        else:
            # Single-criterion fallback (batch missing this criterion)
            met, confidence, reasoning = _grade_criterion_single(
                client, output_text, crit, primary_model
            )

        cr = CriterionResult(
            criterion_id=cid,
            category=crit["category"],
            description=crit["description"],
            met=met,
            confidence=confidence,
            reasoning=reasoning,
            weight=float(crit.get("weight", 1.0)),
        )

        # ── Low-confidence re-grade with Sonnet ─────────────────────────────
        if confidence < LOW_CONFIDENCE_THRESHOLD:
            cr.flagged_for_review = True
            result.human_review_required = True
            remet, reconf, rereason = _grade_criterion_single(
                client, output_text, crit, regrade_model
            )
            cr.met = remet
            cr.confidence = reconf
            cr.reasoning = rereason
            cr.regraded = True
            result.model_used = regrade_model  # note escalation

        result.criteria.append(cr)

    _compute_scores(result, rubric)
    return result


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------


def _compute_scores(result: JudgeResult, rubric: dict[str, Any]) -> None:
    """
    Populate composite and per-category scores on result in-place.

    Weights follow the existing harness convention:
      must_find × 3, should_find × 2, nice_to_find × 1, false_positive_trap × -2
    """
    weights = {
        "must_find": 3,
        "should_find": 2,
        "nice_to_find": 1,
        "false_positive_trap": -2,
    }

    if rubric.get("criteria") or rubric.get("domain_signals"):
        _compute_weighted_candidate_scores(result)
        return

    by_cat: dict[str, list[CriterionResult]] = {k: [] for k in weights}
    for cr in result.criteria:
        bucket = by_cat.get(cr.category)
        if bucket is not None:
            bucket.append(cr)

    def _cat_score(items: list[CriterionResult], is_trap: bool = False) -> float:
        if not items:
            return 100.0
        if is_trap:
            # Score = fraction of traps NOT triggered (higher = better)
            not_triggered = sum(1 for c in items if not c.met)
            return (not_triggered / len(items)) * 100.0
        met = sum(1 for c in items if c.met)
        return (met / len(items)) * 100.0

    result.must_find_score = _cat_score(by_cat["must_find"])
    result.should_find_score = _cat_score(by_cat["should_find"])
    result.nice_to_find_score = _cat_score(by_cat["nice_to_find"])
    # Penalty: fraction of traps triggered, converted to a 0–100 penalty
    if by_cat["false_positive_trap"]:
        triggered = sum(1 for c in by_cat["false_positive_trap"] if c.met)
        result.false_positive_penalty = (triggered / len(by_cat["false_positive_trap"])) * 100.0
    else:
        result.false_positive_penalty = 0.0

    # Composite: weighted average of categories that have criteria
    numer = 0.0
    denom = 0.0
    for cat, w in weights.items():
        items = by_cat[cat]
        if not items:
            continue
        if cat == "false_positive_trap":
            not_triggered_frac = 1.0 - (result.false_positive_penalty / 100.0)
            numer += not_triggered_frac * abs(w) * 100.0
            denom += abs(w) * 100.0
        else:
            cat_score_val = (
                result.must_find_score if cat == "must_find"
                else result.should_find_score if cat == "should_find"
                else result.nice_to_find_score
            )
            numer += (cat_score_val / 100.0) * w * 100.0
            denom += w * 100.0

    result.composite_score = round((numer / denom) if denom > 0 else 100.0, 2)


def _compute_weighted_candidate_scores(result: JudgeResult) -> None:
    """
    Score candidate-comparison rubrics with explicit per-criterion weights.

    Positive criteria earn their weight when met. False-positive traps earn their
    weight when NOT triggered. The existing category score fields are populated
    for compatibility with downstream reporters.
    """
    positive = [c for c in result.criteria if c.category != "false_positive_trap"]
    traps = [c for c in result.criteria if c.category == "false_positive_trap"]

    def _weighted_score(items: list[CriterionResult], invert: bool = False) -> float:
        if not items:
            return 100.0
        denom = sum(max(c.weight, 0.0) for c in items)
        if denom <= 0:
            return 100.0
        earned = 0.0
        for item in items:
            satisfied = not item.met if invert else item.met
            if satisfied:
                earned += max(item.weight, 0.0)
        return (earned / denom) * 100.0

    must_like = [c for c in positive if c.category in {"must_find", "domain_must_detect"}]
    should_like = [
        c for c in positive
        if c.category in {"should_find", "quality", "domain_wordpress_api"}
    ]
    nice_like = [c for c in positive if c.category == "nice_to_find"]

    result.must_find_score = round(_weighted_score(must_like), 2)
    result.should_find_score = round(_weighted_score(should_like), 2)
    result.nice_to_find_score = round(_weighted_score(nice_like), 2)

    if traps:
        triggered = sum(max(c.weight, 0.0) for c in traps if c.met)
        denom = sum(max(c.weight, 0.0) for c in traps)
        result.false_positive_penalty = round((triggered / denom) * 100.0, 2) if denom else 0.0
    else:
        result.false_positive_penalty = 0.0

    total_weight = sum(max(c.weight, 0.0) for c in positive + traps)
    if total_weight <= 0:
        result.composite_score = 100.0
        return

    earned_weight = sum(max(c.weight, 0.0) for c in positive if c.met)
    earned_weight += sum(max(c.weight, 0.0) for c in traps if not c.met)
    result.composite_score = round((earned_weight / total_weight) * 100.0, 2)


# ---------------------------------------------------------------------------
# Convenience: load rubric and score from file paths
# ---------------------------------------------------------------------------


def score_output_file(
    output_path: Path,
    rubric_path: Path,
    fixture_id: str,
    condition: str,
    client: Any | None = None,
) -> JudgeResult:
    """
    Load output text and rubric YAML from disk, then run LLM judge scoring.

    Args:
        output_path:  Path to the skill's .md output file.
        rubric_path:  Path to the .rubric.yaml file.
        fixture_id:   Fixture identifier string.
        condition:    Condition string (skill / baseline-zero-shot / …).
        client:       Optional pre-constructed Anthropic client.

    Returns:
        JudgeResult
    """
    if (
        "design-tooling" in {part.lower() for part in output_path.parts}
        or "design-tooling" in {part.lower() for part in rubric_path.parts}
    ) and os.environ.get(DESIGN_TOOLING_ALLOW_ENV) != "1":
        raise RuntimeError(
            "Anthropic API LLM judge is disabled for evals/suites/design-tooling. "
            "Use the Codex-backed critic runner from critic-config.yaml, or set "
            f"{DESIGN_TOOLING_ALLOW_ENV}=1 only after explicit user approval."
        )

    try:
        import yaml
    except ImportError as exc:
        raise ImportError("PyYAML is required for rubric loading: pip install pyyaml") from exc

    output_text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    rubric: dict[str, Any] = {}
    if rubric_path.exists():
        rubric = yaml.safe_load(rubric_path.read_text(encoding="utf-8")) or {}

    return score_with_llm_judge(
        output_text=output_text,
        rubric=rubric,
        fixture_id=fixture_id,
        condition=condition,
        client=client,
    )


def judge_result_to_dict(result: JudgeResult) -> dict[str, Any]:
    """Serialize a JudgeResult to a JSON-compatible dict."""
    return {
        "fixture_id": result.fixture_id,
        "condition": result.condition,
        "composite_score": result.composite_score,
        "must_find_score": result.must_find_score,
        "should_find_score": result.should_find_score,
        "nice_to_find_score": result.nice_to_find_score,
        "false_positive_penalty": result.false_positive_penalty,
        "human_review_required": result.human_review_required,
        "model_used": result.model_used,
        "judge_notes": result.judge_notes,
        "criteria": [
            {
                "criterion_id": c.criterion_id,
                "category": c.category,
                "description": c.description,
                "met": c.met,
                "confidence": c.confidence,
                "reasoning": c.reasoning,
                "weight": c.weight,
                "flagged_for_review": c.flagged_for_review,
                "regraded": c.regraded,
            }
            for c in result.criteria
        ],
    }
