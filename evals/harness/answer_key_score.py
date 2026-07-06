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


def load_answer_key(fixture_id) -> dict[str, Any]:  # pragma: no cover
    import yaml
    rub = yaml.safe_load((SUITE_DIR / "rubrics" / f"{fixture_id}.rubric.yaml").read_text("utf-8"))
    sig = (rub or {}).get("domain_signals", {}) or {}
    return {
        "must_detect": list(sig.get("must_detect", []) or []),
        "expected_apis": list(sig.get("expected_wordpress_apis", []) or []),
        "anti_patterns": list(sig.get("must_not_penalize_or_do", []) or []),
    }


def load_tier(fixture_id) -> str:  # pragma: no cover
    import yaml
    meta_path = SUITE_DIR / "fixtures" / f"{fixture_id}.metadata.yaml"
    if meta_path.exists():
        meta = yaml.safe_load(meta_path.read_text("utf-8")) or {}
        if meta.get("difficulty_tier"):
            return str(meta["difficulty_tier"])
    for suffix, tier in TIER_BY_SUFFIX.items():
        if fixture_id.endswith(suffix):
            return tier
    return "UNKNOWN"


def fixture_text(fixture_id) -> str:  # pragma: no cover
    return (SUITE_DIR / "fixtures" / f"{fixture_id}.md").read_text("utf-8")


def _hash(*parts) -> str:  # pragma: no cover
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def orchestrate(*, fixtures, conditions, runs, answer_keys, fixture_texts, tiers,
                gens, judges, check_fn, progress_fn=None) -> dict[str, Any]:  # pragma: no cover
    """Run atomic blind checks for every (fixture, condition, run, item) for the PRIMARY
    judge (judges[0]); if a second judge is given, also collect its confirmations for the
    agreement cross-check. `gens[(fixture,condition,run)]->text`. `check_fn(judge,prompt)->raw`."""
    progress_fn = progress_fn or (lambda *a: None)
    primary = judges[0]
    per_item: dict[str, dict[tuple, dict]] = {j: {} for j in judges}
    scores: dict[tuple, dict] = {}

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
        scores[(f, c, r)] = score_output(ak, resp, *per_judge_confirm[primary])

    out = {
        "instrument": "answer-key-diagnostic",
        "judges": judges, "primary_judge": primary,
        "conditions": list(conditions), "fixtures": list(fixtures), "runs": runs,
        "discrimination": discrimination_check(scores, fixtures),
        "aggregate": aggregate(scores, conditions, tiers),
        "deltas_vs_zivtech": {
            other: cluster_bootstrap_delta(scores, fixtures, KNOWN_STRONG, other)
            for other in conditions if other != KNOWN_STRONG
        },
        "per_output": {f"{f}|{c}|r{r}": v for (f, c, r), v in scores.items()},
        "firewall": "Diagnostic only. Localizes where V1 helps; NOT a superiority or "
                    "equivalence claim (wordpress-skills/CLAUDE.md:34).",
    }
    if len(judges) > 1:
        out["judge_agreement"] = judge_agreement(per_item[primary], per_item[judges[1]])
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


def main():  # pragma: no cover
    p = argparse.ArgumentParser(description="Answer-key diagnostic re-scoring (reuses committed generations).")
    p.add_argument("--run-id", required=True)
    p.add_argument("--gen-from", default="pairwise-cert-1",
                   help="Run-id whose checkpoint/gen/ holds the committed generations to re-score.")
    p.add_argument("--judge", default="gpt-5.5",
                   help="Primary judge model id. Non-'claude*' routes to codex (cross-family, default).")
    p.add_argument("--judge-2", default=None, help="Optional second judge for the agreement cross-check.")
    p.add_argument("--fast", action="store_true", help="runs=1 directional read.")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--fixtures", nargs="*", default=list(PILOT_FIXTURES))
    p.add_argument("--conditions", nargs="*", default=list(CONDITIONS))
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

    runs = 1 if args.fast else args.runs
    fixtures, conditions = args.fixtures, args.conditions
    out_dir = RESULTS_DIR / args.run_id

    def progress(phase, i, n, label):
        print(f"[{phase} {i}/{n}] {label}", flush=True)

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

    judges = [args.judge] + ([args.judge_2] if args.judge_2 and args.judge_2 != args.judge else [])

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
        check_fn=check_fn, progress_fn=progress)
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
