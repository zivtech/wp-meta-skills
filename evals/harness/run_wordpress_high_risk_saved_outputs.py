#!/usr/bin/env python3
"""Generate and validate saved outputs for high-risk WordPress eval suites.

This runner is intentionally narrower than the older candidate pilot. It does
not judge output quality or claim benchmark superiority. It archives raw skill
and baseline outputs, runs the deterministic WordPress output-contract oracle on
each saved output, and writes a small manifest/scorecard so suite status docs can
point to real evidence instead of fixture scaffolding.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit(f"Unable to import PyYAML: {exc}") from exc

import invoke as invoke_harness
import validate_wordpress_skill_output as contract_oracle


ROOT = Path(__file__).resolve().parents[2]
SUITES_ROOT = ROOT / "evals" / "suites"
RESULTS_ROOT = ROOT / "evals" / "results"
DEFAULT_CONDITIONS = ("skill", "baseline-zero-shot", "baseline-few-shot")


@dataclass(frozen=True)
class SavedOutputEntry:
    suite: str
    fixture_id: str
    condition: str
    output_path: str
    metadata_path: str
    contract_path: str
    security_gate_path: str | None
    generation_ok: bool
    contract_pass: bool
    contract_score: float | None
    duration_sec: float | None
    error: str | None = None


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_csv(value: str | None, default: tuple[str, ...] = ()) -> list[str]:
    if value is None:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def load_eval_config(suite: str) -> dict[str, Any]:
    path = SUITES_ROOT / suite / "eval.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Missing eval.yaml for suite: {suite}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def fixture_ids_for_suite(suite: str, requested: list[str] | None = None) -> list[str]:
    if requested:
        return requested

    config = load_eval_config(suite)
    fixtures_cfg = config.get("fixtures") or {}
    raw_dir = fixtures_cfg.get("directory") or "./fixtures"
    if raw_dir.startswith("./"):
        raw_dir = raw_dir[2:]
    pattern = fixtures_cfg.get("pattern") or "*.md"
    fixture_dir = SUITES_ROOT / suite / raw_dir
    return sorted(path.stem for path in fixture_dir.glob(pattern) if path.is_file())


def skill_name_for_suite(suite: str) -> str:
    config = load_eval_config(suite)
    skill = config.get("skill") or {}
    return skill.get("name") or suite


def saved_output_path(run_id: str, suite: str, condition: str, fixture_id: str) -> Path:
    return RESULTS_ROOT / run_id / "raw" / suite / condition / f"{fixture_id}.md"


def saved_metadata_path(run_id: str, suite: str, condition: str, fixture_id: str) -> Path:
    return RESULTS_ROOT / run_id / "raw" / suite / condition / f"{fixture_id}.metadata.json"


def contract_result_path(run_id: str, suite: str, condition: str, fixture_id: str) -> Path:
    return RESULTS_ROOT / run_id / "contracts" / suite / condition / f"{fixture_id}.contract.json"


def fixture_dir_for_suite(suite: str) -> Path:
    config = load_eval_config(suite)
    fixtures_cfg = config.get("fixtures") or {}
    raw_dir = fixtures_cfg.get("directory") or "./fixtures"
    if raw_dir.startswith("./"):
        raw_dir = raw_dir[2:]
    return SUITES_ROOT / suite / raw_dir


def security_gate_sidecar_path(suite: str, fixture_id: str) -> Path | None:
    path = fixture_dir_for_suite(suite) / f"{fixture_id}.security-gate.json"
    return path if path.exists() else None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_contract(
    skill_name: str,
    output_path: Path,
    contract_path: Path,
    security_gate_path: Path | None = None,
) -> dict[str, Any]:
    if not output_path.exists() or not output_path.read_text(encoding="utf-8").strip():
        result = {
            "skill": skill_name,
            "pass": False,
            "score": 0.0,
            "error": f"missing or empty output: {rel(output_path)}",
        }
    else:
        try:
            security_gate = (
                contract_oracle.load_security_gate(security_gate_path)
                if security_gate_path is not None
                else None
            )
            result = contract_oracle.validate_output(
                skill_name,
                output_path.read_text(encoding="utf-8"),
                security_gate=security_gate,
            )
            if security_gate_path is not None:
                result["security_gate_path"] = rel(security_gate_path)
        except Exception as exc:  # pragma: no cover - defensive archive path
            result = {
                "skill": skill_name,
                "pass": False,
                "score": 0.0,
                "error": f"{type(exc).__name__}: {exc}",
            }
    write_json(contract_path, result)
    return result


def invoke_or_reuse(
    *,
    run_id: str,
    suite: str,
    fixture_id: str,
    condition: str,
    resume: bool,
    timeout_sec: int,
    max_retries: int,
    model: str | None,
    effort: str | None,
) -> invoke_harness.InvocationResult | None:
    output_path = saved_output_path(run_id, suite, condition, fixture_id)
    metadata_path = saved_metadata_path(run_id, suite, condition, fixture_id)
    if resume and output_path.exists() and metadata_path.exists():
        return None
    return invoke_harness.invoke(
        run_id=run_id,
        suite=suite,
        fixture_id=fixture_id,
        condition=condition,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        model=model,
        effort=effort,
    )


def run_saved_output(
    *,
    run_id: str,
    suite: str,
    fixture_id: str,
    condition: str,
    skill_name: str,
    resume: bool,
    timeout_sec: int,
    max_retries: int,
    model: str | None,
    effort: str | None,
) -> SavedOutputEntry:
    result = invoke_or_reuse(
        run_id=run_id,
        suite=suite,
        fixture_id=fixture_id,
        condition=condition,
        resume=resume,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        model=model,
        effort=effort,
    )
    output_path = saved_output_path(run_id, suite, condition, fixture_id)
    metadata_path = saved_metadata_path(run_id, suite, condition, fixture_id)
    contract_path = contract_result_path(run_id, suite, condition, fixture_id)
    security_gate_path = security_gate_sidecar_path(suite, fixture_id)
    contract = validate_contract(skill_name, output_path, contract_path, security_gate_path=security_gate_path)
    generation_ok = True if result is None else result.ok
    duration = None if result is None else result.total_duration_sec
    error = None if result is None else result.error
    return SavedOutputEntry(
        suite=suite,
        fixture_id=fixture_id,
        condition=condition,
        output_path=rel(output_path),
        metadata_path=rel(metadata_path),
        contract_path=rel(contract_path),
        security_gate_path=rel(security_gate_path) if security_gate_path is not None else None,
        generation_ok=generation_ok,
        contract_pass=bool(contract.get("pass")),
        contract_score=contract.get("score"),
        duration_sec=duration,
        error=error,
    )


def summarize(run_id: str, suite: str, skill_name: str, entries: list[SavedOutputEntry]) -> dict[str, Any]:
    generation_ok_count = sum(1 for entry in entries if entry.generation_ok)
    contract_pass_count = sum(1 for entry in entries if entry.contract_pass)
    by_condition: dict[str, dict[str, Any]] = {}
    for entry in entries:
        bucket = by_condition.setdefault(
            entry.condition,
            {"count": 0, "generation_ok": 0, "contract_pass": 0},
        )
        bucket["count"] += 1
        bucket["generation_ok"] += int(entry.generation_ok)
        bucket["contract_pass"] += int(entry.contract_pass)

    focused_entries = [
        entry for entry in entries
        if not entry.fixture_id.startswith("smoke-")
    ]
    focused_skill_entries = [
        entry for entry in focused_entries
        if entry.condition == "skill"
    ]
    focused_skill_contract_pass_count = sum(
        1 for entry in focused_skill_entries if entry.contract_pass
    )

    return {
        "run_id": run_id,
        "suite": suite,
        "skill": skill_name,
        "run_dir": rel(RESULTS_ROOT / run_id),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "artifact_counts": {
            "entries": len(entries),
            "outputs": len(entries),
            "contract_results": len(entries),
        },
        "generation_ok_count": generation_ok_count,
        "contract_pass_count": contract_pass_count,
        "all_generation_ok": generation_ok_count == len(entries),
        "all_contracts_pass": contract_pass_count == len(entries),
        "by_condition": by_condition,
        "focused_fixture_summary": {
            "definition": "non-smoke fixtures",
            "entry_count": len(focused_entries),
            "skill_entry_count": len(focused_skill_entries),
            "skill_contract_pass_count": focused_skill_contract_pass_count,
            "all_focused_skill_contracts_pass": (
                bool(focused_skill_entries)
                and focused_skill_contract_pass_count == len(focused_skill_entries)
            ),
        },
        "entries": [asdict(entry) for entry in entries],
        "evidence_boundary": (
            "Saved-output contract evidence only. This is not answer-key scoring, "
            "human review, variance measurement, or public benchmark evidence."
        ),
    }


def write_scorecard(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# WordPress High-Risk Saved-Output Summary",
        "",
        f"Run ID: `{summary['run_id']}`",
        f"Suite: `{summary['suite']}`",
        f"Skill: `{summary['skill']}`",
        f"Run directory: `{summary['run_dir']}`",
        "",
        "## Contract Evidence",
        "",
        f"- Generation OK: `{summary['generation_ok_count']}/{summary['artifact_counts']['entries']}`",
        f"- Contract pass: `{summary['contract_pass_count']}/{summary['artifact_counts']['entries']}`",
        f"- All generation OK: `{str(summary['all_generation_ok']).lower()}`",
        f"- All contracts pass: `{str(summary['all_contracts_pass']).lower()}`",
        "",
        "## Conditions",
        "",
        "| Condition | Outputs | Generation OK | Contract Pass |",
        "| --- | ---: | ---: | ---: |",
    ]
    for condition, item in sorted(summary["by_condition"].items()):
        lines.append(
            f"| `{condition}` | {item['count']} | {item['generation_ok']} | {item['contract_pass']} |"
        )
    lines.extend([
        "",
        "## Focused Fixture Subset",
        "",
        "The focused subset excludes legacy smoke fixtures and is the subset relevant",
        "to the high-risk maturation plan's three-fixture minimum.",
        "",
        f"- Focused skill contracts pass: "
        f"`{summary['focused_fixture_summary']['skill_contract_pass_count']}/"
        f"{summary['focused_fixture_summary']['skill_entry_count']}`",
        f"- All focused skill contracts pass: "
        f"`{str(summary['focused_fixture_summary']['all_focused_skill_contracts_pass']).lower()}`",
        "",
        "## Boundary",
        "",
        summary["evidence_boundary"],
        "",
        "Contract failures on baseline lanes can be useful evidence about contract adherence,",
        "but they are not a quality benchmark by themselves.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, help="WordPress eval suite name.")
    parser.add_argument(
        "--run-id",
        default=f"wordpress-high-risk-saved-outputs-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    )
    parser.add_argument("--fixtures", help="Comma-separated fixture IDs. Default: all suite fixtures.")
    parser.add_argument(
        "--conditions",
        default=",".join(DEFAULT_CONDITIONS),
        help="Comma-separated conditions. Default: skill,baseline-zero-shot,baseline-few-shot.",
    )
    parser.add_argument("--timeout-sec", type=int, default=600)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--model", help="Override model for all lanes.")
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"))
    parser.add_argument("--fail-on-contract-failure", action="store_true")
    parser.add_argument("--allow-generation-failures", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    suite = args.suite
    skill_name = skill_name_for_suite(suite)
    fixtures = fixture_ids_for_suite(suite, parse_csv(args.fixtures) or None)
    conditions = parse_csv(args.conditions, DEFAULT_CONDITIONS)
    entries: list[SavedOutputEntry] = []

    for fixture_id in fixtures:
        for condition in conditions:
            print(f"[saved-output] suite={suite} fixture={fixture_id} condition={condition}", flush=True)
            entries.append(
                run_saved_output(
                    run_id=args.run_id,
                    suite=suite,
                    fixture_id=fixture_id,
                    condition=condition,
                    skill_name=skill_name,
                    resume=args.resume,
                    timeout_sec=args.timeout_sec,
                    max_retries=args.max_retries,
                    model=args.model,
                    effort=args.effort,
                )
            )

    summary = summarize(args.run_id, suite, skill_name, entries)
    run_dir = RESULTS_ROOT / args.run_id
    write_json(run_dir / "manifest.json", summary)
    write_json(run_dir / "contract-summary.json", summary)
    write_scorecard(run_dir / "scorecard.md", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))

    generation_failed = not summary["all_generation_ok"]
    contract_failed = not summary["all_contracts_pass"]
    if generation_failed and not args.allow_generation_failures:
        return 1
    if contract_failed and args.fail_on_contract_failure:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
