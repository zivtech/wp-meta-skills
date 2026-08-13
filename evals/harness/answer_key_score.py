#!/usr/bin/env python3
"""Answer-key DIAGNOSTIC scoring for the WordPress candidate eval.

A different instrument from the frozen pairwise preference eval. Instead of asking
a judge "which output is better?" (one bit, gestalt), it scores each output against
the OBJECTIVE answer key already in every rubric:

  domain_signals.must_detect            -> detection RECALL   (judged, atomic, span-verified)
  domain_signals.expected_wordpress_apis-> API COVERAGE       (deterministic substring, no judge)
  domain_signals.must_not_penalize_or_do-> SPECIFICITY        (1 - anti-pattern rate; judged, span-verified)

Design is frozen in
evals/suites/wordpress-skill-candidate-eval/answerkey-diagnostic-prereg.md.

Reliability posture (see prereg §4): atomic one-item-per-call; the judge is BLIND to
condition; a `present:true` verdict must quote a span that the harness verifies occurs
in the response (fabricated/absent span -> downgraded to false) — the key guard against
the documented agreeableness bias (judges over-confirm satisfied criteria); cross-family
judge by default (generations were Claude; default judge is a non-Claude codex model) so
the re-score is not self-graded.

PURE logic (pairing-free scoring, parsing, aggregation) is separated from the LLM I/O
(`check_item_via_cli` / `check_item_via_codex`) and is unit-tested. Nothing here mutates
the committed pairwise harness (`pairwise_judge.py`, `run_pairwise_pilot.py`).

Local `claude -p` (Claude) + `codex exec` (non-Claude); no ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

HARNESS_DIR = Path(__file__).resolve().parent
ROOT = HARNESS_DIR.parent.parent
SUITE = "wordpress-skill-candidate-eval"
SUITE_DIR = ROOT / "evals" / "suites" / SUITE
RESULTS_DIR = ROOT / "evals" / "results" / SUITE

CONDITIONS = ("baseline-zero-shot", "baseline-few-shot",
              "raw_upstream_candidate", "zivtech_prototype")
KNOWN_STRONG = "zivtech_prototype"
KNOWN_WEAK = "baseline-zero-shot"
PILOT_FIXTURES = ("security-boundary-risk", "block-development-risk",
                  "content-model-ambiguous", "performance-ops-clean")
# Adversarial fixtures (2026-06-19) — authored to defeat zero-shot + WPCS so the
# instrument has a discrimination gradient; each maps to the single zivtech agent
# whose protocol claims the relevant differentiator (capability!=nonce, taint, etc.).
ADVERSARIAL_FIXTURES = ("security-nonce-without-capability", "security-sql-aliased-taint",
                        "performance-subtle-real-issue", "block-deprecation-silent-break",
                        "security-overflag-trap")
NEW_FIXTURE_AGENTS = {
    "security-nonce-without-capability": "wordpress-security-critic",
    "security-sql-aliased-taint": "wordpress-security-critic",
    "performance-subtle-real-issue": "wordpress-performance-critic",
    "block-deprecation-silent-break": "wordpress-critic",
    "security-overflag-trap": "wordpress-security-critic",
}
DEFAULT_UPSTREAM_PROJECT = Path("/tmp/wp-agent-skills-pilot-project")

DISCRIMINATION_DELTA = 0.20   # suite-standard known-weak vs known-strong floor (prereg §6)
TIER_BY_SUFFIX = {"clean": "CLEAN_CONTROL", "risk": "HAS_RISK",
                  "ambiguous": "AMBIGUOUS_TRADEOFF"}


# --------------------------------------------------------------------------- #
# PURE: normalization, span + API matching
# --------------------------------------------------------------------------- #

def _norm_ws(text: str) -> str:
    """Lowercase + collapse all whitespace runs to single spaces."""
    return " ".join((text or "").lower().split())


def span_supported(span: str, response: str, *, min_chars: int = 40) -> bool:
    """A judge-quoted span is supported iff it actually occurs in the response
    (whitespace-normalized, case-insensitive). Long spans are checked on their
    first `min_chars` non-space chars to tolerate the judge truncating a quote.
    Empty span is never supported."""
    s = _norm_ws(span)
    if not s:
        return False
    r = _norm_ws(response)
    if s in r:
        return True
    head = s[:min_chars]
    return len(head) >= min_chars and head in r


def _norm_api(token: str) -> str:
    """Normalize an API/surface token for substring matching.

    Keep WordPress function underscores intact, but collapse common code/path/package
    punctuation so `@wordpress/scripts`, `templates/*.html`, `$wpdb->prepare()`,
    and "WP-CLI" can be compared without brittle punctuation misses.
    """
    t = (token or "").lower()
    t = t.replace("->", " ")
    t = re.sub(r"[^a-z0-9_]+", " ", t)
    return " ".join(t.split())


def api_match(expected: str, response: str) -> bool:
    """An expected API matches if every normalized token of it appears (as a
    normalized substring) in the response. Multi-word entries (e.g.
    'register_rest_route permission_callback') require ALL tokens present."""
    r = _norm_api(response)
    tokens = [tok for tok in _norm_api(expected).split(" ") if tok]
    return bool(tokens) and all(tok in r for tok in tokens)


def api_coverage(expected_apis: list[str], response: str) -> dict[str, Any]:
    matched = [a for a in expected_apis if api_match(a, response)]
    total = len(expected_apis)
    return {
        "matched": matched,
        "n_matched": len(matched),
        "n_total": total,
        "coverage": (len(matched) / total) if total else None,
    }


# --------------------------------------------------------------------------- #
# PURE: prompt construction + parsing
# --------------------------------------------------------------------------- #

def build_check_prompt(fixture_text: str, response: str, item: str, kind: str) -> str:
    """Atomic, blind, single-item check. `kind` in {'detect','anti'}.
    'detect': present == the response substantively identifies the issue.
    'anti':   present == the response COMMITS the listed mistake.
    No condition name is ever included."""
    if kind == "anti":
        target = "## The specific mistake to check for"
        ask = ("Decide ONLY whether the response actually COMMITS this mistake. "
               "Not committing it is good and common — say so when it does not.")
        yes_means = "the response commits the mistake"
    else:
        target = "## The specific issue the response should identify"
        ask = ("Decide ONLY whether the response substantively identifies / raises this "
               "issue (a vague gesture does not count). Absence is a valid and common "
               "answer — do not be charitable.")
        yes_means = "the response identifies the issue"
    return (
        "You audit ONE WordPress consulting response for ONE specific point. Judge only "
        "this point; ignore everything else about the response.\n\n"
        f"## Scenario\n{fixture_text.strip()}\n\n"
        f"{target}\n{item.strip()}\n\n"
        f"## Response under audit\n{response.strip()}\n\n"
        f"## Instructions\n{ask}\n"
        f"If YES ({yes_means}), you MUST quote the exact verbatim span from the response "
        "that proves it — copy it character-for-character from the response, do not "
        "paraphrase. If NO, return an empty span.\n\n"
        "## Output\nReturn ONLY strict JSON, nothing before or after:\n"
        '{"present": true|false, "span": "<exact verbatim quote from the response, or '
        'empty string>"}'
    )


def parse_check(raw: str) -> dict[str, Any]:
    """Extract {present, span, parse_ok} from a judge response, tolerant of
    fences/prose around the JSON. On failure returns present=False, parse_ok=False
    so unparseable calls are logged separately rather than silently counted."""
    s = (raw or "").strip()
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(s[start:end + 1])
            present = obj.get("present", False)
            if isinstance(present, str):
                present = present.strip().lower() in {"true", "yes", "1"}
            return {"present": bool(present),
                    "span": str(obj.get("span", "")).strip(),
                    "parse_ok": True}
        except json.JSONDecodeError:
            pass
    return {"present": False, "span": "", "parse_ok": False}


def confirm_item(parsed: dict[str, Any], response: str) -> dict[str, Any]:
    """Apply the span guard: a present=True verdict is CONFIRMED only if its span is
    supported by the response. Returns {confirmed, unsupported_span, parse_ok}."""
    if not parsed["present"]:
        return {"confirmed": False, "unsupported_span": False, "parse_ok": parsed["parse_ok"]}
    supported = span_supported(parsed["span"], response)
    return {"confirmed": supported, "unsupported_span": not supported,
            "parse_ok": parsed["parse_ok"]}


# --------------------------------------------------------------------------- #
# PURE: per-output scoring + aggregation
# --------------------------------------------------------------------------- #

def score_output(answer_key: dict[str, Any], response: str,
                 detect_results: dict[str, dict], anti_results: dict[str, dict]) -> dict[str, Any]:
    """Combine deterministic API coverage with confirmed detect/anti judgments into
    the three axes + composite. detect_results / anti_results map item -> confirm_item()."""
    md = answer_key.get("must_detect", [])
    ap = answer_key.get("anti_patterns", [])
    confirmed_detect = sum(1 for it in md if detect_results.get(it, {}).get("confirmed"))
    committed_anti = sum(1 for it in ap if anti_results.get(it, {}).get("confirmed"))
    api = api_coverage(answer_key.get("expected_apis", []), response)

    recall = (confirmed_detect / len(md)) if md else None
    specificity = (1 - committed_anti / len(ap)) if ap else None
    coverage = api["coverage"]
    parts = [v for v in (recall, coverage, specificity) if v is not None]
    composite = (sum(parts) / len(parts)) if parts else None
    return {
        "recall": recall, "api_coverage": coverage, "specificity": specificity,
        "composite": composite,
        "confirmed_detect": confirmed_detect, "n_must_detect": len(md),
        "committed_anti": committed_anti, "n_anti": len(ap),
        "api_matched": api["matched"], "n_api": api["n_total"],
        "unsupported_spans": sum(1 for d in list(detect_results.values()) + list(anti_results.values())
                                 if d.get("unsupported_span")),
        "parse_failures": sum(1 for d in list(detect_results.values()) + list(anti_results.values())
                              if not d.get("parse_ok")),
    }


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else None


def aggregate(scores: dict[tuple, dict], conditions, tiers_by_fixture) -> dict[str, Any]:
    """scores keyed by (fixture, condition, run) -> score_output dict. Returns per-condition
    and per-(condition,tier) means for each axis."""
    axes = ("recall", "api_coverage", "specificity", "composite")
    by_cond: dict[str, Any] = {}
    by_cond_tier: dict[str, Any] = {}
    for cond in conditions:
        rows = [v for (f, c, r), v in scores.items() if c == cond]
        by_cond[cond] = {ax: _mean([row[ax] for row in rows]) for ax in axes}
        by_cond[cond]["n"] = len(rows)
        tiers = sorted({tiers_by_fixture.get(f, "?") for (f, c, r) in scores if c == cond})
        for tier in tiers:
            rows_t = [v for (f, c, r), v in scores.items()
                      if c == cond and tiers_by_fixture.get(f) == tier]
            by_cond_tier[f"{cond}::{tier}"] = (
                {ax: _mean([row[ax] for row in rows_t]) for ax in axes} | {"n": len(rows_t)})
    return {"by_condition": by_cond, "by_condition_tier": by_cond_tier}


def _per_fixture_composite(scores: dict[tuple, dict], condition, fixtures) -> dict[str, float]:
    """Mean composite per fixture for one condition (runs averaged within fixture —
    respects clustering; runs are not independent samples)."""
    out = {}
    for f in fixtures:
        vals = [v["composite"] for (ff, c, r), v in scores.items()
                if ff == f and c == condition and v["composite"] is not None]
        if vals:
            out[f] = sum(vals) / len(vals)
    return out


def discrimination_check(scores, fixtures, strong=KNOWN_STRONG, weak=KNOWN_WEAK) -> dict[str, Any]:
    """Run FIRST (prereg §6): does the instrument see a gap where one must exist?
    mean composite(strong) - composite(weak), fixture-averaged. >= 0.20 -> discriminates."""
    s = _per_fixture_composite(scores, strong, fixtures)
    w = _per_fixture_composite(scores, weak, fixtures)
    shared = sorted(set(s) & set(w))
    deltas = [s[f] - w[f] for f in shared]
    mean_delta = _mean(deltas)
    return {
        "strong": strong, "weak": weak, "per_fixture_delta": {f: round(s[f] - w[f], 4) for f in shared},
        "mean_delta": None if mean_delta is None else round(mean_delta, 4),
        "threshold": DISCRIMINATION_DELTA,
        "discriminates": (mean_delta is not None and mean_delta >= DISCRIMINATION_DELTA),
    }


def cluster_bootstrap_delta(scores, fixtures, cond_a, cond_b, *, seed="boot", n_boot=2000) -> dict[str, Any]:
    """Bootstrap CI on mean composite delta (cond_a - cond_b), RESAMPLING FIXTURES
    (clusters), not individual outputs — per prereg §3 anti-pseudoreplication."""
    a = _per_fixture_composite(scores, cond_a, fixtures)
    b = _per_fixture_composite(scores, cond_b, fixtures)
    shared = sorted(set(a) & set(b))
    if not shared:
        return {"contrast": f"{cond_a} - {cond_b}", "mean_delta": None, "ci95": [None, None], "n_fixtures": 0}
    point = sum(a[f] - b[f] for f in shared) / len(shared)
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        samp = [shared[rng.randrange(len(shared))] for _ in shared]
        boots.append(sum(a[f] - b[f] for f in samp) / len(samp))
    boots.sort()
    lo = boots[int(0.025 * len(boots))]
    hi = boots[min(len(boots) - 1, int(0.975 * len(boots)))]
    return {"contrast": f"{cond_a} - {cond_b}", "mean_delta": round(point, 4),
            "ci95": [round(lo, 4), round(hi, 4)], "n_fixtures": len(shared)}


def judge_agreement(primary: dict[tuple, dict], secondary: dict[tuple, dict]) -> dict[str, Any]:
    """Per-item raw agreement on `confirmed` between two judges over shared item-keys
    (fixture, condition, run, kind, item). Secondary diagnostic only (prereg §4)."""
    shared = sorted(set(primary) & set(secondary), key=str)
    if not shared:
        return {"n_items": 0, "raw_agreement": None, "disagreements": []}
    agree = sum(1 for k in shared if primary[k]["confirmed"] == secondary[k]["confirmed"])
    disagreements = [list(k) for k in shared if primary[k]["confirmed"] != secondary[k]["confirmed"]]
    return {"n_items": len(shared), "raw_agreement": round(agree / len(shared), 4),
            "disagreements": disagreements[:50]}


# --------------------------------------------------------------------------- #
# PURE: judge-family balance (controls the confound named in prereg §4)
# --------------------------------------------------------------------------- #
#
# The pilot judged every condition with one non-Claude judge. Generation is split:
# the skill lane runs on a local Claude agent, every `baseline-*` lane on local
# Codex (generate_missing_critic). So the baselines were judged by their OWN family
# and the skill cross-family -- an asymmetry that lands entirely on the skill,
# in the direction of the deficit the pilot reported. Recall saturated at 1.00 there
# so it did not bite, but corpus-pilot-results.md §4 says plainly it "must be
# controlled before a larger judged comparison".
#
# Control: judge with one model per family and average. Every condition then receives
# exactly one same-family and one cross-family judgment, so self-preference cancels at
# the condition level instead of falling on one lane. The size of the effect is also
# reported rather than merely avoided -- see `judge_self_preference`.

CLAUDE_FAMILY = "claude"
NON_CLAUDE_FAMILY = "non-claude"
# Counterpart used when --judge-mode balanced is requested without an explicit --judge-2.
DEFAULT_COUNTERPART_JUDGE = {CLAUDE_FAMILY: "gpt-5.5", NON_CLAUDE_FAMILY: "claude-sonnet-4-6"}
_BALANCED_MEAN_FIELDS = ("recall", "specificity", "composite",
                         "confirmed_detect", "committed_anti")
_BALANCED_SUM_FIELDS = ("unsupported_spans", "parse_failures")


def judge_family(model: str) -> str:
    """PURE. Family of a judge id, mirroring the CLI's own routing rule: a judge whose
    id starts with `claude` runs through the local Claude CLI, anything else through
    codex."""
    return CLAUDE_FAMILY if str(model).lower().startswith("claude") else NON_CLAUDE_FAMILY


def condition_family(condition: str) -> str:
    """PURE. Family that GENERATED a condition's outputs. `generate_missing_critic`
    routes the skill lane to a local Claude agent and every `baseline-*` lane to local
    Codex, so the prefix is the discriminator."""
    return NON_CLAUDE_FAMILY if str(condition).startswith("baseline-") else CLAUDE_FAMILY


def judges_span_families(judges) -> bool:
    """PURE. True when the judge panel covers both families, which is the precondition
    for balanced scoring to actually cancel anything."""
    return len({judge_family(j) for j in judges}) > 1


def balance_scores(per_judge_scores: dict[str, dict[tuple, dict]]) -> dict[tuple, dict]:
    """PURE. Mean each judged axis across judges for every (fixture, condition, run).

    Deterministic fields (API coverage, item counts) are judge-invariant and carried
    through unchanged; judge-behaviour diagnostics (unsupported spans, parse failures)
    are summed because they count judge events, not response properties. Per-judge axes
    are retained under `per_judge` so nothing is hidden behind the mean.
    """
    judges = list(per_judge_scores)
    if not judges:
        return {}
    keys = set(per_judge_scores[judges[0]])
    for judge in judges[1:]:
        keys &= set(per_judge_scores[judge])
    out: dict[tuple, dict] = {}
    for key in sorted(keys, key=str):
        rows = [per_judge_scores[judge][key] for judge in judges]
        merged = dict(rows[0])
        for field in _BALANCED_MEAN_FIELDS:
            merged[field] = _mean([row.get(field) for row in rows])
        for field in _BALANCED_SUM_FIELDS:
            merged[field] = sum(row.get(field, 0) for row in rows)
        merged["per_judge"] = {
            judge: {ax: per_judge_scores[judge][key].get(ax)
                    for ax in ("recall", "specificity", "composite")}
            for judge in judges
        }
        out[key] = merged
    return out


def mean_severity_recall(per_judge: list[dict]) -> dict[str, Any]:
    """PURE. Average per-severity recall across judges. `n` counts checks, not judges,
    so it is judge-invariant and taken rather than summed."""
    out: dict[str, Any] = {}
    for cond in sorted({c for table in per_judge for c in table}):
        severities = sorted({s for table in per_judge for s in table.get(cond, {})})
        out[cond] = {}
        for sev in severities:
            rows = [table[cond][sev] for table in per_judge if sev in table.get(cond, {})]
            out[cond][sev] = {"recall": _mean([row.get("recall") for row in rows]),
                              "n": max((row.get("n", 0) for row in rows), default=0)}
    return out


def resolve_judge_panel(judge: str, judge_2: str | None, judge_mode: str) -> list[str]:
    """PURE. Build the judge panel from the CLI flags. Balanced mode is meaningless with a
    single-family panel, so when it is requested without an explicit `--judge-2` the
    default counterpart from the other family is appended rather than silently degrading
    to primary-judge scoring."""
    panel = [judge] + ([judge_2] if judge_2 and judge_2 != judge else [])
    if judge_mode == "balanced" and not judges_span_families(panel):
        counterpart = DEFAULT_COUNTERPART_JUDGE[judge_family(judge)]
        if counterpart not in panel:
            panel.append(counterpart)
    return panel


def judge_self_preference(per_judge_scores: dict[str, dict[tuple, dict]],
                          conditions) -> dict[str, Any]:
    """PURE. Measure the confound instead of only cancelling it: per condition, the mean
    composite awarded by judges of the generating family minus the mean awarded by judges
    of the other family. Positive means the same-family judge scored it higher."""
    by_condition: dict[str, Any] = {}
    deltas: list[float] = []
    for cond in conditions:
        family = condition_family(cond)
        same: list[float] = []
        cross: list[float] = []
        for judge, scores in per_judge_scores.items():
            values = [row["composite"] for (f, c, r), row in scores.items()
                      if c == cond and row.get("composite") is not None]
            if not values:
                continue
            (same if judge_family(judge) == family else cross).append(_mean(values))
        same_mean, cross_mean = _mean(same), _mean(cross)
        delta = None if (same_mean is None or cross_mean is None) else round(same_mean - cross_mean, 4)
        if delta is not None:
            deltas.append(delta)
        by_condition[cond] = {
            "generated_by": family,
            "same_family_composite": None if same_mean is None else round(same_mean, 4),
            "cross_family_composite": None if cross_mean is None else round(cross_mean, 4),
            "self_preference_delta": delta,
        }
    mean_delta = _mean(deltas)
    return {
        "by_condition": by_condition,
        "mean_self_preference_delta": None if mean_delta is None else round(mean_delta, 4),
        "note": "Positive delta = the generating family's own judge scored that condition "
                "higher than the other family's judge. Diagnostic, not a correction: "
                "balanced mode already averages the two.",
    }


# --------------------------------------------------------------------------- #
# I/O — runs only at execution time (not exercised in unit tests)
# --------------------------------------------------------------------------- #

_CHECK_SCHEMA = {
    "type": "object",
    "properties": {"present": {"type": "boolean"}, "span": {"type": "string"}},
    "required": ["present", "span"], "additionalProperties": False,
}


def check_item_via_cli(model, prompt, *, env=None, timeout_sec=600):  # pragma: no cover
    """Atomic answer-key check via a local Claude judge."""
    proc = subprocess.run(
        ["claude", "-p", "--model", model, "--tools", "",
         "--permission-mode", "bypassPermissions"],
        input=prompt, text=True, capture_output=True, timeout=timeout_sec,
        check=False, env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude check failed ({proc.returncode}): {proc.stderr.strip()[:500]}")
    return proc.stdout.strip()


def check_item_via_codex(model, prompt, *, timeout_sec=600):  # pragma: no cover
    """Atomic answer-key check via a non-Claude (OpenAI) judge through local `codex`,
    run non-agentically: read-only sandbox, ephemeral, rules ignored, output constrained
    to {present, span}. ChatGPT auth — no ANTHROPIC_API_KEY. Medium reasoning effort
    (xhigh is pathologically slow on long prompts; see pairwise_judge.judge_pair_via_codex)."""
    with tempfile.TemporaryDirectory(prefix="wp-codex-check-") as d:
        schema_path = os.path.join(d, "schema.json")
        out_path = os.path.join(d, "last.txt")
        with open(schema_path, "w", encoding="utf-8") as fh:
            json.dump(_CHECK_SCHEMA, fh)
        argv = [
            "codex", "exec", "--model", model,
            "-c", "model_reasoning_effort=medium",
            "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
            "--ignore-rules", "--color", "never",
            "--output-schema", schema_path, "--output-last-message", out_path, "-",
        ]
        proc = None
        for _attempt in range(2):
            try:
                proc = subprocess.run(argv, input=prompt, text=True, capture_output=True,
                                      timeout=timeout_sec, check=False)
                break
            except subprocess.TimeoutExpired:
                if _attempt == 0:
                    continue
                return ""  # degrade to a parse failure rather than crash the batch
        if proc.returncode != 0:
            raise RuntimeError(f"codex check failed ({proc.returncode}): {proc.stderr.strip()[:500]}")
        try:
            with open(out_path, encoding="utf-8") as fh:
                text = fh.read().strip()
        except FileNotFoundError:
            text = ""
    return text or proc.stdout.strip()


def grounding_for_items(sidecar: dict[str, Any], must_detect: list[str]) -> dict[str, dict]:
    """PURE. Map each must_detect DESCRIPTION to its grounding metadata from a
    `.provenance.yaml` sidecar's `grounding:` list (cwe/sniff, file, line, severity).

    The description string stays the judged, span-verified recall unit (recall is
    computed exactly as before); grounding is carried ALONGSIDE for the per-severity
    and file:line reports. Descriptions with no grounding entry are simply absent.
    This is the additive §5 extension: no dict items inside domain_signals (which the
    frozen eval-suite validator and llm_judge both require to be plain string lists) —
    the structured fields live in the un-policed sidecar instead."""
    by_desc: dict[str, dict] = {}
    for entry in (sidecar or {}).get("grounding", []) or []:
        if not isinstance(entry, dict):
            continue
        desc = entry.get("description")
        if isinstance(desc, str) and desc in must_detect:
            by_desc[desc] = {k: v for k, v in entry.items() if k != "description"}
    return by_desc


def load_answer_key(fixture_id, suite_dir: Path = SUITE_DIR) -> dict[str, Any]:  # pragma: no cover
    import yaml
    rub = yaml.safe_load((suite_dir / "rubrics" / f"{fixture_id}.rubric.yaml").read_text("utf-8"))
    sig = (rub or {}).get("domain_signals", {}) or {}
    must_detect = list(sig.get("must_detect", []) or [])
    sidecar_path = suite_dir / "fixtures" / f"{fixture_id}.provenance.yaml"
    sidecar = yaml.safe_load(sidecar_path.read_text("utf-8")) if sidecar_path.exists() else {}
    return {
        "must_detect": must_detect,
        "expected_apis": list(sig.get("expected_wordpress_apis", []) or []),
        "anti_patterns": list(sig.get("must_not_penalize_or_do", []) or []),
        "grounding": grounding_for_items(sidecar or {}, must_detect),
    }


def load_tier(fixture_id, suite_dir: Path = SUITE_DIR) -> str:  # pragma: no cover
    """Tier/tranche label. For the critic corpus this is the sidecar `tranche`
    (T/J/C); for the candidate eval it stays `difficulty_tier` or the suffix map."""
    import yaml
    sidecar_path = suite_dir / "fixtures" / f"{fixture_id}.provenance.yaml"
    if sidecar_path.exists():
        sidecar = yaml.safe_load(sidecar_path.read_text("utf-8")) or {}
        if sidecar.get("tranche"):
            return str(sidecar["tranche"])
    meta_path = suite_dir / "fixtures" / f"{fixture_id}.metadata.yaml"
    if meta_path.exists():
        meta = yaml.safe_load(meta_path.read_text("utf-8")) or {}
        if meta.get("difficulty_tier"):
            return str(meta["difficulty_tier"])
    for suffix, tier in TIER_BY_SUFFIX.items():
        if fixture_id.endswith(suffix):
            return tier
    return "UNKNOWN"


def fixture_text(fixture_id, suite_dir: Path = SUITE_DIR) -> str:  # pragma: no cover
    return (suite_dir / "fixtures" / f"{fixture_id}.md").read_text("utf-8")


def _hash(*parts) -> str:  # pragma: no cover
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def severity_recall(detect_confirms: dict[tuple, dict], answer_keys, conditions,
                    tranche_by_fixture=None, only_tranche=None) -> dict[str, Any]:
    """PURE. Per-condition detection recall bucketed by grounding severity
    (MINOR/MAJOR/CRITICAL/UNGROUNDED). `detect_confirms[(f,c,r)] = {description: bool}`.
    Optionally restrict to fixtures whose tranche == `only_tranche` (e.g. 'J')."""
    out: dict[str, Any] = {}
    for cond in conditions:
        buckets: dict[str, list[int]] = {}
        for (f, c, r), items in detect_confirms.items():
            if c != cond:
                continue
            if only_tranche and (tranche_by_fixture or {}).get(f) != only_tranche:
                continue
            grounding = answer_keys[f].get("grounding", {})
            for desc, confirmed in items.items():
                sev = str((grounding.get(desc) or {}).get("severity", "UNGROUNDED")).upper()
                buckets.setdefault(sev, []).append(1 if confirmed else 0)
        out[cond] = {sev: {"recall": (sum(v) / len(v)) if v else None, "n": len(v)}
                     for sev, v in sorted(buckets.items())}
    return out


def false_positive_rate(scores: dict[tuple, dict], conditions, tranche_by_fixture,
                        clean_tranche="C") -> dict[str, Any]:
    """PURE. False-positive rate on the clean tranche = committed anti-patterns /
    total anti-pattern checks, per condition. A finding raised on a clean fixture is a
    false positive; this is `1 - specificity` restricted to tranche C, surfaced plainly."""
    out: dict[str, Any] = {}
    for cond in conditions:
        committed = total = 0
        for (f, c, r), row in scores.items():
            if c != cond or tranche_by_fixture.get(f) != clean_tranche:
                continue
            committed += row.get("committed_anti", 0)
            total += row.get("n_anti", 0)
        out[cond] = {"false_positive_rate": (committed / total) if total else None,
                     "committed": committed, "n_checks": total}
    return out


def orchestrate(*, fixtures, conditions, runs, answer_keys, fixture_texts, tiers,
                gens, judges, check_fn, progress_fn=None,
                strong=KNOWN_STRONG, weak=KNOWN_WEAK,
                judge_mode="primary") -> dict[str, Any]:  # pragma: no cover
    """Run atomic blind checks for every (fixture, condition, run, item) for every judge.
    `gens[(fixture,condition,run)]->text`. `check_fn(judge,prompt)->raw`.
    `strong`/`weak` name the discrimination poles (candidate eval: zivtech vs zero-shot;
    critic corpus: skill vs zero-shot).

    `judge_mode='primary'` scores from judges[0] alone and uses any second judge only for
    the agreement cross-check -- the historical behaviour, kept so archived candidate-eval
    runs stay reproducible. `judge_mode='balanced'` averages every judge's scores, which
    controls the generation/judge family asymmetry described above; it requires a panel
    spanning both families to mean anything."""
    progress_fn = progress_fn or (lambda *a: None)
    primary = judges[0]
    balanced = judge_mode == "balanced" and len(judges) > 1
    per_item: dict[str, dict[tuple, dict]] = {j: {} for j in judges}
    per_judge_scores: dict[str, dict[tuple, dict]] = {j: {} for j in judges}
    per_judge_detect: dict[str, dict[tuple, dict]] = {j: {} for j in judges}

    units = [(f, c, r) for f in fixtures for c in conditions for r in range(1, runs + 1)
             if (f, c, r) in gens]
    total = sum((len(answer_keys[f]["must_detect"]) + len(answer_keys[f]["anti_patterns"]))
                * len(judges) for (f, c, r) in units)
    i = 0
    for (f, c, r) in units:
        ak, resp, ftext = answer_keys[f], gens[(f, c, r)], fixture_texts[f]
        per_judge_confirm = {j: ({}, {}) for j in judges}  # j -> (detect_results, anti_results)
        for kind, items in (("detect", ak["must_detect"]), ("anti", ak["anti_patterns"])):
            for item in items:
                prompt = build_check_prompt(ftext, resp, item, kind)
                for j in judges:
                    i += 1
                    progress_fn("check", i, total, f"{f}/{c}/r{r} [{kind}] {item[:40]}")
                    parsed = parse_check(check_fn(j, prompt))
                    res = confirm_item(parsed, resp)
                    (per_judge_confirm[j][0] if kind == "detect" else per_judge_confirm[j][1])[item] = res
                    per_item[j][(f, c, r, kind, item)] = res
        for j in judges:
            per_judge_scores[j][(f, c, r)] = score_output(ak, resp, *per_judge_confirm[j])
            per_judge_detect[j][(f, c, r)] = {item: res.get("confirmed", False)
                                              for item, res in per_judge_confirm[j][0].items()}

    scores = balance_scores(per_judge_scores) if balanced else per_judge_scores[primary]
    tranche_by_fixture = {f: tiers.get(f) for f in fixtures}
    if balanced:
        severity_tranche_J = mean_severity_recall([
            severity_recall(per_judge_detect[j], answer_keys, conditions,
                            tranche_by_fixture, only_tranche="J")
            for j in judges
        ])
    else:
        severity_tranche_J = severity_recall(
            per_judge_detect[primary], answer_keys, conditions,
            tranche_by_fixture, only_tranche="J")
    out = {
        "instrument": "answer-key-diagnostic",
        "judges": judges, "primary_judge": primary, "strong": strong, "weak": weak,
        "judge_mode": "balanced" if balanced else "primary",
        "judge_families": {j: judge_family(j) for j in judges},
        "judge_family_balanced": judges_span_families(judges),
        "conditions": list(conditions), "fixtures": list(fixtures), "runs": runs,
        "discrimination": discrimination_check(scores, fixtures, strong=strong, weak=weak),
        "aggregate": aggregate(scores, conditions, tiers),
        "deltas_vs_strong": {
            other: cluster_bootstrap_delta(scores, fixtures, strong, other)
            for other in conditions if other != strong
        },
        "severity_recall_tranche_J": severity_tranche_J,
        "false_positive_rate_tranche_C": false_positive_rate(
            scores, conditions, tranche_by_fixture, clean_tranche="C"),
        "per_fixture_grounding": {f: answer_keys[f].get("grounding", {}) for f in fixtures},
        "per_output": {f"{f}|{c}|r{r}": v for (f, c, r), v in scores.items()},
        "firewall": "Diagnostic only. Localizes where V1 helps; NOT a superiority or "
                    "equivalence claim (wordpress-skills/CLAUDE.md:34).",
    }
    # Back-compat alias for the candidate-eval consumers/run history.
    if strong == KNOWN_STRONG:
        out["deltas_vs_zivtech"] = out["deltas_vs_strong"]
    if len(judges) > 1:
        out["judge_agreement"] = judge_agreement(per_item[primary], per_item[judges[1]])
    if judges_span_families(judges):
        out["judge_self_preference"] = judge_self_preference(per_judge_scores, conditions)
    return out


def generate_missing(fixtures, conditions, runs, gen_dir, model, upstream_project,
                     timeout_sec, progress_fn, baseline_model="gpt-5.5",
                     baseline_effort="medium"):  # pragma: no cover
    """Generate any missing (fixture, condition, run) outputs into gen_dir using the SAME
    isolated generation + condition-prompt assembly as the frozen pairwise harness
    (imported, not modified). New fixtures are registered in run_pairwise_pilot's agent map
    at runtime so the zivtech condition resolves; raw_upstream is skipped for fixtures with
    no upstream-skill mapping. Baseline conditions use isolated local Codex
    (`gpt-5.5` by default); skill/upstream conditions still use the isolated
    Claude generation path because they inject Claude agent/skill prompts."""
    import tempfile
    import run_pairwise_pilot as rpp
    from isolation import run_isolated_generation
    import invoke
    rpp.ZIVTECH_AGENTS.update(NEW_FIXTURE_AGENTS)
    units = [(f, c, r) for f in fixtures for c in conditions for r in range(1, runs + 1)]
    for i, (f, c, r) in enumerate(units, 1):
        dest = gen_dir / f"r{r}__{f}__{c}.txt"
        if dest.exists():
            progress_fn("gen-cached", i, len(units), dest.name)
            continue
        ftext = fixture_text(f)
        try:
            prompt, agent = rpp.build_condition_prompt(c, f, ftext, upstream_project)
        except (KeyError, FileNotFoundError):
            progress_fn("gen-skip", i, len(units), f"{f}/{c} (no mapping/skill; skipped)")
            continue
        progress_fn("gen", i, len(units), f"{f}/{c}/r{r}")
        if c.startswith("baseline-"):
            out, err, rc, _dt = invoke._run_codex(
                prompt,
                timeout_sec=timeout_sec,
                max_retries=2,
                model=baseline_model,
                effort=baseline_effort,
            )
            if rc != 0 and not out.strip():
                out = err
        else:
            with tempfile.TemporaryDirectory(prefix="wp-akgen-") as base:
                out, _err, _rc, _posture = run_isolated_generation(
                    prompt, model=model, base=Path(base), agent_prompt_text=agent, timeout_sec=timeout_sec)
        dest.write_text(out, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Suite-aware critic-corpus path (recommendation 09)
# --------------------------------------------------------------------------- #

CRITIC_CONDITIONS = ("skill", "baseline-zero-shot", "baseline-few-shot")
CRITIC_STRONG = "skill"
CRITIC_WEAK = "baseline-zero-shot"


def discover_corpus_fixtures(suite_dir: Path) -> list[str]:  # pragma: no cover
    """Corpus fixtures = every `<id>.md` that has a `<id>.provenance.yaml` sidecar whose
    `status` is not `draft`. This cleanly excludes the legacy smoke fixture (no sidecar)
    and any draft CVE stub the human-verification gate has not promoted."""
    import yaml
    out = []
    for md in sorted((suite_dir / "fixtures").glob("*.md")):
        sidecar = suite_dir / "fixtures" / f"{md.stem}.provenance.yaml"
        if not sidecar.exists():
            continue
        data = yaml.safe_load(sidecar.read_text("utf-8")) or {}
        if str(data.get("status", "active")).lower() == "draft":
            continue
        out.append(md.stem)
    return out


def generate_missing_critic(suite, fixtures, conditions, runs, gen_dir, run_id,
                            timeout_sec, progress_fn):  # pragma: no cover
    """Generate missing critic outputs via invoke.invoke (single-stage critic mode) and
    write them to the shared gen_dir filename convention `r{run}__{fixture}__{condition}.txt`.
    Skill lane -> local Claude agent; baseline lanes -> local Codex (resolved in invoke.py
    from eval.yaml's invocation block). Runs share the invoke output path, so each run is
    generated then copied to its indexed gen file."""
    import invoke
    units = [(f, c, r) for f in fixtures for c in conditions for r in range(1, runs + 1)]
    for i, (f, c, r) in enumerate(units, 1):
        dest = gen_dir / f"r{r}__{f}__{c}.txt"
        if dest.exists():
            progress_fn("gen-cached", i, len(units), dest.name)
            continue
        progress_fn("gen", i, len(units), f"{f}/{c}/r{r}")
        result = invoke.invoke(run_id=f"{run_id}-r{r}", suite=suite, fixture_id=f,
                               condition=c, mode="critic", timeout_sec=timeout_sec)
        dest.write_text(result.final_output or "", encoding="utf-8")


def write_critic_scorecard(path: Path, summary: dict[str, Any]) -> None:  # pragma: no cover
    agg = summary["aggregate"]["by_condition"]
    fpr = summary["false_positive_rate_tranche_C"]
    lines = [
        "# WordPress Critic Answer-Key Scorecard",
        "",
        f"Suite: `{summary['suite']}`  ·  runs: {summary['runs']}  ·  "
        f"primary judge: `{summary['primary_judge']}`",
        f"Strong pole: `{summary['strong']}`  ·  weak pole: `{summary['weak']}`",
        f"Judge mode: `{summary.get('judge_mode', 'primary')}`  ·  panel: "
        + ", ".join(f"`{j}` ({fam})" for j, fam in summary.get("judge_families", {}).items())
        + ("" if summary.get("judge_family_balanced") else
           "  ·  **single-family panel: the generation/judge family confound is NOT controlled**"),
        "",
        "Diagnostic only — localizes where the skill helps by tranche; NOT a superiority "
        "or equivalence claim (`CLAUDE.md` evaluation boundary).",
        "",]
    pref = summary.get("judge_self_preference")
    if pref:
        lines += [
            "## Judge self-preference (family confound, prereg §4)",
            "",
            "Composite awarded by the generating family's own judge minus the other "
            "family's. Positive = self-preference. Balanced mode averages both, so this "
            "reports the size of the effect it cancels.",
            "",
            f"Mean across conditions: **{pref.get('mean_self_preference_delta')}**",
            "",
            "| Condition | generated by | same-family | cross-family | delta |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
        for c, row in pref.get("by_condition", {}).items():
            lines.append(f"| `{c}` | {row.get('generated_by')} | "
                         f"{row.get('same_family_composite')} | "
                         f"{row.get('cross_family_composite')} | "
                         f"{row.get('self_preference_delta')} |")
    lines += [
        "",
        "## Per-condition (composite | recall | api | specificity)",
        "",
        "| Condition | composite | recall | api | specificity | n |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for c in summary["conditions"]:
        a = agg.get(c, {})
        lines.append(f"| `{c}` | {a.get('composite')} | {a.get('recall')} | "
                     f"{a.get('api_coverage')} | {a.get('specificity')} | {a.get('n')} |")
    lines += ["", "## Tranche-C false-positive rate (findings raised on clean code)", "",
              "| Condition | FP rate | committed | checks |", "| --- | ---: | ---: | ---: |"]
    for c in summary["conditions"]:
        b = fpr.get(c, {})
        lines.append(f"| `{c}` | {b.get('false_positive_rate')} | {b.get('committed')} | "
                     f"{b.get('n_checks')} |")
    lines += ["", "## Discrimination self-check (strong − weak composite)", "",
              f"- mean delta: `{summary['discrimination']['mean_delta']}` "
              f"(threshold {summary['discrimination']['threshold']}; "
              f"discriminates: {summary['discrimination']['discriminates']})",
              "- per-fixture: " + json.dumps(summary["discrimination"]["per_fixture_delta"]),
              ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_critic_corpus(args, progress) -> None:  # pragma: no cover
    """Suite-aware three-condition answer-key run for a critic corpus suite."""
    suite = args.suite
    suite_dir = SUITES_ROOT_FOR(suite)
    out_dir = (ROOT / "evals" / "results" / args.out) if args.out else (
        ROOT / "evals" / "results" / suite / args.run_id)
    conditions = args.conditions or list(CRITIC_CONDITIONS)
    runs = 1 if args.fast else args.runs
    fixtures = args.fixtures if args.fixtures else discover_corpus_fixtures(suite_dir)
    if not fixtures:
        raise SystemExit(f"no active corpus fixtures (with .provenance.yaml) under {suite_dir}")

    gen_dir = out_dir / "checkpoint" / "gen"
    gen_dir.mkdir(parents=True, exist_ok=True)
    if args.generate:
        generate_missing_critic(suite, fixtures, conditions, runs, gen_dir, args.run_id,
                                args.timeout_sec, progress)

    answer_keys = {f: load_answer_key(f, suite_dir) for f in fixtures}
    fixture_texts = {f: fixture_text(f, suite_dir) for f in fixtures}
    tiers = {f: load_tier(f, suite_dir) for f in fixtures}
    gens: dict[tuple, str] = {}
    for f in fixtures:
        for c in conditions:
            for r in range(1, runs + 1):
                gp = gen_dir / f"r{r}__{f}__{c}.txt"
                if gp.exists():
                    gens[(f, c, r)] = gp.read_text("utf-8")
    if not gens:
        raise SystemExit(f"no generations under {gen_dir}; pass --generate to produce them")

    ckpt = out_dir / "checkpoint" / "check"
    ckpt.mkdir(parents=True, exist_ok=True)
    # Critic corpus defaults to balanced: its conditions are generated by two different
    # families, so a single-family judge would reintroduce the prereg §4 confound.
    judge_mode = args.judge_mode or "balanced"
    judges = resolve_judge_panel(args.judge, args.judge_2, judge_mode)

    def check_fn(judge_model, prompt):
        cache = ckpt / f"{_hash(judge_model, prompt)}.txt"
        if cache.exists():
            return cache.read_text("utf-8")
        call = check_item_via_cli if judge_model.startswith("claude") else check_item_via_codex
        raw = call(judge_model, prompt, timeout_sec=args.timeout_sec)
        cache.write_text(raw, "utf-8")
        return raw

    summary = orchestrate(
        fixtures=fixtures, conditions=conditions, runs=runs, answer_keys=answer_keys,
        fixture_texts=fixture_texts, tiers=tiers, gens=gens, judges=judges,
        check_fn=check_fn, progress_fn=progress, strong=CRITIC_STRONG, weak=CRITIC_WEAK,
        judge_mode=judge_mode)
    summary["suite"] = suite
    summary["n_boot"] = args.n_boot
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "answerkey-summary.json").write_text(json.dumps(summary, indent=2), "utf-8")
    write_critic_scorecard(out_dir / "scorecard.md", summary)

    print("\n=== PER-CONDITION (composite | recall | api | specificity) ===")
    for c in conditions:
        a = summary["aggregate"]["by_condition"][c]
        print(f"  {c:22s} {a['composite']} | {a['recall']} | {a['api_coverage']} | {a['specificity']}  (n={a['n']})")
    print("\n=== tranche-C false-positive rate ===")
    for c, b in summary["false_positive_rate_tranche_C"].items():
        print(f"  {c:22s} FPR={b['false_positive_rate']}  ({b['committed']}/{b['n_checks']})")
    print(f"\nwrote {out_dir / 'answerkey-summary.json'} and scorecard.md")


def SUITES_ROOT_FOR(suite: str) -> Path:  # pragma: no cover
    return ROOT / "evals" / "suites" / suite


def main():  # pragma: no cover
    p = argparse.ArgumentParser(description="Answer-key diagnostic re-scoring (reuses committed generations).")
    p.add_argument("--suite", default=None,
                   help="Score a critic-corpus suite (e.g. wordpress-security-critic) instead of the "
                        "candidate eval. Uses skill/baseline-zero-shot/baseline-few-shot with strong=skill.")
    p.add_argument("--out", default=None, help="Results subdirectory under evals/results/ (critic-corpus path).")
    p.add_argument("--run-id", required=True)
    p.add_argument("--gen-from", default="pairwise-cert-1",
                   help="Run-id whose checkpoint/gen/ holds the committed generations to re-score.")
    p.add_argument("--judge", default="gpt-5.5",
                   help="Primary judge model id. Non-'claude*' routes to codex (cross-family, default).")
    p.add_argument("--judge-2", default=None, help="Optional second judge for the agreement cross-check.")
    p.add_argument("--judge-mode", choices=("primary", "balanced"), default=None,
                   help="'balanced' averages one judge per model family so generation/judge "
                        "family self-preference cancels (default for the critic corpus); "
                        "'primary' scores from --judge alone (default for the candidate eval). "
                        "Balanced adds the counterpart judge automatically if --judge-2 is omitted.")
    p.add_argument("--fast", action="store_true", help="runs=1 directional read.")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--fixtures", nargs="*", default=None)
    p.add_argument("--conditions", nargs="*", default=None)
    p.add_argument("--timeout-sec", type=int, default=600)
    p.add_argument("--n-boot", type=int, default=2000)
    p.add_argument("--generate", action="store_true",
                   help="Generate missing outputs into this run's checkpoint/gen before scoring. "
                        "Baseline lanes use local Codex; skill/upstream lanes use isolated Claude.")
    p.add_argument("--generation-model", default="claude-sonnet-4-6")
    p.add_argument("--baseline-model", default="gpt-5.5")
    p.add_argument("--baseline-effort", default="medium")
    p.add_argument("--upstream-project", type=Path, default=DEFAULT_UPSTREAM_PROJECT)
    args = p.parse_args()

    def progress(phase, i, n, label):
        print(f"[{phase} {i}/{n}] {label}", flush=True)

    if args.suite:
        run_critic_corpus(args, progress)
        return

    runs = 1 if args.fast else args.runs
    fixtures = args.fixtures if args.fixtures else list(PILOT_FIXTURES)
    conditions = args.conditions if args.conditions else list(CONDITIONS)
    out_dir = RESULTS_DIR / args.run_id

    if args.generate:
        gen_dir = out_dir / "checkpoint" / "gen"
        gen_dir.mkdir(parents=True, exist_ok=True)
        generate_missing(fixtures, conditions, runs, gen_dir, args.generation_model,
                         args.upstream_project, args.timeout_sec, progress,
                         args.baseline_model, args.baseline_effort)
    else:
        gen_dir = RESULTS_DIR / args.gen_from / "checkpoint" / "gen"
        if not gen_dir.is_dir():
            raise SystemExit(f"no committed generations at {gen_dir} (need --gen-from or --generate)")

    answer_keys = {f: load_answer_key(f) for f in fixtures}
    fixture_texts = {f: fixture_text(f) for f in fixtures}
    tiers = {f: load_tier(f) for f in fixtures}
    gens: dict[tuple, str] = {}
    for f in fixtures:
        for c in conditions:
            for r in range(1, runs + 1):
                gp = gen_dir / f"r{r}__{f}__{c}.txt"
                if gp.exists():
                    gens[(f, c, r)] = gp.read_text("utf-8")
    if not gens:
        raise SystemExit(f"no generations matched fixtures/conditions/runs under {gen_dir}")

    ckpt = out_dir / "checkpoint" / "check"
    ckpt.mkdir(parents=True, exist_ok=True)

    # Candidate eval defaults to primary so archived runs stay reproducible; its lanes
    # were generated single-family historically. Opt in with --judge-mode balanced.
    judge_mode = args.judge_mode or "primary"
    judges = resolve_judge_panel(args.judge, args.judge_2, judge_mode)

    def check_fn(judge_model, prompt):
        cache = ckpt / f"{_hash(judge_model, prompt)}.txt"
        if cache.exists():
            return cache.read_text("utf-8")
        call = check_item_via_cli if judge_model.startswith("claude") else check_item_via_codex
        raw = call(judge_model, prompt, timeout_sec=args.timeout_sec)
        cache.write_text(raw, "utf-8")
        return raw

    summary = orchestrate(
        fixtures=fixtures, conditions=conditions, runs=runs, answer_keys=answer_keys,
        fixture_texts=fixture_texts, tiers=tiers, gens=gens, judges=judges,
        check_fn=check_fn, progress_fn=progress, judge_mode=judge_mode)
    summary["gen_from"] = args.gen_from
    summary["n_boot"] = args.n_boot
    if args.generate:
        summary["generation_models"] = {
            "baseline_provider": "codex",
            "baseline_model_policy": "newest-chatgpt-level-at-run-time",
            "baseline_model": args.baseline_model,
            "baseline_effort": args.baseline_effort,
            "candidate_provider": "claude",
            "candidate_model": args.generation_model,
        }

    (out_dir / "answerkey-summary.json").write_text(json.dumps(summary, indent=2), "utf-8")

    disc = summary["discrimination"]
    print("\n=== DISCRIMINATION SELF-CHECK (gate interpretation on this) ===")
    print(f"  {disc['strong']} - {disc['weak']} mean composite delta = {disc['mean_delta']} "
          f"(>= {disc['threshold']}? {disc['discriminates']})")
    print("  per-fixture:", disc["per_fixture_delta"])
    print("\n=== PER-CONDITION (composite | recall | api | specificity) ===")
    for c in conditions:
        a = summary["aggregate"]["by_condition"][c]
        print(f"  {c:24s} {a['composite']} | {a['recall']} | {a['api_coverage']} | {a['specificity']}  (n={a['n']})")
    print("\n=== zivtech - baseline (cluster-bootstrap CI) ===")
    for other, d in summary["deltas_vs_zivtech"].items():
        print(f"  vs {other:24s} {d['mean_delta']}  CI95 {d['ci95']}")
    if "judge_agreement" in summary:
        print(f"\n  judge agreement (raw): {summary['judge_agreement']['raw_agreement']} "
              f"over {summary['judge_agreement']['n_items']} items")
    print(f"\nwrote {out_dir / 'answerkey-summary.json'}")


if __name__ == "__main__":  # pragma: no cover
    main()
