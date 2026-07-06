#!/usr/bin/env python3
"""
Skill invocation abstraction for the zivtech-meta-skills eval harness.

Standardises how eval harness runners invoke skills across three modes:

  critic   — single-stage: fixture → skill → output (read-only review)
  planner  — single-stage: fixture → skill → output (architecture plan)
  executor — three-stage pipeline:
               1. rollout   : planner produces a spec from the fixture
               2. reproduction: executor consumes the spec to generate an artifact
               3. grading   : critic/judge scores the artifact

The invocation_mode is read from eval.yaml; callers receive a normalised
InvocationResult regardless of mode.

Usage (standalone):
    python3 evals/harness/invoke.py \
        --suite dataviz-executor \
        --fixture simple-bar-chart \
        --condition skill

Or import invoke_skill() / invoke_executor_pipeline() for use inside other runners.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
SUITES_ROOT = ROOT / "evals" / "suites"
RESULTS_ROOT = ROOT / "evals" / "results"
AGENT_ROOTS = (
    ROOT / "wordpress-skills" / ".claude" / "agents",
    ROOT / ".claude" / "agents",
)
AGENT_ALIASES = {
    "wordpress-planner.block": "wordpress-block-planner",
    "wordpress-planner.content-model": "wordpress-content-model-planner",
    "wordpress-planner.migration": "wordpress-migration-planner",
    "wordpress-planner.plugin": "wordpress-plugin-planner",
    "wordpress-planner.theme": "wordpress-theme-planner",
}

# ---------------------------------------------------------------------------
# Invocation modes
# ---------------------------------------------------------------------------

VALID_MODES = ("critic", "planner", "executor")


def is_baseline_condition(condition: str) -> bool:
    """Return true only for explicit baseline lanes."""
    return condition.startswith("baseline-")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StageResult:
    """Result for a single invocation stage."""

    stage: str            # "single" | "rollout" | "reproduction" | "grading"
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_sec: float
    output_path: Path | None = None


@dataclass
class InvocationResult:
    """Aggregated result for one (fixture, condition) invocation."""

    suite: str
    fixture_id: str
    condition: str
    mode: str
    stages: list[StageResult] = field(default_factory=list)
    ok: bool = False
    final_output: str = ""
    final_output_path: Path | None = None
    total_duration_sec: float = 0.0
    error: str | None = None

    def primary_output(self) -> str:
        """Return the last stage's stdout as the primary artifact."""
        if self.stages:
            return self.stages[-1].stdout
        return ""


# ---------------------------------------------------------------------------
# eval.yaml helpers
# ---------------------------------------------------------------------------


def load_eval_yaml(suite: str) -> dict[str, Any]:
    """Load and parse the eval.yaml for a suite. Returns {} on failure."""
    try:
        import yaml
    except ImportError:
        return {}

    path = SUITES_ROOT / suite / "eval.yaml"
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def get_invocation_mode(suite: str, override: str | None = None) -> str:
    """
    Resolve invocation_mode for a suite.

    Priority:
      1. override argument (CLI --mode flag)
      2. invocation_mode field in eval.yaml
      3. skill.type field in eval.yaml: CRITIC → critic, PLANNER → planner,
         EXECUTOR → executor
      4. Default: "critic"
    """
    if override and override in VALID_MODES:
        return override

    config = load_eval_yaml(suite)

    # Direct field
    direct = config.get("invocation_mode")
    if direct and direct in VALID_MODES:
        return direct

    # Derive from skill.type
    skill_type = (config.get("skill") or {}).get("type", "").lower()
    type_map = {"critic": "critic", "planner": "planner", "executor": "executor"}
    if skill_type in type_map:
        return type_map[skill_type]

    return "critic"


def get_invocation_settings(suite: str) -> dict[str, Any]:
    """Return optional per-suite invocation settings."""
    config = load_eval_yaml(suite)
    settings = config.get("invocation") or {}
    return settings if isinstance(settings, dict) else {}


# ---------------------------------------------------------------------------
# Model subprocess wrappers
# ---------------------------------------------------------------------------


def infer_provider(model: str | None, configured_provider: str | None = None) -> str:
    """Infer the local CLI provider from explicit config or a model id."""
    if configured_provider:
        return configured_provider
    if model and model.lower().startswith("gpt"):
        return "codex"
    return "claude"


def resolve_invocation_runtime(
    settings: dict[str, Any],
    condition: str,
    model: str | None,
    effort: str | None,
) -> tuple[str, str | None, str | None]:
    """Resolve provider/model/effort, with ChatGPT-level defaults for baselines."""
    if is_baseline_condition(condition) and settings.get("baseline_model"):
        resolved_model = model or settings.get("baseline_model")
        resolved_effort = effort or settings.get("baseline_effort") or settings.get("effort")
        provider = infer_provider(resolved_model, settings.get("baseline_provider"))
        return provider, resolved_model, resolved_effort

    resolved_model = model or settings.get("model")
    resolved_effort = effort or settings.get("effort")
    provider = infer_provider(resolved_model, settings.get("provider"))
    return provider, resolved_model, resolved_effort


def build_claude_command(
    prompt: str,
    agent: str | None,
    model: str | None = None,
    effort: str | None = None,
) -> list[str]:
    """Build the non-interactive Claude CLI command used by eval invocations.

    The prompt is sent on stdin by `_run_claude`. Do not append it as a
    positional argument: injected agent prompts can begin with YAML frontmatter
    (`---`), which the CLI would otherwise parse as an option.
    """
    cmd = ["claude", "-p", "--tools", "", "--permission-mode", "bypassPermissions"]
    if model:
        cmd.extend(["--model", model])
    if effort:
        cmd.extend(["--effort", effort])
    if agent:
        cmd.extend(["--agent", agent])
    return cmd


def agent_prompt_path(agent: str | None) -> Path | None:
    """Resolve repo-local agent files that Claude CLI cannot discover by name."""
    if not agent:
        return None
    agent = AGENT_ALIASES.get(agent, agent)
    for root in AGENT_ROOTS:
        path = root / f"{agent}.md"
        if path.exists():
            return path
    return None


def prepare_claude_prompt_and_agent(prompt: str, agent: str | None) -> tuple[str, str | None, Path | None]:
    """Inject nested package agents as content and avoid brittle --agent lookup."""
    path = agent_prompt_path(agent)
    if not path:
        return prompt, agent, None
    agent_prompt = path.read_text(encoding="utf-8").strip()
    return f"{agent_prompt}\n\n---\n\n{prompt.strip()}", None, path


def build_codex_command(
    model: str | None = None,
    effort: str | None = None,
    output_path: str | None = None,
    work_root: str | None = None,
) -> list[str]:
    """Build the non-agentic Codex CLI command used for ChatGPT-level baselines."""
    cmd = ["codex", "exec"]
    if model:
        cmd.extend(["--model", model])
    if effort:
        cmd.extend(["-c", f"model_reasoning_effort={effort}"])
    cmd.extend([
        "--sandbox",
        "read-only",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-rules",
        "--color",
        "never",
    ])
    if work_root:
        cmd.extend(["--cd", work_root])
    if output_path:
        cmd.extend(["--output-last-message", output_path])
    cmd.append("-")
    return cmd


def _run_claude(
    prompt: str,
    agent: str | None,
    timeout_sec: int,
    max_retries: int = 2,
    model: str | None = None,
    effort: str | None = None,
) -> tuple[int, str, str, float]:
    """
    Invoke the Claude CLI and return (exit_code, stdout, stderr, duration_sec).
    Retries on overload up to max_retries times.
    """
    prompt, cli_agent, _agent_prompt_path = prepare_claude_prompt_and_agent(prompt, agent)
    cmd = build_claude_command(prompt, cli_agent, model=model, effort=effort)

    for attempt in range(1, max_retries + 1):
        t0 = time.time()
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout_sec)
            dt = time.time() - t0
            combined = (proc.stdout or "") + (proc.stderr or "")
            if proc.returncode == 0 and proc.stdout.strip() and "overloaded" not in combined.lower():
                return proc.returncode, proc.stdout, proc.stderr or "", dt
            if attempt < max_retries:
                time.sleep(2)
        except subprocess.TimeoutExpired as exc:
            dt = float(timeout_sec)
            stdout = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = ((exc.stderr or b"").decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")) + "\nTimeoutExpired"
            if attempt < max_retries:
                time.sleep(2)
            else:
                return 124, stdout, stderr, dt

    # Final attempt result
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout_sec)
        dt = time.time() - t0
        return proc.returncode, proc.stdout or "", proc.stderr or "", dt
    except subprocess.TimeoutExpired as exc:
        dt = float(timeout_sec)
        stdout = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = ((exc.stderr or b"").decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")) + "\nTimeoutExpired"
        return 124, stdout, stderr, dt


def _run_codex(
    prompt: str,
    timeout_sec: int,
    max_retries: int = 2,
    model: str | None = None,
    effort: str | None = None,
) -> tuple[int, str, str, float]:
    """Invoke the Codex CLI and return (exit_code, stdout, stderr, duration_sec)."""
    with tempfile.TemporaryDirectory(prefix="wp-codex-invoke-") as temp_dir:
        out_path = os.path.join(temp_dir, "last-message.md")
        cmd = build_codex_command(model=model, effort=effort, output_path=out_path, work_root=temp_dir)
        isolated_prompt = (
            "You are running a prompt-only baseline. Do not use tools, shell commands, "
            "file inspection, memory, project rules, or repository context. Use only "
            "the task text below and return the requested answer.\n\n"
            f"{prompt}"
        )
        last_result: tuple[int, str, str, float] | None = None
        for attempt in range(1, max_retries + 1):
            t0 = time.time()
            try:
                proc = subprocess.run(cmd, input=isolated_prompt, text=True, capture_output=True, timeout=timeout_sec)
                dt = time.time() - t0
                try:
                    output = Path(out_path).read_text(encoding="utf-8").strip()
                except FileNotFoundError:
                    output = (proc.stdout or "").strip()
                last_result = (proc.returncode, output, proc.stderr or "", dt)
                if proc.returncode == 0 and output:
                    return last_result
                if attempt < max_retries:
                    time.sleep(2)
            except subprocess.TimeoutExpired as exc:
                dt = float(timeout_sec)
                stdout = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                stderr = ((exc.stderr or b"").decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")) + "\nTimeoutExpired"
                last_result = (124, stdout, stderr, dt)
                if attempt < max_retries:
                    time.sleep(2)
        return last_result or (1, "", "codex invocation did not run", 0.0)


def _run_model(
    prompt: str,
    agent: str | None,
    timeout_sec: int,
    max_retries: int,
    provider: str,
    model: str | None,
    effort: str | None,
) -> tuple[int, str, str, float]:
    """Dispatch to the configured local model CLI."""
    if provider == "claude":
        return _run_claude(prompt, agent, timeout_sec, max_retries, model=model, effort=effort)
    if provider == "codex":
        if agent:
            return 2, "", "codex provider does not support Claude agent invocation; use it for baselines only", 0.0
        return _run_codex(prompt, timeout_sec, max_retries, model=model, effort=effort)
    return 2, "", f"unsupported invocation provider: {provider}", 0.0


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _write_stage_stderr(path: Path, stderr: str, exit_code: int) -> None:
    if stderr.strip() or exit_code != 0:
        path.write_text(stderr, encoding="utf-8")
    elif path.exists():
        path.unlink()


def write_invocation_metadata(
    path: Path,
    *,
    provider: str,
    model: str | None,
    effort: str | None,
    agent: str | None,
    condition: str,
    suite: str,
    fixture_id: str,
    mode: str,
    stage: str,
    settings: dict[str, Any],
) -> None:
    """Write audit metadata for a generated raw output."""
    metadata: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "effort": effort,
        "agent": agent,
        "condition": condition,
        "suite": suite,
        "fixture_id": fixture_id,
        "mode": mode,
        "stage": stage,
        "runtime": "local_codex_cli" if provider == "codex" else "local_claude_cli",
    }
    prompt_path = agent_prompt_path(agent)
    if prompt_path:
        metadata["agent_injection"] = "content"
        metadata["agent_prompt_path"] = rel(prompt_path)
    elif agent:
        metadata["agent_injection"] = "cli-agent"
    if is_baseline_condition(condition):
        metadata["model_policy"] = settings.get("baseline_model_policy")
        metadata["baseline_provider"] = settings.get("baseline_provider")
        metadata["auth_route"] = "ChatGPT/Codex local auth" if provider == "codex" else "Claude local auth"
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Single-stage invocation (critic / planner)
# ---------------------------------------------------------------------------


def invoke_skill(
    run_id: str,
    suite: str,
    fixture_id: str,
    condition: str,
    timeout_sec: int = 360,
    max_retries: int = 2,
    model: str | None = None,
    effort: str | None = None,
    mode_label: str | None = None,
) -> InvocationResult:
    """
    Single-stage invocation for critic or planner skills.

    Reads fixture text, constructs the prompt (skill agent or baseline prompt),
    calls Claude, and writes output to the canonical raw/ path.
    """
    suite_dir = SUITES_ROOT / suite
    fixture_path = suite_dir / "fixtures" / f"{fixture_id}.md"
    fixture_text = _read_text(fixture_path)

    # Build prompt and agent reference
    if condition == "skill":
        prompt = fixture_text
        agent: str | None = suite
    elif is_baseline_condition(condition):
        baseline_path = suite_dir / "baselines" / f"{condition}.md"
        baseline_text = _read_text(baseline_path)
        prompt = baseline_text.strip() + "\n\n---\n\nUse this fixture:\n\n" + fixture_text.strip()
        agent = None
    else:
        raise ValueError(
            f"invoke.py only supports condition='skill' or explicit baseline-* lanes; "
            f"use the suite-specific runner for condition {condition!r}."
        )

    # Output paths
    out_dir = RESULTS_ROOT / run_id / "raw" / suite / condition
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{fixture_id}.md"
    err_file = out_dir / f"{fixture_id}.stderr.txt"
    metadata_file = out_dir / f"{fixture_id}.metadata.json"

    settings = get_invocation_settings(suite)
    provider, model, effort = resolve_invocation_runtime(settings, condition, model, effort)
    rc, stdout, stderr, dt = _run_model(
        prompt,
        agent,
        timeout_sec,
        max_retries,
        provider=provider,
        model=model,
        effort=effort,
    )
    out_file.write_text(stdout, encoding="utf-8")
    _write_stage_stderr(err_file, stderr, rc)
    resolved_mode = mode_label or get_invocation_mode(suite)
    write_invocation_metadata(
        metadata_file,
        provider=provider,
        model=model,
        effort=effort,
        agent=agent,
        condition=condition,
        suite=suite,
        fixture_id=fixture_id,
        mode=resolved_mode,
        stage="single",
        settings=settings,
    )

    ok = rc == 0 and bool(stdout.strip()) and "overloaded" not in stdout.lower()
    stage = StageResult(
        stage="single",
        ok=ok,
        exit_code=rc,
        stdout=stdout,
        stderr=stderr,
        duration_sec=round(dt, 2),
        output_path=out_file,
    )

    return InvocationResult(
        suite=suite,
        fixture_id=fixture_id,
        condition=condition,
        mode=resolved_mode,
        stages=[stage],
        ok=ok,
        final_output=stdout,
        final_output_path=out_file,
        total_duration_sec=round(dt, 2),
        error=stderr if not ok else None,
    )


# ---------------------------------------------------------------------------
# Three-stage executor pipeline
# ---------------------------------------------------------------------------


def invoke_executor_pipeline(
    run_id: str,
    suite: str,
    fixture_id: str,
    condition: str,
    planner_agent: str | None = None,
    executor_agent: str | None = None,
    critic_agent: str | None = None,
    timeout_sec: int = 360,
    max_retries: int = 2,
    model: str | None = None,
    effort: str | None = None,
) -> InvocationResult:
    """
    Three-stage executor pipeline:

      Stage 1 (rollout):       planner generates a spec from the fixture.
      Stage 2 (reproduction):  executor consumes the spec to produce an artifact.
      Stage 3 (grading):       critic/judge scores the artifact.

    Each stage's output is written to:
      evals/results/<run-id>/raw/<suite>/<condition>/<fixture_id>-stage{N}.md

    The final artifact (stage 2 output) is also written to the canonical
    single-stage path so downstream scorers can find it:
      evals/results/<run-id>/raw/<suite>/<condition>/<fixture_id>.md

    Agent names default to conventional names derived from the suite name:
      planner_agent   → "<suite-prefix>-planner"  (e.g. dataviz-planner)
      executor_agent  → "<suite>"                  (e.g. dataviz-executor)
      critic_agent    → "<suite-prefix>-critic"    (e.g. dataviz-critic)
    """
    suite_dir = SUITES_ROOT / suite
    fixture_path = suite_dir / "fixtures" / f"{fixture_id}.md"
    fixture_text = _read_text(fixture_path)

    out_dir = RESULTS_ROOT / run_id / "raw" / suite / condition
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = get_invocation_settings(suite)
    provider, model, effort = resolve_invocation_runtime(settings, condition, model, effort)

    # Derive default agent names from suite name
    prefix = suite.replace("-executor", "").replace("-planner", "")
    _planner_agent = planner_agent or f"{prefix}-planner"
    _executor_agent = executor_agent or suite
    _critic_agent = critic_agent or f"{prefix}-critic"

    stages: list[StageResult] = []
    total_dt = 0.0

    # ── Stage 1: rollout (planner) ────────────────────────────────────────────
    stage1_prompt = fixture_text
    stage1_agent = _planner_agent if condition == "skill" else None
    if condition == "skill":
        pass
    elif is_baseline_condition(condition):
        baseline_path = suite_dir / "baselines" / f"{condition}.md"
        baseline_text = _read_text(baseline_path)
        stage1_prompt = baseline_text.strip() + "\n\n---\n\nFixture:\n\n" + fixture_text.strip()
    else:
        raise ValueError(
            f"invoke.py executor mode only supports condition='skill' or explicit baseline-* lanes; "
            f"use the suite-specific runner for condition {condition!r}."
        )

    rc1, out1, err1, dt1 = _run_model(
        stage1_prompt,
        stage1_agent,
        timeout_sec,
        max_retries,
        provider=provider,
        model=model,
        effort=effort,
    )
    total_dt += dt1
    stage1_file = out_dir / f"{fixture_id}-stage1.md"
    stage1_err_file = out_dir / f"{fixture_id}-stage1.stderr.txt"
    stage1_file.write_text(out1, encoding="utf-8")
    _write_stage_stderr(stage1_err_file, err1, rc1)
    write_invocation_metadata(
        out_dir / f"{fixture_id}-stage1.metadata.json",
        provider=provider,
        model=model,
        effort=effort,
        agent=stage1_agent,
        condition=condition,
        suite=suite,
        fixture_id=fixture_id,
        mode="executor",
        stage="rollout",
        settings=settings,
    )

    ok1 = rc1 == 0 and bool(out1.strip()) and "overloaded" not in out1.lower()
    stages.append(StageResult(
        stage="rollout",
        ok=ok1,
        exit_code=rc1,
        stdout=out1,
        stderr=err1,
        duration_sec=round(dt1, 2),
        output_path=stage1_file,
    ))

    if not ok1:
        return InvocationResult(
            suite=suite,
            fixture_id=fixture_id,
            condition=condition,
            mode="executor",
            stages=stages,
            ok=False,
            total_duration_sec=round(total_dt, 2),
            error=f"Stage 1 (rollout) failed: {err1[:200]}",
        )

    # ── Stage 2: reproduction (executor) ─────────────────────────────────────
    stage2_prompt = (
        "Use the following planner spec to generate the artifact.\n\n"
        "## Planner Spec\n\n" + out1.strip()
    )
    stage2_agent = _executor_agent if condition == "skill" else None

    rc2, out2, err2, dt2 = _run_model(
        stage2_prompt,
        stage2_agent,
        timeout_sec,
        max_retries,
        provider=provider,
        model=model,
        effort=effort,
    )
    total_dt += dt2
    stage2_file = out_dir / f"{fixture_id}-stage2.md"
    stage2_err_file = out_dir / f"{fixture_id}-stage2.stderr.txt"
    stage2_file.write_text(out2, encoding="utf-8")
    _write_stage_stderr(stage2_err_file, err2, rc2)
    write_invocation_metadata(
        out_dir / f"{fixture_id}-stage2.metadata.json",
        provider=provider,
        model=model,
        effort=effort,
        agent=stage2_agent,
        condition=condition,
        suite=suite,
        fixture_id=fixture_id,
        mode="executor",
        stage="reproduction",
        settings=settings,
    )

    ok2 = rc2 == 0 and bool(out2.strip()) and "overloaded" not in out2.lower()
    stages.append(StageResult(
        stage="reproduction",
        ok=ok2,
        exit_code=rc2,
        stdout=out2,
        stderr=err2,
        duration_sec=round(dt2, 2),
        output_path=stage2_file,
    ))

    if not ok2:
        return InvocationResult(
            suite=suite,
            fixture_id=fixture_id,
            condition=condition,
            mode="executor",
            stages=stages,
            ok=False,
            total_duration_sec=round(total_dt, 2),
            error=f"Stage 2 (reproduction) failed: {err2[:200]}",
        )

    # Write the artifact to the canonical path so downstream scorers find it
    canonical_file = out_dir / f"{fixture_id}.md"
    canonical_file.write_text(out2, encoding="utf-8")
    write_invocation_metadata(
        out_dir / f"{fixture_id}.metadata.json",
        provider=provider,
        model=model,
        effort=effort,
        agent=stage2_agent,
        condition=condition,
        suite=suite,
        fixture_id=fixture_id,
        mode="executor",
        stage="canonical_reproduction",
        settings=settings,
    )

    # ── Stage 3: grading (critic) ─────────────────────────────────────────────
    rubric_path = suite_dir / "rubrics" / f"{fixture_id}.rubric.yaml"
    rubric_text = _read_text(rubric_path)

    stage3_prompt = (
        "Review the artifact below against the rubric.\n\n"
        "## Original Fixture\n\n" + fixture_text.strip() + "\n\n"
        "## Generated Artifact\n\n" + out2.strip() + "\n\n"
        "## Rubric\n\n" + rubric_text.strip()
    )
    stage3_agent = _critic_agent if condition == "skill" else None

    rc3, out3, err3, dt3 = _run_model(
        stage3_prompt,
        stage3_agent,
        timeout_sec,
        max_retries,
        provider=provider,
        model=model,
        effort=effort,
    )
    total_dt += dt3
    stage3_file = out_dir / f"{fixture_id}-stage3.md"
    stage3_err_file = out_dir / f"{fixture_id}-stage3.stderr.txt"
    stage3_file.write_text(out3, encoding="utf-8")
    _write_stage_stderr(stage3_err_file, err3, rc3)
    write_invocation_metadata(
        out_dir / f"{fixture_id}-stage3.metadata.json",
        provider=provider,
        model=model,
        effort=effort,
        agent=stage3_agent,
        condition=condition,
        suite=suite,
        fixture_id=fixture_id,
        mode="executor",
        stage="grading",
        settings=settings,
    )

    ok3 = rc3 == 0 and bool(out3.strip()) and "overloaded" not in out3.lower()
    stages.append(StageResult(
        stage="grading",
        ok=ok3,
        exit_code=rc3,
        stdout=out3,
        stderr=err3,
        duration_sec=round(dt3, 2),
        output_path=stage3_file,
    ))

    overall_ok = ok1 and ok2 and ok3
    return InvocationResult(
        suite=suite,
        fixture_id=fixture_id,
        condition=condition,
        mode="executor",
        stages=stages,
        ok=overall_ok,
        final_output=out2,          # the artifact is the primary output
        final_output_path=canonical_file,
        total_duration_sec=round(total_dt, 2),
        error=None if overall_ok else f"Stage 3 (grading) failed: {err3[:200]}",
    )


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------


def invoke(
    run_id: str,
    suite: str,
    fixture_id: str,
    condition: str,
    mode: str | None = None,
    timeout_sec: int = 360,
    max_retries: int = 2,
    model: str | None = None,
    effort: str | None = None,
    **executor_kwargs: Any,
) -> InvocationResult:
    """
    Unified invocation entry point. Resolves mode from eval.yaml if not given.

    Args:
        run_id:         Run identifier (used for output path construction).
        suite:          Suite name.
        fixture_id:     Fixture identifier.
        condition:      Condition name (skill / baseline-zero-shot / …).
        mode:           Override invocation mode (critic / planner / executor).
        timeout_sec:    Per-stage Claude CLI timeout.
        max_retries:    Retry attempts per stage on transient failure.
        **executor_kwargs: Forwarded to invoke_executor_pipeline() when mode=executor
                           (planner_agent, executor_agent, critic_agent).

    Returns:
        InvocationResult
    """
    resolved_mode = get_invocation_mode(suite, mode)

    if resolved_mode == "executor":
        return invoke_executor_pipeline(
            run_id=run_id,
            suite=suite,
            fixture_id=fixture_id,
            condition=condition,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            model=model,
            effort=effort,
            **executor_kwargs,
        )

    # critic and planner share the single-stage path
    return invoke_skill(
        run_id=run_id,
        suite=suite,
        fixture_id=fixture_id,
        condition=condition,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        model=model,
        effort=effort,
        mode_label=resolved_mode,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Invoke a skill for one fixture and condition."
    )
    p.add_argument("--run-id", required=True, help="Run ID for output path.")
    p.add_argument("--suite", required=True, help="Suite name.")
    p.add_argument("--fixture", required=True, help="Fixture ID (without .md).")
    p.add_argument(
        "--condition",
        default="skill",
        help="Condition name (skill / baseline-zero-shot / …). Default: skill.",
    )
    p.add_argument(
        "--mode",
        choices=list(VALID_MODES),
        default=None,
        help="Override invocation mode. Default: read from eval.yaml.",
    )
    p.add_argument("--timeout-sec", type=int, default=360)
    p.add_argument("--max-retries", type=int, default=2)
    p.add_argument("--model", default=None, help="Override local model for generation.")
    p.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"), default=None, help="Override local model reasoning effort.")
    p.add_argument(
        "--planner-agent", default=None, help="Override planner agent name (executor mode)."
    )
    p.add_argument(
        "--executor-agent", default=None, help="Override executor agent name (executor mode)."
    )
    p.add_argument(
        "--critic-agent", default=None, help="Override critic agent name (executor mode)."
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    executor_kwargs: dict[str, Any] = {}
    if args.planner_agent:
        executor_kwargs["planner_agent"] = args.planner_agent
    if args.executor_agent:
        executor_kwargs["executor_agent"] = args.executor_agent
    if args.critic_agent:
        executor_kwargs["critic_agent"] = args.critic_agent

    result = invoke(
        run_id=args.run_id,
        suite=args.suite,
        fixture_id=args.fixture,
        condition=args.condition,
        mode=args.mode,
        timeout_sec=args.timeout_sec,
        max_retries=args.max_retries,
        model=args.model,
        effort=args.effort,
        **executor_kwargs,
    )

    status = "OK" if result.ok else "FAIL"
    print(f"[{status}] mode={result.mode} suite={result.suite} fixture={result.fixture_id} condition={result.condition}")
    for stage in result.stages:
        stg_status = "OK" if stage.ok else "FAIL"
        print(f"  stage={stage.stage} [{stg_status}] exit={stage.exit_code} duration={stage.duration_sec}s")
        if stage.output_path:
            print(f"    output: {stage.output_path.relative_to(ROOT)}")

    if result.error:
        print(f"error: {result.error}", file=sys.stderr)

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
