"""Tests for eval harness Claude invocation command construction."""

import sys
import json
from pathlib import Path

import pytest


HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))

import invoke


def test_build_claude_command_includes_model_effort_and_cli_agent():
    command = invoke.build_claude_command(
        "Return ok",
        "external-agent",
        model="sonnet",
        effort="low",
    )

    assert command[:5] == ["claude", "-p", "--tools", "", "--permission-mode"]
    assert "--model" in command
    assert command[command.index("--model") + 1] == "sonnet"
    assert "--effort" in command
    assert command[command.index("--effort") + 1] == "low"
    assert "--agent" in command
    assert command[command.index("--agent") + 1] == "external-agent"
    assert "Return ok" not in command


def test_prepare_claude_prompt_injects_nested_wordpress_agent():
    prompt, cli_agent, agent_path = invoke.prepare_claude_prompt_and_agent(
        "Review this fixture",
        "wordpress-security-critic",
    )

    assert cli_agent is None
    assert agent_path is not None
    assert agent_path.name == "wordpress-security-critic.md"
    assert "You are the WordPress Security Critic" in prompt
    assert prompt.rstrip().endswith("Review this fixture")


def test_prepare_claude_prompt_resolves_dot_named_wordpress_agent_alias():
    prompt, cli_agent, agent_path = invoke.prepare_claude_prompt_and_agent(
        "Plan this migration",
        "wordpress-planner.migration",
    )

    assert cli_agent is None
    assert agent_path is not None
    assert agent_path.name == "wordpress-migration-planner.md"
    assert "WordPress Migration Planner" in prompt
    assert prompt.rstrip().endswith("Plan this migration")


def test_build_codex_command_is_non_agentic_chatgpt_baseline():
    command = invoke.build_codex_command(
        model="gpt-5.5",
        effort="medium",
        output_path="/tmp/last.md",
        work_root="/tmp/wp-baseline",
    )

    assert command[:4] == ["codex", "exec", "--model", "gpt-5.5"]
    assert "-c" in command
    assert command[command.index("-c") + 1] == "model_reasoning_effort=medium"
    assert "--sandbox" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in command
    assert "--ephemeral" in command
    assert "--ignore-rules" in command
    assert "--cd" in command
    assert command[command.index("--cd") + 1] == "/tmp/wp-baseline"
    assert "--output-last-message" in command
    assert command[-1] == "-"


def test_resolve_invocation_runtime_uses_codex_for_configured_baselines():
    settings = {
        "model": "sonnet",
        "effort": "low",
        "baseline_provider": "codex",
        "baseline_model": "gpt-5.5",
        "baseline_effort": "medium",
    }

    provider, model, effort = invoke.resolve_invocation_runtime(
        settings,
        "baseline-few-shot",
        model=None,
        effort=None,
    )

    assert provider == "codex"
    assert model == "gpt-5.5"
    assert effort == "medium"


def test_resolve_invocation_runtime_does_not_treat_candidate_lane_as_baseline():
    settings = {
        "model": "sonnet",
        "effort": "low",
        "baseline_provider": "codex",
        "baseline_model": "gpt-5.5",
        "baseline_effort": "medium",
    }

    provider, model, effort = invoke.resolve_invocation_runtime(
        settings,
        "raw_upstream_candidate",
        model=None,
        effort=None,
    )

    assert provider == "claude"
    assert model == "sonnet"
    assert effort == "low"


def test_wordpress_plugin_executor_invocation_settings_are_fast_lane():
    settings = invoke.get_invocation_settings("wordpress-plugin-executor")

    assert settings["model"] == "sonnet"
    assert settings["effort"] == "low"
    assert settings["baseline_provider"] == "codex"
    assert settings["baseline_model_policy"] == "newest-chatgpt-level-at-run-time"
    assert settings["baseline_model"] == "gpt-5.5"


def test_wordpress_block_executor_invocation_settings_use_chatgpt_baseline():
    settings = invoke.get_invocation_settings("wordpress-block-executor")

    assert settings["model"] == "sonnet"
    assert settings["effort"] == "low"
    assert settings["baseline_provider"] == "codex"
    assert settings["baseline_model_policy"] == "newest-chatgpt-level-at-run-time"
    assert settings["baseline_model"] == "gpt-5.5"


def test_wordpress_candidate_suite_declares_chatgpt_baseline_policy():
    settings = invoke.get_invocation_settings("wordpress-skill-candidate-eval")

    assert settings["baseline_provider"] == "codex"
    assert settings["baseline_model_policy"] == "newest-chatgpt-level-at-run-time"
    assert settings["baseline_model"] == "gpt-5.5"
    assert "run_wordpress_candidate_pilot.py" in settings["note"]
    assert "run_pairwise_pilot.py" in settings["note"]
    assert "baseline-* lanes through Codex" in settings["note"]


def test_invoke_skill_fails_closed_for_candidate_lanes():
    with pytest.raises(ValueError, match="suite-specific runner"):
        invoke.invoke_skill(
            run_id="candidate-routing-test",
            suite="wordpress-skill-candidate-eval",
            fixture_id="security-boundary-risk",
            condition="raw_upstream_candidate",
        )


def test_write_invocation_metadata_records_chatgpt_baseline_policy(tmp_path):
    metadata_path = tmp_path / "fixture.metadata.json"

    invoke.write_invocation_metadata(
        metadata_path,
        provider="codex",
        model="gpt-5.5",
        effort="medium",
        agent=None,
        condition="baseline-zero-shot",
        suite="wordpress-plugin-executor",
        fixture_id="smoke-wordpress-v1",
        mode="planner",
        stage="single",
        settings={
            "baseline_provider": "codex",
            "baseline_model_policy": "newest-chatgpt-level-at-run-time",
        },
    )

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert metadata["provider"] == "codex"
    assert metadata["runtime"] == "local_codex_cli"
    assert metadata["model"] == "gpt-5.5"
    assert metadata["model_policy"] == "newest-chatgpt-level-at-run-time"
    assert metadata["auth_route"] == "ChatGPT/Codex local auth"


def test_write_stage_stderr_removes_stale_success_file(tmp_path):
    path = tmp_path / "fixture.stderr.txt"
    path.write_text("old failure", encoding="utf-8")

    invoke._write_stage_stderr(path, "", 0)

    assert not path.exists()
