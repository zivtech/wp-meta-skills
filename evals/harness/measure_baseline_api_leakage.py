#!/usr/bin/env python3
"""Measure how much of the API-coverage answer key each baseline prompt already contains.

`answer_key_score.py` scores API coverage as a deterministic substring match of a
fixture's `domain_signals.expected_wordpress_apis` against a candidate's response. That
axis is meant to ask "did the reviewer name the right WordPress surface for this defect".

It cannot ask that of a condition whose *prompt* already lists those surfaces. A prompt
naming `esc_like`, `update_meta_cache`, or `viewScriptModule` hands its outputs that
vocabulary for free, so the axis partly measures prompt content rather than review skill.

This tool scores each baseline prompt AS IF it were a response, using the same
`api_coverage` the scorer uses. A high score is not misconduct -- naming remediation APIs
is good prompt engineering -- it is a construct-validity warning: on those fixtures the
API axis is not comparing what it claims to compare.

    python3 evals/harness/measure_baseline_api_leakage.py
    python3 evals/harness/measure_baseline_api_leakage.py --suite wordpress-security-critic --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

HARNESS_DIR = Path(__file__).resolve().parent
ROOT = HARNESS_DIR.parent.parent
sys.path.insert(0, str(HARNESS_DIR))

import answer_key_score as ak  # noqa: E402

CRITIC_SUITES = ("wordpress-critic", "wordpress-security-critic",
                 "wordpress-performance-critic", "wordpress-theme-critic")
# A prompt supplying most of a fixture's answer key makes that fixture's API axis
# uninformative; flag it rather than leaving it to the reader to spot in the table.
LEAKAGE_FLAG = 0.50


def leakage_for_fixture(expected_apis: list[str], prompt: str) -> dict[str, Any]:
    """PURE. Score one fixture's API answer key against a prompt, via the scorer's own
    matcher. `named` lists which expected APIs the prompt already contains."""
    coverage = ak.api_coverage(expected_apis, prompt)
    return {
        "coverage": coverage["coverage"],
        "n_expected": coverage["n_total"],
        "named": [api for api in expected_apis if ak.api_match(api, prompt)],
    }


def summarize(rows: list[dict[str, Any]], flag_at: float = LEAKAGE_FLAG) -> dict[str, Any]:
    """PURE. Mean leakage per condition plus the fixtures at or above the flag."""
    conditions = sorted({row["condition"] for row in rows})
    by_condition: dict[str, Any] = {}
    for cond in conditions:
        vals = [row["coverage"] for row in rows
                if row["condition"] == cond and row["coverage"] is not None]
        flagged = sorted({row["fixture"] for row in rows
                          if row["condition"] == cond and (row["coverage"] or 0) >= flag_at})
        by_condition[cond] = {
            "mean_coverage": (sum(vals) / len(vals)) if vals else None,
            "n_fixtures": len(vals),
            "n_flagged": len(flagged),
            "flagged_fixtures": flagged,
        }
    return {"flag_at": flag_at, "by_condition": by_condition}


def collect(suites=CRITIC_SUITES, root: Path = ROOT) -> list[dict[str, Any]]:  # pragma: no cover
    rows: list[dict[str, Any]] = []
    for suite in suites:
        base = root / "evals" / "suites" / suite
        prompts = {p.stem: p.read_text(encoding="utf-8")
                   for p in sorted((base / "baselines").glob("baseline-*.md"))}
        for rubric_path in sorted((base / "rubrics").glob("*.rubric.yaml")):
            fixture = rubric_path.name[: -len(".rubric.yaml")]
            provenance = base / "fixtures" / f"{fixture}.provenance.yaml"
            if not provenance.exists():
                continue  # labeled corpus fixtures only; legacy smoke fixtures have no tranche
            tranche = (yaml.safe_load(provenance.read_text(encoding="utf-8")) or {}).get("tranche")
            signals = (yaml.safe_load(rubric_path.read_text(encoding="utf-8")) or {}).get(
                "domain_signals") or {}
            expected = signals.get("expected_wordpress_apis") or []
            if not expected:
                continue
            for condition, prompt in prompts.items():
                rows.append({"suite": suite, "fixture": fixture, "tranche": tranche,
                             "condition": condition} | leakage_for_fixture(expected, prompt))
    return rows


def main() -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", action="append", choices=list(CRITIC_SUITES), default=None)
    parser.add_argument("--json", action="store_true", help="Emit the raw rows and summary.")
    parser.add_argument("--flag-at", type=float, default=LEAKAGE_FLAG)
    args = parser.parse_args()

    rows = collect(tuple(args.suite) if args.suite else CRITIC_SUITES)
    if not rows:
        print("no labeled corpus fixtures with expected_wordpress_apis found", file=sys.stderr)
        return 1
    summary = summarize(rows, flag_at=args.flag_at)
    if args.json:
        print(json.dumps({"rows": rows, "summary": summary}, indent=2))
        return 0

    conditions = sorted({row["condition"] for row in rows})
    header = f"{'fixture':<44}{'tr':<4}" + "".join(f"{c.replace('baseline-', ''):>11}" for c in conditions)
    print(header)
    print("-" * len(header))
    for fixture in sorted({row["fixture"] for row in rows}):
        group = {row["condition"]: row for row in rows if row["fixture"] == fixture}
        any_row = next(iter(group.values()))
        line = f"{fixture:<44}{str(any_row['tranche']):<4}"
        line += "".join(f"{group[c]['coverage']:>11.2f}" if c in group else f"{'-':>11}"
                        for c in conditions)
        print(line)
    print("-" * len(header))
    for cond, agg in summary["by_condition"].items():
        mean = agg["mean_coverage"]
        print(f"{cond:<48}mean {mean:.2f} over {agg['n_fixtures']} fixtures  "
              f"({agg['n_flagged']} at or above {summary['flag_at']:.2f})")
    print("\nA prompt scoring high here supplies its own outputs the API vocabulary the "
          "scorer counts.\nOn those fixtures the API-coverage axis does not compare review "
          "skill between conditions.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
