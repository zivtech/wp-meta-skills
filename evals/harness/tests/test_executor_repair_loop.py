#!/usr/bin/env python3
"""Unit tests for the pure orchestrate() core of run_executor_repair_loop.

Uses stub generate_fn / certify_fn so the loop logic is verified with no model
calls and no Docker — mirroring run_pairwise_pilot's injectable-callable pattern.
Run: python3 evals/harness/tests/test_executor_repair_loop.py  (or via pytest)
"""
from __future__ import annotations

import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))

import run_executor_repair_loop as loop  # noqa: E402


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
