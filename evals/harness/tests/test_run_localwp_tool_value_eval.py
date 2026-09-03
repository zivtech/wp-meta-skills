"""Tests for the runner skeleton (design §4.2, §9.1) — the parts that need
no live agent and no live PHP/MySQL stack: reset/seed orchestration
against a real fixture's real seed.sh, arm file setup, pre-run assertion
logic, agent-command construction, and grading.json assembly.

`invoke_agent()` and `assert_mcp_tools_list_count()` were wired for real
2026-09-03 (proven against a live Docker stack, a live headless MCP server,
and one real `claude -p` run — see this session's report and
evals/suites/localwp-agent-tools-value/README.md). They are exercised here
with a FAKE `claude` binary / a monkeypatched MCP client respectively —
still no live agent, no live PHP/MySQL stack, no network — to keep this
file's own promise (module docstring, historically) of running with none of
that. `assert_mcp_tools_list_count`'s no-server-details fallback (still a
documented, honest "not wired up" precheck result, not a false pass) is
also covered, since a caller with no server details is a real case (e.g.
this very test file, or a unit test with no Docker).
"""
from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import replace
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

import run_localwp_tool_value_eval as runner  # noqa: E402

FIXTURE_1_DIR = (
    Path(__file__).resolve().parents[3]
    / "evals" / "suites" / "localwp-agent-tools-value" / "fixtures" / "fatal-undefined-function-page-scoped"
)


def _config(tmp_path: Path, arm: runner.Arm = "C0", rep: int = 1) -> runner.CellConfig:
    site_dir = tmp_path / "site"
    site_root = site_dir / "app" / "public"
    golden_dir = tmp_path / "golden"
    (golden_dir / "public" / "wp-content" / "plugins" / "acme-events").mkdir(parents=True, exist_ok=True)
    return runner.CellConfig(
        fixture_dir=FIXTURE_1_DIR, arm=arm, rep=rep, site_root=site_root, site_dir=site_dir,
        golden_dir=golden_dir, run_dir=tmp_path / "run", model="claude-test-model",
    )


def test_reset_to_golden_restores_from_golden_public_dir(tmp_path: Path):
    config = _config(tmp_path)
    marker = config.golden_dir / "public" / "wp-content" / "plugins" / "acme-events" / "marker.php"
    marker.write_text("<?php // golden marker\n")
    # pre-existing stray state from a hypothetical prior cell
    config.site_root.mkdir(parents=True)
    (config.site_root / "leftover.txt").write_text("stale")
    (config.site_root / ".mcp.json").write_text("{}")
    (config.site_root / "CLAUDE.md").write_text("stale context")

    runner.reset_to_golden(config)

    assert not (config.site_root / "leftover.txt").exists()
    assert not (config.site_root / ".mcp.json").exists()
    assert not (config.site_root / "CLAUDE.md").exists()
    assert (config.site_root / "wp-content" / "plugins" / "acme-events" / "marker.php").is_file()
    assert (config.site_dir / "logs" / "php" / "error.log").read_text() == ""


def test_reset_to_golden_without_prebuilt_public_dir_creates_empty_root(tmp_path: Path):
    config = _config(tmp_path)
    # golden/public/ absent (this suite's built fixtures ship a plugin
    # source tree directly, not a pre-assembled public/ dir)
    import shutil
    shutil.rmtree(config.golden_dir)
    config.golden_dir.mkdir()

    runner.reset_to_golden(config)
    assert config.site_root.is_dir()
    assert (config.site_dir / "logs" / "php" / "error.log").is_file()


def test_run_seed_against_the_real_fixture_1_seed_script(tmp_path: Path):
    config = _config(tmp_path)
    runner.reset_to_golden(config)
    # materialize the real golden plugin source (fixture 1's own, not the
    # bare marker dir _config() creates) so seed.sh has real content to
    # mutate — mirroring what a real golden restore would produce.
    import shutil
    shutil.rmtree(config.site_root / "wp-content" / "plugins" / "acme-events")
    shutil.copytree(
        FIXTURE_1_DIR / "plugins" / "acme-events", config.site_root / "wp-content" / "plugins" / "acme-events",
    )

    completed = runner.run_seed(config)
    assert completed.returncode == 0, completed.stderr
    plugin_file = config.site_root / "wp-content" / "plugins" / "acme-events" / "acme-events.php"
    assert "if ( is_admin() ) {" in plugin_file.read_text()


def test_write_context_file_variant_none_removes_existing_file(tmp_path: Path):
    config = _config(tmp_path, arm="C0")
    config.site_root.mkdir(parents=True)
    (config.site_root / "CLAUDE.md").write_text("stale")
    result = runner.write_context_file(config, variant="none")
    assert result is None
    assert not (config.site_root / "CLAUDE.md").exists()


def test_write_context_file_variant_full_writes_and_hashes(tmp_path: Path):
    config = _config(tmp_path, arm="T")
    config.site_root.mkdir(parents=True)
    text = "# WordPress Site: acme\n\nfull context\n"
    result = runner.write_context_file(config, variant="full", full_context_text=text)
    import hashlib
    assert result == hashlib.sha256(text.encode()).hexdigest()
    assert (config.site_root / "CLAUDE.md").read_text() == text


def test_write_context_file_variant_stripped_applies_the_real_transform(tmp_path: Path):
    config = _config(tmp_path, arm="C1-ctx")
    config.site_root.mkdir(parents=True)
    text = "# Title\n\ntool line here\n\nkeep this\n"
    result = runner.write_context_file(config, variant="stripped", full_context_text=text)
    written = (config.site_root / "CLAUDE.md").read_text()
    assert "tool line" not in written
    assert "keep this" in written
    import hashlib
    assert result == hashlib.sha256(written.encode()).hexdigest()


def test_write_context_file_requires_full_text_for_full_and_stripped(tmp_path: Path):
    config = _config(tmp_path, arm="T")
    config.site_root.mkdir(parents=True)
    with pytest.raises(ValueError):
        runner.write_context_file(config, variant="full")


def test_setup_arm_c0_removes_context_and_does_not_touch_shim(tmp_path: Path, monkeypatch):
    config = _config(tmp_path, arm="C0")
    config.site_root.mkdir(parents=True)
    installed = {"called": False}
    monkeypatch.setattr(runner, "install_c1_shim", lambda *a, **k: installed.__setitem__("called", True))
    result = runner.setup_arm(config)
    assert result is None
    assert installed["called"] is False


def test_setup_arm_c1_installs_shim(tmp_path: Path, monkeypatch):
    config = _config(tmp_path, arm="C1")
    config.site_root.mkdir(parents=True)
    calls = []
    monkeypatch.setattr(runner, "install_c1_shim", lambda *a, **k: calls.append(True))
    runner.setup_arm(config)
    assert calls == [True]


def test_assert_no_stray_mcp_config(tmp_path: Path):
    config = _config(tmp_path, arm="C1")
    config.site_root.mkdir(parents=True)
    assert runner.assert_no_stray_mcp_config(config).ok is True
    (config.site_root / ".mcp.json").write_text("{}")
    assert runner.assert_no_stray_mcp_config(config).ok is False


def test_assert_no_stray_mcp_config_arm_t_allows_it(tmp_path: Path):
    config = _config(tmp_path, arm="T")
    config.site_root.mkdir(parents=True)
    (config.site_root / ".mcp.json").write_text("{}")
    assert runner.assert_no_stray_mcp_config(config).ok is True


def test_assert_context_hash_none_variant(tmp_path: Path):
    config = _config(tmp_path, arm="C0")
    config.site_root.mkdir(parents=True)
    assert runner.assert_context_hash(config, None).ok is True
    (config.site_root / "CLAUDE.md").write_text("x")
    assert runner.assert_context_hash(config, None).ok is False


def test_assert_context_hash_matches(tmp_path: Path):
    config = _config(tmp_path, arm="T")
    config.site_root.mkdir(parents=True)
    text = "hello"
    (config.site_root / "CLAUDE.md").write_text(text)
    import hashlib
    good_hash = hashlib.sha256(text.encode()).hexdigest()
    assert runner.assert_context_hash(config, good_hash).ok is True
    assert runner.assert_context_hash(config, "0" * 64).ok is False


def test_assert_mcp_tools_list_count_is_a_seam_for_arm_t(tmp_path: Path):
    config = _config(tmp_path, arm="T")
    result = runner.assert_mcp_tools_list_count(config)
    assert result.ok is False
    assert "SEAM" in result.reason


def test_assert_mcp_tools_list_count_not_applicable_other_arms(tmp_path: Path):
    for arm in ("C0", "C1", "C1-ctx"):
        config = _config(tmp_path, arm=arm)
        assert runner.assert_mcp_tools_list_count(config).ok is True


def test_assert_egress_blocked_true_when_connection_refused():
    result = runner.assert_egress_blocked(probe_url="http://127.0.0.1:1/", timeout_seconds=2)
    assert result.ok is True


def test_assert_egress_blocked_false_when_a_fake_curl_succeeds(tmp_path: Path, monkeypatch):
    fake_curl = tmp_path / "curl"
    fake_curl.write_text("#!/bin/sh\nexit 0\n")
    fake_curl.chmod(fake_curl.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    result = runner.assert_egress_blocked(probe_url="http://example.invalid/", timeout_seconds=2)
    assert result.ok is False


def test_assert_shim_ok_not_applicable_for_t_and_c0(tmp_path: Path):
    for arm in ("T", "C0"):
        config = _config(tmp_path, arm=arm)
        assert runner.assert_shim_ok(config).ok is True


def test_assert_shim_ok_with_a_working_fake_shim(tmp_path: Path):
    config = _config(tmp_path, arm="C1")
    config.site_root.mkdir(parents=True)
    fake_wp = tmp_path / "fake-wp"
    fake_wp.write_text("#!/bin/sh\necho 6.5\n")
    fake_wp.chmod(fake_wp.stat().st_mode | stat.S_IEXEC)
    result = runner.assert_shim_ok(config, wp_binary=str(fake_wp))
    assert result.ok is True


def test_assert_shim_ok_with_a_failing_shim(tmp_path: Path):
    config = _config(tmp_path, arm="C1")
    config.site_root.mkdir(parents=True)
    fake_wp = tmp_path / "fake-wp"
    fake_wp.write_text("#!/bin/sh\nexit 1\n")
    fake_wp.chmod(fake_wp.stat().st_mode | stat.S_IEXEC)
    result = runner.assert_shim_ok(config, wp_binary=str(fake_wp))
    assert result.ok is False


def test_build_agent_command_identical_bytes_except_mcp_config(tmp_path: Path):
    config_t = _config(tmp_path, arm="T")
    config_c0 = _config(tmp_path, arm="C0")
    cmd_t = runner.build_agent_command(config_t, prompt="fix the bug", mcp_config_path=tmp_path / "T.mcp.json")
    cmd_c0 = runner.build_agent_command(config_c0, prompt="fix the bug", mcp_config_path=tmp_path / "C0.mcp.json")
    mcp_index = cmd_t.index("--mcp-config") + 1
    stripped_t = cmd_t[:mcp_index] + cmd_t[mcp_index + 1:]
    stripped_c0 = cmd_c0[:mcp_index] + cmd_c0[mcp_index + 1:]
    assert stripped_t == stripped_c0
    assert cmd_t[mcp_index] != cmd_c0[mcp_index]


def test_build_agent_command_contains_required_flags(tmp_path: Path):
    config = _config(tmp_path, arm="C1")
    cmd = runner.build_agent_command(config, prompt="hello", mcp_config_path=tmp_path / "x.json")
    assert cmd[0:3] == ["claude", "-p", "hello"]
    assert "--max-turns" in cmd and cmd[cmd.index("--max-turns") + 1] == "60"
    assert "--permission-mode" in cmd and cmd[cmd.index("--permission-mode") + 1] == "bypassPermissions"
    assert "--strict-mcp-config" in cmd


def test_build_mcp_config_shape_matches_the_forks_buildMcpServerEntry(): # noqa: N802
    config = runner.build_mcp_config(port=24842, site_id="acme-site", token="tok-abc")
    entry = config["mcpServers"]["local-wp"]
    assert entry["type"] == "http"
    assert entry["url"] == "http://localhost:24842/sites/acme-site/mcp?token=tok-abc"
    assert entry["headers"] == {"Authorization": "Bearer tok-abc"}


def test_build_mcp_config_url_encodes_the_token():
    config = runner.build_mcp_config(port=1, site_id="s", token="a b/c")
    assert "token=a%20b%2Fc" in config["mcpServers"]["local-wp"]["url"]


def test_write_mcp_config_writes_into_site_root(tmp_path: Path):
    config = _config(tmp_path, arm="T")
    config.site_root.mkdir(parents=True)
    path = runner.write_mcp_config(config, port=1, site_id="s", token="t")
    assert path == config.site_root / ".mcp.json"
    assert json.loads(path.read_text())["mcpServers"]["local-wp"]["type"] == "http"


def _fake_claude_script(tmp_path: Path, *, body: str) -> Path:
    script = tmp_path / "fake_claude.sh"
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_invoke_agent_runs_the_command_and_writes_a_redacted_transcript(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _config(tmp_path, arm="T")
    config.site_root.mkdir(parents=True)  # bounded_subprocess needs a real cwd
    fake_claude = _fake_claude_script(tmp_path, body='echo \'{"type":"result","token_seen":"tok-secret-1"}\'')
    monkeypatch.setattr(runner, "build_agent_command", lambda cfg, *, prompt, mcp_config_path: [str(fake_claude)])

    result = runner.invoke_agent(
        config, prompt="x", mcp_config_path=tmp_path / "x.json", redact_tokens=("tok-secret-1",),
    )

    assert result["outcome"] == "ran"
    assert result["wall_cap_hit"] is False
    assert result["returncode"] == 0
    transcript = Path(result["transcript_path"]).read_text()
    assert "tok-secret-1" not in transcript
    assert "<REDACTED>" in transcript
    assert Path(result["transcript_path"]) == config.run_dir / "transcript.jsonl"


def test_invoke_agent_wall_cap_kill_is_classed_error_wall_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _config(tmp_path, arm="T")
    config.site_root.mkdir(parents=True)  # bounded_subprocess needs a real cwd
    config = replace(config, wall_clock_safety_cap_minutes=0.02)  # ~1.2s — plenty for a fast kill in a test
    fake_claude = _fake_claude_script(tmp_path, body="sleep 30")
    monkeypatch.setattr(runner, "build_agent_command", lambda cfg, *, prompt, mcp_config_path: [str(fake_claude)])

    result = runner.invoke_agent(config, prompt="x", mcp_config_path=tmp_path / "x.json")

    assert result["outcome"] == "error:wall_cap"
    assert result["wall_cap_hit"] is True
    assert result["returncode"] is None
    # Documented limitation (invoke_agent's own docstring): bounded_subprocess
    # discards buffered stdout on a timeout, so the archived transcript is
    # empty here, not partial.
    assert Path(result["transcript_path"]).read_text() == ""


def test_assert_mcp_tools_list_count_real_check_against_a_fake_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Exercises the real (non-seam) branch: given server details, it
    actually calls out via tool_value_parity's MCP client — faked at the
    network layer only, same style as test_tool_value_parity.py's fakes."""
    import tool_value_parity as parity

    def fake_urlopen(request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        if payload["method"] == "initialize":
            result: object = {"protocolVersion": "2024-11-05"}
        else:
            result = {"tools": list(range(13))}
        body = json.dumps({"jsonrpc": "2.0", "id": payload["id"], "result": result}).encode("utf-8")

        class _Resp:
            headers = {"mcp-session-id": "sess-1"}

            def read(self_inner):
                return body

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

        return _Resp()

    monkeypatch.setattr(parity.urllib.request, "urlopen", fake_urlopen)
    config = _config(tmp_path, arm="T")
    result = runner.assert_mcp_tools_list_count(
        config, mcp_base_url="http://127.0.0.1:1/sites/s/mcp", mcp_token="tok",
    )
    assert result.ok is True


def test_post_agent_log_offset_reads_current_size(tmp_path: Path):
    config = _config(tmp_path)
    log_path = config.site_dir / "logs" / "php" / "error.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("12345")
    assert runner.post_agent_log_offset(config) == 5


def test_post_agent_log_offset_missing_file_is_zero(tmp_path: Path):
    config = _config(tmp_path)
    assert runner.post_agent_log_offset(config) == 0


def test_build_grading_json_schema_shape(tmp_path: Path):
    config = _config(tmp_path, arm="T", rep=3)
    config.run_dir.mkdir(parents=True)
    prechecks = {"no_stray_mcp_config": runner.PrecheckResult(True), "egress_blocked": runner.PrecheckResult(True)}
    payload = runner.build_grading_json(
        config=config, prompt_sha256="a" * 64, golden_digest="b" * 64, seed_digest="c" * 64,
        php_ini_digest="d" * 64, context_variant="full", context_sha256="e" * 64,
        claude_version="2.1.259", image_digest="sha256:f" * 8, prechecks=prechecks,
        pre_oracle="fail", outcome="pass",
        oracle_payload={"checks": {"symptom_resolved": True}, "evidence": {}},
        log_offsets={"trigger": 100, "post_agent": 200}, secondary={"turns": 14},
    )
    assert payload["schema"] == runner.SCHEMA
    assert payload["fixture"] == FIXTURE_1_DIR.name
    assert payload["arm"] == "T"
    assert payload["rep"] == 3
    assert payload["prechecks"] == {"no_stray_mcp_config": True, "egress_blocked": True}
    assert payload["outcome"] == "pass"
    assert payload["checks"] == {"symptom_resolved": True}
    assert payload["fork_commit"] == runner.FORK_COMMIT


def test_write_grading_json_round_trips(tmp_path: Path):
    config = _config(tmp_path, arm="C1")
    payload = {"schema": runner.SCHEMA, "outcome": "pass"}
    path = runner.write_grading_json(config, payload)
    assert path.is_file()
    assert json.loads(path.read_text()) == payload
