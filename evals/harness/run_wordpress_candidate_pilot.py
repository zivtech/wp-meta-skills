#!/usr/bin/env python3
"""Run the WordPress candidate discrimination pilot.

The pilot intentionally archives raw outputs, score JSON, metadata, and a
summary decision. Baseline generation uses isolated local Codex/ChatGPT by
default. Zivtech/upstream candidate generation and judging use local Claude CLI
by default, not direct Anthropic SDK/API calls. It does not claim
benchmark-grade superiority.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import random
import subprocess
import sys
import time
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import invoke
    from isolation import run_isolated_generation
    from score_with_claude_cli import load_rubric, score_output
    from llm_judge import judge_result_to_dict
except ImportError as exc:  # pragma: no cover - local script import guard
    raise SystemExit(f"Unable to import eval harness modules: {exc}") from exc


ROOT = Path(__file__).resolve().parent.parent.parent
SUITE = "wordpress-skill-candidate-eval"
SUITE_DIR = ROOT / "evals" / "suites" / SUITE
RESULTS_DIR = ROOT / "evals" / "results" / SUITE
DEFAULT_UPSTREAM_PROJECT = Path("/tmp/wp-agent-skills-pilot-project")
DEFAULT_UPSTREAM_REPO = Path("/tmp/wp-agent-skills-aa735ea")
UPSTREAM_SHA = "aa735ea7111c7924ee988306bcef70439e17dec9"

PILOT_FIXTURES = (
    "security-boundary-risk",
    "block-development-risk",
    "content-model-ambiguous",
    "performance-ops-clean",
)

CONDITIONS = (
    "baseline-zero-shot",
    "baseline-few-shot",
    "raw_upstream_candidate",
    "zivtech_prototype",
)

ZIVTECH_AGENTS = {
    "security-boundary-risk": "wordpress-security-critic",
    "block-development-risk": "wordpress-block-planner",
    "content-model-ambiguous": "wordpress-content-model-planner",
    "performance-ops-clean": "wordpress-performance-critic",
}

UPSTREAM_SKILLS = {
    "security-boundary-risk": "wp-plugin-development",
    "block-development-risk": "wp-block-development",
    "content-model-ambiguous": "wp-rest-api",
    "performance-ops-clean": "wp-performance",
}


@dataclass(frozen=True)
class PilotTask:
    run_index: int
    fixture_id: str
    condition: str
    condition_order: list[str]


def wordpress_agent_dir() -> Path:
    monorepo_dir = ROOT / "wordpress-skills" / ".claude" / "agents"
    if monorepo_dir.exists():
        return monorepo_dir
    return ROOT / ".claude" / "agents"


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_codex_baseline(
    prompt: str,
    *,
    model: str,
    effort: str,
    timeout_sec: int,
) -> tuple[str, str, int, float, list[str]]:
    """Run a prompt-only baseline through isolated local Codex."""
    with tempfile.TemporaryDirectory(prefix="wp-candidate-codex-") as temp_dir:
        out_path = Path(temp_dir) / "last-message.md"
        command = invoke.build_codex_command(
            model=model,
            effort=effort,
            output_path=str(out_path),
            work_root=temp_dir,
        )
        isolated_prompt = (
            "You are running a prompt-only baseline. Do not use tools, shell commands, "
            "file inspection, memory, project rules, or repository context. Use only "
            "the task text below and return the requested answer.\n\n"
            f"{prompt}"
        )
        started = time.time()
        proc = subprocess.run(
            command,
            input=isolated_prompt,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
            check=False,
        )
        duration = round(time.time() - started, 2)
        try:
            output = out_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            output = proc.stdout or ""
        return output, proc.stderr or "", proc.returncode, duration, command


def baseline_prompt(fixture_text: str, condition: str) -> tuple[str, Path]:
    prompt_path = SUITE_DIR / "baselines" / f"{condition}.md"
    prompt_text = prompt_path.read_text(encoding="utf-8").strip()
    return (
        prompt_text + "\n\n---\n\nUse this fixture:\n\n" + fixture_text.strip(),
        prompt_path,
    )


def upstream_prompt(
    fixture_text: str,
    fixture_id: str,
    upstream_project: Path,
) -> tuple[str, Path, str, str]:
    skill = UPSTREAM_SKILLS[fixture_id]
    prompt_path = upstream_project / ".claude" / "skills" / skill / "SKILL.md"
    if not prompt_path.exists():
        raise FileNotFoundError(
            f"Missing upstream skill prompt for {fixture_id}: {prompt_path}"
        )
    prompt = "## Fixture\n\n" + fixture_text.strip()
    return prompt, prompt_path, skill, prompt_path.read_text(encoding="utf-8")


def zivtech_prompt(fixture_text: str, fixture_id: str) -> tuple[str, Path, str, str]:
    agent = ZIVTECH_AGENTS[fixture_id]
    prompt_path = wordpress_agent_dir() / f"{agent}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Missing Zivtech agent prompt for {fixture_id}: {prompt_path}")
    return fixture_text, prompt_path, agent, prompt_path.read_text(encoding="utf-8")


def output_paths(run_dir: Path, task: PilotTask) -> tuple[Path, Path, Path, Path]:
    raw_dir = run_dir / f"run-{task.run_index}" / "raw" / task.condition
    score_dir = run_dir / f"run-{task.run_index}" / "scores" / task.condition
    meta_dir = run_dir / f"run-{task.run_index}" / "metadata" / task.condition
    err_dir = run_dir / f"run-{task.run_index}" / "stderr" / task.condition
    return (
        raw_dir / f"{task.fixture_id}.md",
        score_dir / f"{task.fixture_id}.score.json",
        meta_dir / f"{task.fixture_id}.metadata.json",
        err_dir / f"{task.fixture_id}.stderr.txt",
    )


def enrich_metadata(
    metadata_path: Path,
    *,
    task: PilotTask,
    output_path: Path,
    score_path: Path,
    prompt_path: Path | None,
    fixture_path: Path,
) -> None:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    output_text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    rubric_path = SUITE_DIR / "rubrics" / f"{task.fixture_id}.rubric.yaml"
    metadata.update(
        {
            "metadata_path": rel(metadata_path),
            "output_path": rel(output_path),
            "score_path": rel(score_path),
            "fixture_sha256": sha256_file(fixture_path),
            "rubric_sha256": sha256_file(rubric_path),
            "prompt_sha256": sha256_file(prompt_path) if prompt_path else None,
            "output_sha256": sha256_file(output_path),
            "judge_output_truncated_before_scoring": len(output_text) > 12000,
        }
    )
    write_json(metadata_path, metadata)


def build_tasks(runs: int, seed: str) -> list[PilotTask]:
    rng = random.Random(seed)
    tasks: list[PilotTask] = []
    for run_index in range(1, runs + 1):
        for fixture_id in PILOT_FIXTURES:
            order = list(CONDITIONS)
            rng.shuffle(order)
            for condition in order:
                tasks.append(
                    PilotTask(
                        run_index=run_index,
                        fixture_id=fixture_id,
                        condition=condition,
                        condition_order=order,
                    )
                )
    return tasks


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_generation(
    task: PilotTask,
    run_dir: Path,
    args: argparse.Namespace,
    claude_version: str,
) -> tuple[Path, Path, Path]:
    output_path, score_path, metadata_path, stderr_path = output_paths(run_dir, task)

    fixture_path = SUITE_DIR / "fixtures" / f"{task.fixture_id}.md"
    fixture_text = fixture_path.read_text(encoding="utf-8")
    agent = None
    upstream_skill = None
    prompt_path: Path | None = None
    cwd = ROOT
    model = args.generation_model
    provider = "claude"
    runtime = "local_claude_cli"
    model_policy = None
    effort = None
    agent_prompt_text = None
    isolation_posture = None

    if task.condition.startswith("baseline-"):
        prompt, prompt_path = baseline_prompt(fixture_text, task.condition)
        cwd = args.baseline_cwd
        model = args.baseline_model
        effort = args.baseline_effort
        provider = "codex"
        runtime = "local_codex_cli"
        model_policy = "newest-chatgpt-level-at-run-time"
    elif task.condition == "raw_upstream_candidate":
        prompt, prompt_path, upstream_skill, agent_prompt_text = upstream_prompt(
            fixture_text,
            task.fixture_id,
            args.upstream_project,
        )
        cwd = args.upstream_project
    elif task.condition == "zivtech_prototype":
        prompt, prompt_path, agent, agent_prompt_text = zivtech_prompt(fixture_text, task.fixture_id)
    else:  # pragma: no cover - guarded by CONDITIONS
        raise ValueError(f"Unsupported condition: {task.condition}")

    if args.resume and output_path.exists() and metadata_path.exists():
        enrich_metadata(
            metadata_path,
            task=task,
            output_path=output_path,
            score_path=score_path,
            prompt_path=prompt_path,
            fixture_path=fixture_path,
        )
        return output_path, score_path, metadata_path

    if provider == "codex":
        output, stderr, exit_code, duration, command = run_codex_baseline(
            prompt,
            model=model,
            effort=effort or "medium",
            timeout_sec=args.timeout_sec,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="wp-candidate-claude-") as base:
            started = time.time()
            output, stderr, exit_code, isolation_posture = run_isolated_generation(
                prompt,
                model=model,
                base=Path(base),
                agent_prompt_text=agent_prompt_text,
                timeout_sec=args.timeout_sec,
            )
            duration = round(time.time() - started, 2)
        runtime = "local_claude_cli_isolated"
        cwd = Path(isolation_posture["scratch_cwd"]) if isolation_posture else cwd
        command = [
            "claude",
            "-p",
            "--model",
            model,
            "--tools",
            "",
            "--permission-mode",
            "bypassPermissions",
            "--strict-mcp-config",
            "--mcp-config",
            isolation_posture["empty_mcp_config"] if isolation_posture else "<unknown>",
        ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output, encoding="utf-8")
    if stderr.strip() or exit_code != 0:
        stderr_path.write_text(stderr, encoding="utf-8")
    elif stderr_path.exists():
        stderr_path.unlink()

    metadata = {
        "run_id": args.run_id,
        "suite": SUITE,
        "fixture_id": task.fixture_id,
        "fixture_path": rel(fixture_path),
        "condition": task.condition,
        "condition_order": task.condition_order,
        "run_index": task.run_index,
        "provider": provider,
        "runtime": runtime,
        "model": model,
        "model_policy": model_policy,
        "effort": effort,
        "claude_cli_version": claude_version,
        "prompt_path": rel(prompt_path) if prompt_path else None,
        "agent": agent,
        "agent_injection": "content" if agent_prompt_text else None,
        "upstream_skill": upstream_skill,
        "upstream_repo": str(args.upstream_repo) if task.condition == "raw_upstream_candidate" else None,
        "upstream_commit": UPSTREAM_SHA if task.condition == "raw_upstream_candidate" else None,
        "cwd": str(cwd),
        "output_path": rel(output_path),
        "stderr_path": rel(stderr_path) if stderr_path.exists() else None,
        "score_path": rel(score_path),
        "metadata_path": rel(metadata_path),
        "fixture_sha256": sha256_file(fixture_path),
        "rubric_sha256": sha256_file(SUITE_DIR / "rubrics" / f"{task.fixture_id}.rubric.yaml"),
        "prompt_sha256": sha256_file(prompt_path) if prompt_path else None,
        "output_sha256": sha256_file(output_path),
        "judge_output_truncated_before_scoring": len(output) > 12000,
        "generation_command": command,
        "generation_exit_code": exit_code,
        "generation_duration_sec": duration,
        "isolation_posture": isolation_posture,
        "judge_model": args.judge_model,
        "baseline_provider": args.baseline_provider,
        "baseline_model_policy": "newest-chatgpt-level-at-run-time",
        "baseline_model": args.baseline_model,
        "baseline_effort": args.baseline_effort,
        "scoring_config": {
            "rubric_path": rel(SUITE_DIR / "rubrics" / f"{task.fixture_id}.rubric.yaml"),
            "scoring_method": "quality_weighted",
            "criteria_source": "criteria + domain_signals",
            "single_judge": True,
            "publication_status": "internal-only, uncalibrated single-judge",
        },
    }
    write_json(metadata_path, metadata)

    if exit_code != 0 or not output.strip():
        raise RuntimeError(
            f"Generation failed for run {task.run_index} {task.condition} "
            f"{task.fixture_id}; stderr at {stderr_path}"
        )
    return output_path, score_path, metadata_path


def run_score(
    task: PilotTask,
    output_path: Path,
    score_path: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    if args.resume and score_path.exists():
        return json.loads(score_path.read_text(encoding="utf-8"))

    rubric_path = SUITE_DIR / "rubrics" / f"{task.fixture_id}.rubric.yaml"
    rubric = load_rubric(rubric_path)
    output_text = output_path.read_text(encoding="utf-8")
    result = score_output(
        output_text=output_text,
        rubric=rubric,
        fixture_id=task.fixture_id,
        condition=task.condition,
        model=args.judge_model,
        timeout_sec=args.timeout_sec,
    )
    payload = judge_result_to_dict(result)
    write_json(score_path, payload)
    return payload


def run_task(
    task: PilotTask,
    run_dir: Path,
    args: argparse.Namespace,
    claude_cli_version: str,
) -> dict[str, Any]:
    output_path, score_path, _metadata_path = run_generation(
        task,
        run_dir,
        args,
        claude_cli_version,
    )
    return run_score(task, output_path, score_path, args)


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def summarize(run_dir: Path, args: argparse.Namespace, scores: list[dict[str, Any]]) -> dict[str, Any]:
    by_condition: dict[str, list[float]] = {condition: [] for condition in CONDITIONS}
    by_fixture_condition: dict[str, dict[str, list[float]]] = {}
    human_review_count = 0

    for item in scores:
        condition = item["condition"]
        fixture_id = item["fixture_id"]
        score = float(item["composite_score"])
        by_condition.setdefault(condition, []).append(score)
        by_fixture_condition.setdefault(fixture_id, {}).setdefault(condition, []).append(score)
        if item.get("human_review_required"):
            human_review_count += 1

    condition_means = {
        condition: mean(values)
        for condition, values in by_condition.items()
    }
    weak_mean = condition_means.get("baseline-zero-shot")
    strong_mean = condition_means.get("zivtech_prototype")
    separation_delta = None
    if weak_mean is not None and strong_mean is not None:
        separation_delta = round((strong_mean - weak_mean) / 100.0, 3)

    fixture_summary: dict[str, dict[str, Any]] = {}
    for fixture_id, condition_map in sorted(by_fixture_condition.items()):
        fixture_summary[fixture_id] = {
            condition: mean(values)
            for condition, values in sorted(condition_map.items())
        }

    summary = {
        "run_id": args.run_id,
        "suite": SUITE,
        "run_dir": rel(run_dir),
        "runs_per_condition": args.runs,
        "fixtures": list(PILOT_FIXTURES),
        "conditions": list(CONDITIONS),
        "artifact_counts": {
            "outputs": len(scores),
            "scores": len(scores),
            "metadata": len(scores),
        },
        "condition_mean_composite": condition_means,
        "fixture_condition_mean_composite": fixture_summary,
        "known_weak_condition": "baseline-zero-shot",
        "known_strong_condition": "zivtech_prototype",
        "separation_delta_normalized": separation_delta,
        "required_delta_normalized": 0.2,
        "pilot_passed": bool(separation_delta is not None and separation_delta >= 0.2),
        "fallback_required": bool(separation_delta is None or separation_delta < 0.2),
        "fallback": "blind_pairwise_preference" if separation_delta is None or separation_delta < 0.2 else None,
        "judge_agreement_status": "internal-only, uncalibrated single-judge",
        "human_review_required_count": human_review_count,
        "judge_model": args.judge_model,
        "generation_model": args.generation_model,
        "generation_models": {
            "baseline_provider": args.baseline_provider,
            "baseline_model_policy": "newest-chatgpt-level-at-run-time",
            "baseline_model": args.baseline_model,
            "baseline_effort": args.baseline_effort,
            "candidate_provider": "claude",
            "candidate_model": args.generation_model,
        },
        "upstream_commit": UPSTREAM_SHA,
    }
    manifest = build_manifest(run_dir, args, summary)
    write_json(run_dir / "manifest.json", manifest)
    write_json(run_dir / "summary.json", summary)
    write_json(run_dir / "pilot-summary.json", summary)
    write_markdown_summary(run_dir / "scorecard.md", summary)
    write_markdown_summary(run_dir / "pilot-summary.md", summary)
    write_internal_only_decision(run_dir / "internal-only-decision.md", summary)
    return summary


def build_manifest(
    run_dir: Path,
    args: argparse.Namespace,
    summary: dict[str, Any],
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for metadata_path in sorted(run_dir.glob("run-*/metadata/*/*.metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        score_path = ROOT / metadata["score_path"]
        score = json.loads(score_path.read_text(encoding="utf-8")) if score_path.exists() else {}
        entries.append(
            {
                "run_index": metadata["run_index"],
                "fixture_id": metadata["fixture_id"],
                "condition": metadata["condition"],
                "condition_order": metadata["condition_order"],
                "output_path": metadata["output_path"],
                "metadata_path": metadata.get("metadata_path", rel(metadata_path)),
                "score_path": metadata["score_path"],
                "fixture_sha256": metadata.get("fixture_sha256"),
                "rubric_sha256": metadata.get("rubric_sha256"),
                "prompt_sha256": metadata.get("prompt_sha256"),
                "output_sha256": metadata.get("output_sha256"),
                "generation_exit_code": metadata.get("generation_exit_code"),
                "generation_duration_sec": metadata.get("generation_duration_sec"),
                "provider": metadata.get("provider"),
                "runtime": metadata.get("runtime"),
                "model": metadata.get("model"),
                "model_policy": metadata.get("model_policy"),
                "judge_model": metadata.get("judge_model"),
                "composite_score": score.get("composite_score"),
                "human_review_required": score.get("human_review_required"),
            }
        )

    return {
        "run_id": args.run_id,
        "suite": SUITE,
        "run_dir": rel(run_dir),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "expected_artifacts": {
            "outputs": len(PILOT_FIXTURES) * len(CONDITIONS) * args.runs,
            "metadata": len(PILOT_FIXTURES) * len(CONDITIONS) * args.runs,
            "scores": len(PILOT_FIXTURES) * len(CONDITIONS) * args.runs,
        },
        "actual_artifacts": summary["artifact_counts"],
        "entries": entries,
    }


def write_markdown_summary(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# WordPress Candidate Pilot Summary",
        "",
        f"Run ID: `{summary['run_id']}`",
        f"Run directory: `{summary['run_dir']}`",
        "",
        "## Verdict",
        "",
        f"- Pilot passed: `{str(summary['pilot_passed']).lower()}`",
        f"- Normalized separation delta: `{summary['separation_delta_normalized']}`",
        f"- Required normalized delta: `{summary['required_delta_normalized']}`",
        f"- Judge agreement status: {summary['judge_agreement_status']}",
        f"- Fallback required: `{str(summary['fallback_required']).lower()}`",
        "",
        "This is internal pilot evidence only. It is not a publishable benchmark result.",
        "",
        "## Condition Means",
        "",
        "| Condition | Mean composite |",
        "| --- | ---: |",
    ]
    for condition, value in summary["condition_mean_composite"].items():
        lines.append(f"| `{condition}` | {value} |")
    lines.extend(["", "## Fixture Means", ""])
    for fixture_id, condition_map in summary["fixture_condition_mean_composite"].items():
        lines.extend([f"### `{fixture_id}`", "", "| Condition | Mean composite |", "| --- | ---: |"])
        for condition, value in condition_map.items():
            lines.append(f"| `{condition}` | {value} |")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_internal_only_decision(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Internal-Only Decision",
        "",
        f"Run ID: `{summary['run_id']}`",
        "",
        "This pilot uses a single local Claude judge pass. No independent human or multi-judge agreement metric has been measured.",
        "",
        "## Boundary",
        "",
        "- These results may be used as internal pilot evidence for deciding whether the candidate rubric separates weak and strong outputs.",
        "- These results must not be used as external benchmark, superiority, or public release claims.",
        "- If the pilot saturates or fails the separation gate, use the configured blind pairwise preference fallback before making adoption decisions.",
        "",
        "## Current State",
        "",
        f"- Pilot passed: `{str(summary['pilot_passed']).lower()}`",
        f"- Fallback required: `{str(summary['fallback_required']).lower()}`",
        f"- Judge agreement status: {summary['judge_agreement_status']}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def claude_version() -> str:
    proc = subprocess.run(
        ["claude", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    return (proc.stdout or proc.stderr or "unknown").strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-id",
        default=f"wordpress-candidate-pilot-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--generation-model",
        default="claude-sonnet-4-6",
        help="Claude model for Zivtech/upstream candidate generation.",
    )
    parser.add_argument("--baseline-provider", default="codex", choices=["codex"])
    parser.add_argument("--baseline-model", default="gpt-5.5")
    parser.add_argument("--baseline-effort", default="medium")
    parser.add_argument("--judge-model", default="claude-opus-4-6")
    parser.add_argument("--timeout-sec", type=int, default=900)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of concurrent generation+scoring workers.",
    )
    parser.add_argument(
        "--fail-on-fallback",
        action="store_true",
        help="Exit nonzero when the pilot requires blind pairwise fallback.",
    )
    parser.add_argument("--seed", help="Deterministic condition-order seed.")
    parser.add_argument("--upstream-project", type=Path, default=DEFAULT_UPSTREAM_PROJECT)
    parser.add_argument("--upstream-repo", type=Path, default=DEFAULT_UPSTREAM_REPO)
    parser.add_argument(
        "--baseline-cwd",
        type=Path,
        default=Path("/tmp/wp-candidate-baseline-empty"),
        help="Directory without repo-local skills for baseline generation.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")

    args.baseline_cwd.mkdir(parents=True, exist_ok=True)
    run_dir = RESULTS_DIR / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    seed = args.seed or args.run_id
    tasks = build_tasks(args.runs, seed)
    version = claude_version()
    scores: list[dict[str, Any]] = []

    if args.workers <= 1:
        for index, task in enumerate(tasks, start=1):
            print(
                f"[{index}/{len(tasks)}] run={task.run_index} "
                f"condition={task.condition} fixture={task.fixture_id}",
                flush=True,
            )
            scores.append(run_task(task, run_dir, args, version))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_map = {
                executor.submit(run_task, task, run_dir, args, version): task
                for task in tasks
            }
            for index, future in enumerate(concurrent.futures.as_completed(future_map), start=1):
                task = future_map[future]
                scores.append(future.result())
                print(
                    f"[{index}/{len(tasks)}] completed run={task.run_index} "
                    f"condition={task.condition} fixture={task.fixture_id}",
                    flush=True,
                )

    summary = summarize(run_dir, args, scores)
    print(json.dumps(summary, indent=2))
    if args.fail_on_fallback and summary["fallback_required"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
