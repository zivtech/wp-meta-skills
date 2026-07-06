"""Tests for WordPress candidate pilot generation transport routing."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))

import run_wordpress_candidate_pilot as pilot  # noqa: E402


def _args(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        run_id="candidate-test",
        resume=False,
        generation_model="claude-sonnet-4-6",
        baseline_provider="codex",
        baseline_model="gpt-5.5",
        baseline_effort="medium",
        judge_model="claude-opus-4-6",
        timeout_sec=123,
        baseline_cwd=tmp_path / "baseline-empty",
        upstream_project=pilot.DEFAULT_UPSTREAM_PROJECT,
        upstream_repo=pilot.DEFAULT_UPSTREAM_REPO,
    )


def test_baseline_generation_uses_codex_metadata(tmp_path, monkeypatch):
    calls = []

    def fake_codex(prompt, *, model, effort, timeout_sec):
        calls.append((model, effort, timeout_sec, "Use this fixture:" in prompt))
        return "codex baseline output", "", 0, 0.2, ["codex", "exec", "--model", model]

    monkeypatch.setattr(pilot, "run_codex_baseline", fake_codex)
    monkeypatch.setattr(
        pilot,
        "run_isolated_generation",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Claude should not generate baseline lanes")),
    )

    task = pilot.PilotTask(
        run_index=1,
        fixture_id="security-boundary-risk",
        condition="baseline-zero-shot",
        condition_order=["baseline-zero-shot"],
    )
    output_path, _score_path, metadata_path = pilot.run_generation(
        task,
        tmp_path / "run",
        _args(tmp_path),
        "claude-version-unused",
    )

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert output_path.read_text(encoding="utf-8") == "codex baseline output"
    assert calls == [("gpt-5.5", "medium", 123, True)]
    assert metadata["provider"] == "codex"
    assert metadata["runtime"] == "local_codex_cli"
    assert metadata["model"] == "gpt-5.5"
    assert metadata["model_policy"] == "newest-chatgpt-level-at-run-time"
    assert metadata["baseline_model"] == "gpt-5.5"


def test_zivtech_generation_stays_on_claude_agent_lane(tmp_path, monkeypatch):
    calls = []

    def fake_isolated(prompt, *, model, base, agent_prompt_text, timeout_sec):
        posture = {
            "scratch_cwd": str(Path(base) / "work"),
            "empty_mcp_config": str(Path(base) / "xdg" / "empty.mcp.json"),
            "agent_injection": "content",
        }
        calls.append((model, "wordpress-security-critic" in agent_prompt_text, timeout_sec, base))
        return "claude skill output", "", 0, posture

    monkeypatch.setattr(
        pilot,
        "run_codex_baseline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Codex should not generate skill lanes")),
    )
    monkeypatch.setattr(pilot, "run_isolated_generation", fake_isolated)

    task = pilot.PilotTask(
        run_index=1,
        fixture_id="security-boundary-risk",
        condition="zivtech_prototype",
        condition_order=["zivtech_prototype"],
    )
    output_path, _score_path, metadata_path = pilot.run_generation(
        task,
        tmp_path / "run",
        _args(tmp_path),
        "claude-version",
    )

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert output_path.read_text(encoding="utf-8") == "claude skill output"
    assert calls[0][0] == "claude-sonnet-4-6"
    assert calls[0][1] is True
    assert metadata["provider"] == "claude"
    assert metadata["runtime"] == "local_claude_cli_isolated"
    assert metadata["model"] == "claude-sonnet-4-6"
    assert metadata["model_policy"] is None
    assert metadata["agent"] == "wordpress-security-critic"
    assert metadata["agent_injection"] == "content"
    assert metadata["isolation_posture"]["agent_injection"] == "content"
