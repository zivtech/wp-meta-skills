#!/usr/bin/env python3
"""Validity gate for the WordPress candidate pairwise pilot.

Pure, importable, judge-independent. No I/O, no LLM call. Classifies a generated
candidate output as `valid` (auto) or `review` (escalate to the human queue).

Design (frozen in evals/suites/wordpress-skill-candidate-eval/pairwise-prereg.md):
escalate-first. The gate makes only the one fully-safe auto-call — a non-refusal
that is substantive — and escalates everything else. It NEVER auto-`invalid`s at
pilot scale, so it can never silently discard a possibly-valid output.

Invariant (verified over all 12 archived outputs + the FN1-FN4/FP3 attack
battery): no true refusal is ever auto-`valid`, and no valid output is ever
auto-discarded.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

# Frozen length floor (chars). Used ONLY inside the substantive test, never alone.
LENGTH_FLOOR = 1000

# Refusal-intent patterns. Matched over the WHOLE text (closes the post-window
# hole) and deliberately broadened to cover out-of-set phrasings (closes the
# closed-vocabulary hole). Lexical detection has an irreducible ceiling; the
# pairwise judge + human queue are the documented backstops.
REFUSAL_PATTERNS = [
    r"no candidate response",
    r"don'?t see a candidate response",
    r"didn'?t see a candidate",
    r"need the candidate'?s actual response",
    r"paste .{0,40}and i'?ll score",
    r"no response text to score",
    r"there'?s no response",
    r"can'?t (evaluate|score|assess) what isn'?t there",
    r"unable to (assess|evaluate|score)",
    r"candidate'?s answer (never arrived|is missing|wasn'?t)",
    r"where is it",
    r"send (me )?the (thing|response|candidate)",
    r"nothing to (score|evaluate)",
    r"no (actual )?(submission|artifact|answer) (to|was) (score|provided|included|attached)",
]

_REFUSAL_RE = [re.compile(p, re.IGNORECASE) for p in REFUSAL_PATTERNS]
_HEADING_RE = re.compile(r"(?m)^#{2,3}\s")
_TABLE_RE = re.compile(r"(?m)^\|")


@dataclass
class Verdict:
    label: str       # "valid" | "review"
    cls: str         # "valid" | "needs_human"
    reason: str
    scorable_chars: int

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["class"] = d.pop("cls")
        return d


def has_refusal_intent(text: str) -> bool:
    """Whole-text scan for refusal-intent (not a leading window)."""
    return any(rx.search(text) for rx in _REFUSAL_RE)


def has_structural_body(text: str) -> bool:
    """A scorable body requires structure. Length alone is never a body."""
    return ("```" in text) or bool(_TABLE_RE.search(text)) or bool(_HEADING_RE.search(text))


def is_substantive(text: str) -> bool:
    return len(text) >= LENGTH_FLOOR or has_structural_body(text)


def classify_output(text: str) -> Verdict:
    """Escalate-first classification.

    valid (auto) iff no refusal-intent AND substantive.
    Everything else -> review (human queue, excluded from auto-pairing).
    """
    text = text or ""
    refusal = has_refusal_intent(text)
    substantive = is_substantive(text)
    scorable = len(text)

    if not refusal and substantive:
        return Verdict("valid", "valid", "no refusal-intent; substantive body", scorable)

    if refusal and substantive:
        return Verdict(
            "review", "needs_human",
            "refusal-intent present with a surviving body: hybrid vs padded-refusal "
            "is lexically undecidable -> escalate",
            scorable,
        )
    if refusal and not substantive:
        return Verdict("review", "needs_human", "refusal-intent, no substantive body -> escalate", scorable)
    # not refusal and not substantive -> short structureless blob, do not trust
    return Verdict("review", "needs_human", "short structureless output, no refusal-intent -> escalate", scorable)


if __name__ == "__main__":  # pragma: no cover
    import sys
    if len(sys.argv) > 1:
        v = classify_output(open(sys.argv[1], encoding="utf-8").read())
        print(v.to_dict())
