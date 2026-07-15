#!/usr/bin/env python3
"""Unit tests for the pure orchestrate() core of run_executor_repair_loop.

Uses stub generate_fn / certify_fn so the loop logic is verified with no model
calls and no Docker — mirroring run_pairwise_pilot's injectable-callable pattern.
Run: python3 evals/harness/tests/test_executor_repair_loop.py  (or via pytest)
"""
from __future__ import annotations

import sys
import json
import copy
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))

import run_executor_repair_loop as loop  # noqa: E402
import isolated_runtime_contract  # noqa: E402
from wp_runtime_types import BlockRuntimeAssertion  # noqa: E402


def _stub_generate(record):
    def gen(iteration, prior, failures):
        record.append({"iteration": iteration, "prior": prior, "failures": failures})
        return f"packet-{iteration}"
    return gen


def _stub_certify(pass_at):
    """certify_fn that fails every iteration until `pass_at` (None = never passes)."""
    def cert(iteration, packet):
        if pass_at is not None and iteration >= pass_at:
            return {"passed": True, "gate_vector": {"plugin_check": "pass"}}
        return {
            "passed": False,
            "failing_gates": ["plugin_check"],
            "failures": f"F{iteration}",
            "gate_vector": {"plugin_check": "fail"},
        }
    return cert


def test_pass_at_1_zero_repairs_needed():
    rec = []
    res = loop.orchestrate(_stub_generate(rec), _stub_certify(pass_at=0), max_repairs=2)
    assert res["green"] is True
    assert res["iterations_to_green"] == 0
    assert res["pass_at_1"] is True
    assert res["generations"] == 1
    assert len(rec) == 1  # only the initial generation


def test_one_repair_then_green():
    rec = []
    res = loop.orchestrate(_stub_generate(rec), _stub_certify(pass_at=1), max_repairs=2)
    assert res["green"] is True
    assert res["iterations_to_green"] == 1
    assert res["pass_at_1"] is False
    assert res["generations"] == 2
    assert len(res["history"]) == 2


def test_two_repairs_then_green():
    res = loop.orchestrate(_stub_generate([]), _stub_certify(pass_at=2), max_repairs=2)
    assert res["green"] is True
    assert res["iterations_to_green"] == 2
    assert res["generations"] == 3


def test_never_green_within_bound():
    rec = []
    res = loop.orchestrate(_stub_generate(rec), _stub_certify(pass_at=None), max_repairs=2)
    assert res["green"] is False
    assert res["iterations_to_green"] is None
    assert res["generations"] == 3
    assert len(res["history"]) == 3
    # initial + exactly max_repairs regenerations
    assert len(rec) == 3


def test_failures_and_prior_fed_into_repair():
    rec = []
    loop.orchestrate(_stub_generate(rec), _stub_certify(pass_at=2), max_repairs=2)
    # iteration 0 gets no prior/failures; repairs get the prior packet + that iter's failure text
    assert rec[0] == {"iteration": 0, "prior": None, "failures": ""}
    assert rec[1] == {"iteration": 1, "prior": "packet-0", "failures": "F0"}
    assert rec[2] == {"iteration": 2, "prior": "packet-1", "failures": "F1"}


def test_max_repairs_zero_is_single_attempt():
    rec = []
    res = loop.orchestrate(_stub_generate(rec), _stub_certify(pass_at=None), max_repairs=0)
    assert res["green"] is False
    assert res["generations"] == 1
    assert len(rec) == 1  # no repair attempted


def test_negative_max_repairs_rejected():
    try:
        loop.orchestrate(_stub_generate([]), _stub_certify(pass_at=0), max_repairs=-1)
    except ValueError:
        return
    raise AssertionError("expected ValueError for negative max_repairs")


def test_failure_text_extracts_error_lines():
    checks = [
        {"id": "plugin_check", "status": "fail",
         "detail": "exit 0; stdout: FILE: x.php\\n0\\t0\\tERROR\\tplugin_header_no_license\\tMissing License\\n"},
        {"id": "wp_env_smoke", "status": "pass", "detail": "7.0"},
    ]
    text = loop._failure_text(checks)
    assert "plugin_check" in text
    assert "plugin_header_no_license" in text
    assert "wp_env_smoke" not in text  # passing gates are not reported


def test_checks_with_status_normalises_passed_and_status():
    data = {
        "checks": [
            {"id": "a", "passed": True},
            {"id": "b", "passed": False},
            {"nested": {"checks": [{"id": "c", "status": "fail", "detail": "boom"}]}},
        ]
    }
    got = {c["id"]: c["status"] for c in loop._checks_with_status(data)}
    assert got == {"a": "pass", "b": "fail", "c": "fail"}


def test_load_json_object_accepts_only_object(tmp_path):
    result = tmp_path / "result.json"
    result.write_text('{"status":"pass"}', encoding="utf-8")
    assert loop._load_json_object(result) == {"status": "pass"}
    result.write_text('[]', encoding="utf-8")
    assert loop._load_json_object(result) is None


def test_load_json_object_rejects_missing_empty_and_malformed(tmp_path):
    result = tmp_path / "result.json"
    assert loop._load_json_object(result) is None
    result.write_text('', encoding="utf-8")
    assert loop._load_json_object(result) is None
    result.write_text('{', encoding="utf-8")
    assert loop._load_json_object(result) is None


def test_stage_failure_preserves_fail_and_blocked_gates():
    result = loop._stage_failure("runtime_status", "blocked", [
        {"id": "plugin_check", "status": "fail", "detail": "ERROR broken"},
        {"id": "wp_env_smoke", "status": "blocked", "detail": "tool missing"},
        {"id": "other", "status": "pass", "detail": "ok"},
    ])
    assert result["failing_gates"] == ["runtime_status"]
    assert result["gate_vector"] == {"runtime_status": {"status": "fail", "checks": [
        {"id": "plugin_check", "status": "fail"}, {"id": "wp_env_smoke", "status": "blocked"}
    ]}}
    assert "plugin_check" in result["failures"] and "wp_env_smoke" in result["failures"]
    assert "other" not in result["failures"]


def test_stage_failure_names_command_return_code():
    result = loop._stage_failure("runtime_command", "return code 2")
    assert result["failing_gates"] == ["runtime_command"]
    assert "return code 2" in result["failures"]


def test_stage_failure_sanitizes_and_bounds_subordinate_diagnostics():
    checks = [{"id": "bad id/../../", "status": "blocked",
               "detail": "ERROR /private/client/file.php token=supersecret " + "x" * 2000} for _ in range(40)]
    result = loop._stage_failure("runtime_status", "blocked", checks)
    assert result["failing_gates"] == ["runtime_status"]
    assert "supersecret" not in result["failures"]
    assert "/private/client" not in result["failures"]
    assert "bad_id_.._.._" in result["failures"]
    assert len(result["failures"].encode()) <= 12_100


def test_contradictory_enclosing_pass_cannot_hide_blocked_or_failed_checks():
    checks = [{"id": "ok", "status": "pass"}, {"id": "blocked", "status": "blocked"},
              {"id": "failed", "status": "fail"}]
    assert loop._nonpassing_check_ids(checks) == ["blocked", "failed"]


def test_repair_runtime_contract_rejects_legacy_profile_without_isolated_oracles():
    data = {
            "schema_version": 1, "run_id": "run", "evidence_id": "evidence",
            "artifact_kind": "plugin", "input_artifact_digest": "a" * 64,
            "runtime_profile_id": isolated_runtime_contract.STANDARD_PROFILE,
            "runtime_pre_command_manifest_digest": "b" * 64,
        "post_command_manifest_digest": "b" * 64,
        "status": "pass", "pass": True,
        "full_plugin_runtime_profile": {"status": "pass", "checks": [
            {"id": "plugin_check", "status": "pass"},
            {"id": "wp_env_smoke", "status": "pass"},
        ]},
        "checks": [],
    }
    errors = isolated_runtime_contract.persisted_runtime_errors(
        data, run_id="run", evidence_id="evidence",
        artifact_kind="plugin", input_digest="a" * 64,
        expected_profile=isolated_runtime_contract.STANDARD_PROFILE,
    )
    assert {
        "wp_cli_activation did not pass", "plugin_check did not pass",
        "container_browser did not pass", "runtime_identity did not pass",
        "runtime check timing evidence invalid", "full plugin runtime profile did not pass",
        "runtime topology inspection inventory mismatch", "runtime cleanup inventory mismatch",
        "artifact retention cleanup did not converge", "sandbox posture did not pass",
        "strict full profile was not requested",
    } <= set(errors)


def test_repair_runtime_command_uses_exact_isolated_contract_only(tmp_path):
    adapter = loop.runtime_adapter("plugin", "runtime")
    command = loop._isolated_runtime_command(
        adapter, tmp_path / "plugin", tmp_path / "results", "run", "evidence",
        "a" * 64, 300,
    )
    assert "--provision-full-profile" in command and "--strict-full-profile" in command
    assert command[command.index("--evidence-id") + 1] == "evidence"
    assert command[command.index("--expected-artifact-digest") + 1] == "a" * 64
    assert command[command.index("--results-root") + 1] == str(tmp_path / "results")


def test_runtime_parent_preserves_child_cleanup_budget(monkeypatch):
    timeout = 300
    expected = (timeout * 2) + 180 + 30
    observed = []

    def expire(_command, **kwargs):
        observed.append(kwargs["timeout"])
        raise loop.subprocess.TimeoutExpired(["runtime"], kwargs["timeout"])

    monkeypatch.setattr(loop.subprocess, "run", expire)
    process, detail = loop._run_isolated_runtime_process(["runtime"], timeout)
    assert process is None and observed == [expected]
    assert str(expected) in detail and "cleanup" in detail


def _block_assertion():
    return BlockRuntimeAssertion(
        "acme/runtime-card", ".wp-block-acme-runtime-card", "Exact runtime card text"
    )


def test_executor_profile_matrix_is_exact_and_immutable():
    assert loop.EXECUTOR_PROFILE_MATRIX == {
        "plugin": {"static": "supported", "runtime": "supported"},
        "block": {"static": "supported", "runtime": "conditional"},
        "blueprint": {"static": "supported", "runtime": "rejected"},
    }
    with pytest.raises(TypeError):
        loop.EXECUTOR_PROFILE_MATRIX["plugin"] = {}


@pytest.mark.parametrize(
    ("executor", "profile", "assertion"),
    (
        ("plugin", "static", None), ("plugin", "runtime", None),
        ("block", "static", None), ("block", "runtime", _block_assertion()),
        ("blueprint", "static", None),
    ),
)
def test_supported_matrix_combinations(executor, profile, assertion):
    assert loop.validate_compatibility(executor, profile, assertion) is assertion


def test_conditional_and_rejected_runtime_are_direct_api_errors(tmp_path):
    with pytest.raises(ValueError, match="assertion"):
        loop.validate_compatibility("block", "runtime", None)
    with pytest.raises(ValueError, match="Blueprint runtime"):
        loop.validate_compatibility("blueprint", "runtime", None)
    with pytest.raises(ValueError, match="Blueprint runtime"):
        loop.make_certify("wordpress-blueprint-executor", "blueprint", tmp_path,
                          "runtime", 60)


def test_blueprint_runtime_cli_rejects_before_any_side_effect(monkeypatch):
    monkeypatch.setattr(
        loop, "create_named", lambda *_args, **_kwargs: pytest.fail("run directory created")
    )
    monkeypatch.setattr(
        loop, "make_generate", lambda *_args, **_kwargs: pytest.fail("provider preflight reached")
    )
    with pytest.raises(SystemExit) as raised:
        loop.main([
            "--suite", "wordpress-blueprint-executor", "--fixture", "smoke-wordpress-v1",
            "--executor", "blueprint", "--profile", "runtime", "--run-id", "rejected",
        ])
    assert raised.value.code == 2


def test_block_runtime_cli_loads_assertions_before_run_directory(monkeypatch, tmp_path):
    fixtures = tmp_path / "wordpress-block-executor" / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "card.md").write_text("card", encoding="utf-8")
    (fixtures / "card.metadata.yaml").write_text(
        "name: card\nsuite: wordpress-block-executor\n", encoding="utf-8"
    )
    monkeypatch.setattr(loop.invoke, "SUITES_ROOT", tmp_path)
    monkeypatch.setattr(
        loop, "create_named", lambda *_args, **_kwargs: pytest.fail("run directory created")
    )
    with pytest.raises(SystemExit) as raised:
        loop.main([
            "--suite", "wordpress-block-executor", "--fixture", "card",
            "--executor", "block", "--profile", "runtime", "--run-id", "rejected",
        ])
    assert raised.value.code == 2


def test_block_runtime_command_uses_named_adapter_and_exact_assertions(tmp_path):
    assertion = _block_assertion()
    adapter = loop.runtime_adapter("block", "runtime", assertion)
    command = loop._isolated_runtime_command(
        adapter, tmp_path / "block", tmp_path / "results", "run", "evidence",
        "a" * 64, 300, assertion,
    )
    assert command[command.index("--artifact-kind") + 1] == "block"
    assert "--block-build-smoke" in command
    assert "--editor-insert-render-smoke" in command
    assert command[command.index("--block-name") + 1] == assertion.block_name
    assert command[command.index("--expected-frontend-selector") + 1] == assertion.frontend_selector
    assert command[command.index("--expected-frontend-text") + 1] == assertion.expected_frontend_text


def test_materialized_block_name_must_equal_fixture_assertion(tmp_path):
    block = tmp_path / "block"
    block.mkdir()
    (block / "block.json").write_text(
        '{"name":"acme/runtime-card","title":"Card","category":"widgets"}',
        encoding="utf-8",
    )
    assert loop._materialized_block_name(block) == "acme/runtime-card"
    with pytest.raises(ValueError, match="does not match"):
        loop._require_materialized_block_name(block, BlockRuntimeAssertion(
            "acme/other", ".wp-block-acme-other", "Other"
        ))


def test_repair_runtime_verdict_requires_exact_isolated_checks():
    service_networks = {
        "database": ("backend",), "wordpress": ("backend", "application"),
        "cli": ("backend",), "gateway": ("application", "frontend"),
        "browser": ("frontend",),
    }
    services = {
        name: {"id": f"id-{name}", "image": f"sha256:{name}", "mounts": [],
               "networks": [f"project_{network}" for network in networks],
               "addresses": {f"project_{network}": "172.20.0.2" for network in networks},
               "seccomp": 2}
        for name, networks in service_networks.items()
    }
    created = copy.deepcopy(services)
    for service in created.values():
        service.pop("seccomp")
        service["addresses"] = {name: "" for name in service["networks"]}
    networks = {
        f"project_{network}": {
            "id": f"id-{network}", "internal": True,
            "members": sorted(service["id"] for name, service in services.items()
                              if network in service_networks[name]),
            "gateway": [], "gateway_mode": "isolated", "subnet": "172.20.0.0/24",
        }
        for network in ("backend", "application", "frontend")
    }
    data = {
        "schema_version": 1, "run_id": "run", "evidence_id": "evidence",
        "artifact_kind": "plugin", "input_artifact_digest": "a" * 64,
        "runtime_profile_id": isolated_runtime_contract.STANDARD_PROFILE,
        "runtime_pre_command_manifest_digest": "b" * 64,
        "post_command_manifest_digest": "b" * 64, "status": "pass", "pass": True,
        "checks": [
            {"id": "wp_cli_activation", "status": "pass", "duration_sec": 0.1},
            {"id": "plugin_check", "status": "pass", "duration_sec": 0.2},
            {"id": "container_browser", "status": "pass", "duration_sec": 0.3},
            {"id": "runtime_identity", "status": "pass"},
        ],
        "provision_full_profile": True, "strict_full_profile": True,
        "inspection": {
            "normalized": {"services": sorted(services),
                           "images": {name: value["image"] for name, value in services.items()},
                           "networks": ["application", "backend", "frontend"]},
            "created": {"services": created, "networks": {}, "require_running": False},
            "started": {"services": services, "networks": networks, "require_running": True},
            "post_oracle": {"services": copy.deepcopy(services),
                            "networks": copy.deepcopy(networks), "require_running": True},
            "artifact_seal": {"component": "runtime_artifact_image", "state": "sealed",
                              "seed_started": False, "seed_removed": True,
                              "artifact_mounts": 0, "base_image": "sha256:wordpress",
                              "derived_image": "sha256:derived"},
        },
        "cleanup": {
            "compose": {"component": "compose", "state": "removed", "errors": [],
                        "remaining": {"containers": [], "networks": [], "volumes": []},
                        "recovery": []},
            "images": {"component": "runtime_images", "state": "removed", "error": None,
                       "remaining": [], "recovery": []},
            "export": {"component": "runtime_artifact_image", "state": "released",
                       "error": None, "recovery": None},
            "workspace": {"component": "runtime_workspace", "state": "removed", "error": None},
        },
        "artifact_execution_retained": False,
        "artifact_retention": {"retained": False, "resources": [
            {"component": component, "state": "removed", "exists": False,
             "live": False, "resource_path": f"/tmp/{component}",
             "error": None, "recovery_path": None}
            for component in ("input_copy", "synthesized_runtime")
        ]},
        "sandbox_posture": {"host_fallback": False, "static_scan_root": "staged_copy",
                            "generated_execution": {"php": "pass", "browser": "pass"}},
        "full_plugin_runtime_profile": {"status": "pass", "pass": True, "checks": [
            {"id": "phpcs_wpcs", "status": "pass"},
            {"id": "plugin_check", "status": "pass"},
            {"id": "wp_env_smoke", "status": "pass"},
        ]},
    }
    adapter = loop.runtime_adapter("plugin", "runtime")
    verdict = loop._isolated_runtime_verdict(
        data, adapter=adapter, run_id="run", evidence_id="evidence",
        expected_digest="a" * 64,
    )
    assert verdict["passed"] is True
    data["post_command_manifest_digest"] = "c" * 64
    assert loop._isolated_runtime_verdict(
        data, adapter=adapter, run_id="run", evidence_id="evidence",
        expected_digest="a" * 64,
    )["failing_gates"] == ["runtime_result"]


# --- new-this-sweep coverage: warning-inclusive feedback + cross-market providers ---


def test_failure_text_includes_warnings():
    """Regression for the gemini-flash stall: WPCS fails on warnings, so the repair
    prompt must carry the specific WARNING lines, not just ERRORs. Feeding only
    ERROR lines (old behaviour) starved the model of the issues it had to fix."""
    checks = [{
        "id": "phpcs_wpcs", "status": "fail",
        "detail": (
            "FOUND 0 ERRORS AND 6 WARNINGS AFFECTING 6 LINES\n"
            " 62 | WARNING | Array double arrow not aligned correctly; expected 15 spaces\n"
            " 63 | WARNING | Inline comment must end in a full-stop"
        ),
    }]
    text = loop._failure_text(checks)
    assert "phpcs_wpcs" in text
    assert "Array double arrow not aligned" in text   # the actionable warning reaches the model
    assert "Inline comment must end" in text


def test_failure_text_skips_passing_and_handles_no_diag():
    checks = [
        {"id": "wp_env_smoke", "status": "pass", "detail": "7.0"},
        {"id": "mystery", "status": "fail", "detail": "opaque failure with no marker"},
    ]
    text = loop._failure_text(checks)
    assert "wp_env_smoke" not in text                 # passing gates omitted
    assert "mystery" in text and "opaque failure" in text  # falls back to raw detail


def test_strip_model_noise_removes_think_and_fences():
    assert loop._strip_model_noise("<think>reasoning</think>\n## Spec Conformance\nbody") == "## Spec Conformance\nbody"
    assert loop._strip_model_noise("<think>\nmulti\nline\n</think>\n\nX") == "X"
    assert loop._strip_model_noise("```markdown\n## Spec Conformance\nb\n```") == "## Spec Conformance\nb"
    assert loop._strip_model_noise("## already clean\nbody") == "## already clean\nbody"


def test_run_provider_rejects_unknown():
    try:
        loop._run_provider("nonsense", "prompt", None, None, 5)
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown provider")


def test_run_gemini_without_key_is_graceful():
    """No network: the key check returns early, so this is a pure-logic test."""
    import os
    saved = {k: os.environ.pop(k, None) for k in ("GOOGLE_API_KEY", "GEMINI_API_KEY")}
    try:
        rc, out, err = loop._run_gemini("prompt", "gemini-2.5-flash", 5)
        assert rc == 127 and out == ""
        assert "API_KEY" in err
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_provider_lane_assembles_persona_fixture_and_repair_feedback():
    """The cross-market provider lane must put persona+fixture in iter0 and the gate
    failures + prior packet in repair iterations — verified without any model call."""
    import tempfile

    captured: list[tuple[str, str]] = []
    original = loop._run_provider
    loop._run_provider = lambda provider, prompt, model, effort, timeout: (
        captured.append((provider, prompt)) or (0, "## Spec Conformance\nstub-packet", "")
    )
    try:
        gen = loop.make_generate(
            "wordpress-plugin-executor", "abilities-ai-surface-v1", "skill",
            Path(tempfile.mkdtemp()), None, None, 10, provider="ollama",
        )
        p0 = gen(0, None, "")
        gen(1, p0, "- phpcs_wpcs:\n    WARNING array alignment")
    finally:
        loop._run_provider = original

    assert captured[0][0] == "ollama"                       # routed to the explicit provider
    assert "Output Requirements" in captured[0][1]          # fixture content present
    persona_path = loop.invoke.agent_prompt_path("wordpress-plugin-executor")
    if persona_path:
        first_line = persona_path.read_text(encoding="utf-8").strip().splitlines()[0][:25]
        assert first_line in captured[0][1]                 # persona prepended
    assert "WARNING array alignment" in captured[1][1]      # repair feedback fed back
    assert "stub-packet" in captured[1][1]                  # prior packet included


# --- generation-resilience coverage: timeouts must not discard the last-good packet ---


def _stub_generate_flaky(fail_counts, record=None):
    """generate_fn that returns None (failed/empty generation) for the first
    fail_counts[iteration] attempts of each iteration, then a packet token. Models
    transient model timeouts so the retry / preserve-last-good logic is testable."""
    attempts: dict[int, int] = {}

    def gen(iteration, prior, failures):
        if record is not None:
            record.append({"iteration": iteration, "prior": prior, "failures": failures})
        n = attempts.get(iteration, 0)
        attempts[iteration] = n + 1
        if n < fail_counts.get(iteration, 0):
            return None
        return f"packet-{iteration}"

    return gen


def test_generation_retry_recovers_transient_failure():
    """A generation that fails once then succeeds recovers within the slot via gen_retries,
    and is not counted as a generation failure."""
    rec = []
    res = loop.orchestrate(_stub_generate_flaky({0: 1}, rec), _stub_certify(pass_at=0),
                           max_repairs=2, gen_retries=1)
    assert res["green"] is True
    assert res["pass_at_1"] is True
    assert res["generation_failures"] == 0
    assert len([r for r in rec if r["iteration"] == 0]) == 2  # one failure + one success


def test_transient_repair_failure_preserves_last_good_packet():
    """A failed repair generation must NOT overwrite the last-good packet, and the next
    repair must be fed the last-good packet (not an empty/None one)."""
    rec = []
    # iter1 fails on every attempt (> gen_retries); iter2 succeeds and certifies green
    res = loop.orchestrate(_stub_generate_flaky({1: 99}, rec), _stub_certify(pass_at=2),
                           max_repairs=3, gen_retries=1)
    assert res["green"] is True
    assert res["iterations_to_green"] == 2
    assert res["generation_failures"] == 1
    iter2 = [r for r in rec if r["iteration"] == 2]
    assert iter2 and iter2[0]["prior"] == "packet-0"  # repaired from last-good, not empty
    assert any(h.get("generation_failed") and h["iteration"] == 1 for h in res["history"])


def test_initial_generation_failure_is_graceful():
    res = loop.orchestrate(_stub_generate_flaky({0: 99}), _stub_certify(pass_at=0),
                           max_repairs=2, gen_retries=1)
    assert res["green"] is False
    assert res["generations"] == 0
    assert res["generation_failures"] == 1
    assert res["pass_at_1"] is False


def test_repeated_generation_failures_report_best_certified_state():
    """Even if every repair generation fails, the loop reports the real iter0 verdict
    (progress), not an empty all-fail produced by a timeout."""
    res = loop.orchestrate(_stub_generate_flaky({1: 99, 2: 99, 3: 99}),
                           _stub_certify(pass_at=None), max_repairs=3, gen_retries=1)
    assert res["green"] is False
    assert res["generations"] == 1          # only iter0 was certified
    assert res["generation_failures"] == 3  # three repair slots failed to generate
    certified = [h for h in res["history"] if not h.get("generation_failed")]
    assert certified[0]["failing_gates"] == ["plugin_check"]  # real verdict preserved


def test_negative_gen_retries_rejected():
    try:
        loop.orchestrate(_stub_generate([]), _stub_certify(pass_at=0), max_repairs=1, gen_retries=-1)
    except ValueError:
        return
    raise AssertionError("expected ValueError for negative gen_retries")


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
