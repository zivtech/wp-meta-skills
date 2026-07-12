#!/usr/bin/env python3
"""Automated executor repair loop: generate -> certify -> (repair -> regenerate -> re-certify)* until green or k.

The deterministic gate (Plugin Check / WPCS / wp-env activation) emits machine-readable
failures; this loop feeds those failures back to the model and re-certifies, up to a bound.
The 2026-06-22 gate-pass experiment showed this loop is the model-agnostic lever (it took
both a gpt-5.5 baseline and a sonnet+skill packet from fail -> green in one iteration), so
this turns that manual handoff into a standing capability.

Design mirrors run_pairwise_pilot.py: the core `orchestrate(generate_fn, certify_fn, ...)`
takes injectable callables and is fully unit-tested with stubs
(tests/test_executor_repair_loop.py). `main()` wires the real single-shot generation
(invoke.py: claude for skill lanes, codex for baseline-* lanes) and the real gate
(certify_wordpress_executor_artifact.py static + run_wordpress_runtime_smoke.py runtime).

Internal-only measurement harness. It reports pass@1, pass@k-with-repair, iterations-to-green,
and per-iteration gate vectors. It makes no skill-superiority claim. Failed generations (model
timeouts / empty output) are retried and never discard the last-good packet.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import stat
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent.parent
HARNESS = ROOT / "evals" / "harness"
RESULTS = ROOT / "evals" / "results"
sys.path.insert(0, str(HARNESS))

import invoke  # noqa: E402  (reuse single-shot generation + provider routing)
from certify_wordpress_executor_artifact import digest_regular_tree  # noqa: E402
from workspace_lease import WorkspacePurpose, create_named  # noqa: E402

# Type aliases for the injectable callables.
#   generate_fn(iteration, prior_packet, failures) -> packet token (opaque), or None on a
#       failed/empty generation (model timeout) so orchestrate can retry / preserve last-good
#   certify_fn(iteration, packet) -> {"passed": bool, "failing_gates": [...],
#                                     "failures": str, "gate_vector": {...}}
GenerateFn = Callable[[int, Any, str], Any]
CertifyFn = Callable[[int, Any], dict[str, Any]]


# ---------------------------------------------------------------------------
# Pure orchestration (unit-tested with stubs — no I/O, no model, no Docker)
# ---------------------------------------------------------------------------


def _generate_nonempty(generate_fn: GenerateFn, iteration: int, prior: Any,
                       failures: str, retries: int) -> Any:
    """Call generate_fn, retrying transient failed generations.

    generate_fn returns None when a generation produced empty output (model timeout,
    empty API response). Such a failure is retried up to `retries` times. Returns the
    packet token, or None if every attempt produced an empty generation.
    """
    for _ in range(retries + 1):
        result = generate_fn(iteration, prior, failures)
        if result is not None:
            return result
    return None


def orchestrate(generate_fn: GenerateFn, certify_fn: CertifyFn, max_repairs: int,
                gen_retries: int = 1) -> dict[str, Any]:
    """Run generate -> certify -> repair loop until a green certification or max_repairs.

    iteration 0 is the initial generation; iterations 1..max_repairs are repairs driven
    by the previous certification's machine-readable failures. Returns a structured result
    with pass@1 (green at iteration 0), pass@k (green within the bound), iterations_to_green,
    and the per-iteration history.

    Generation resilience: generate_fn returns None on an empty/timed-out generation.
    Such failures are retried (gen_retries) and, if still empty, NEVER overwrite the
    last-good packet — the loop records a generation_failed iteration and keeps repairing
    from the last-good base. A transient model timeout therefore cannot discard accumulated
    progress or feed an empty "previous packet" into the next repair prompt.
    """
    if max_repairs < 0:
        raise ValueError("max_repairs must be >= 0")
    if gen_retries < 0:
        raise ValueError("gen_retries must be >= 0")

    history: list[dict[str, Any]] = []
    gen_failures = 0

    def _record(iteration: int, verdict: dict[str, Any]) -> bool:
        passed = bool(verdict.get("passed"))
        history.append({
            "iteration": iteration,
            "passed": passed,
            "failing_gates": list(verdict.get("failing_gates") or []),
            "gate_vector": dict(verdict.get("gate_vector") or {}),
        })
        return passed

    def _record_gen_failure(iteration: int) -> None:
        nonlocal gen_failures
        gen_failures += 1
        history.append({
            "iteration": iteration,
            "passed": False,
            "generation_failed": True,
            "failing_gates": ["generation_failed"],
            "gate_vector": {},
        })

    def _result(green: bool, iters_to_green: int | None) -> dict[str, Any]:
        certified = [h for h in history if not h.get("generation_failed")]
        return {
            "green": green,
            "iterations_to_green": iters_to_green,
            "generations": len(certified),
            "generation_failures": gen_failures,
            "pass_at_1": bool(certified and certified[0]["passed"]
                              and certified[0]["iteration"] == 0),
            "history": history,
        }

    packet = _generate_nonempty(generate_fn, 0, None, "", gen_retries)
    if packet is None:
        _record_gen_failure(0)
        return _result(False, None)

    verdict = certify_fn(0, packet)
    if _record(0, verdict):
        return _result(True, 0)

    slot = 1
    while slot <= max_repairs:
        failures = str(verdict.get("failures") or "")
        new_packet = _generate_nonempty(generate_fn, slot, packet, failures, gen_retries)
        if new_packet is None:
            # Preserve the last-good packet and verdict; record the miss and keep going,
            # so the next repair slot still works from real progress, not an empty packet.
            _record_gen_failure(slot)
            slot += 1
            continue
        packet = new_packet
        verdict = certify_fn(slot, packet)
        if _record(slot, verdict):
            return _result(True, slot)
        slot += 1

    return _result(False, None)


# ---------------------------------------------------------------------------
# Result parsing helpers (shared by the real certify_fn)
# ---------------------------------------------------------------------------


def _walk_objects(obj: Any):
    """Yield every dict in a nested JSON structure (recursive descent)."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_objects(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_objects(v)


def _checks_with_status(data: Any) -> list[dict[str, Any]]:
    """Flatten all {id, status|passed} check objects, normalising to status strings."""
    seen: dict[str, dict[str, Any]] = {}
    for node in _walk_objects(data):
        if "id" not in node:
            continue
        if "status" in node:
            status = node["status"]
        elif "passed" in node:
            status = "pass" if node["passed"] else "fail"
        else:
            continue
        cid = str(node["id"])
        # Prefer a failing record if the same id appears twice.
        if cid not in seen or status == "fail":
            seen[cid] = {"id": cid, "status": status, "detail": str(node.get("detail", ""))}
    return list(seen.values())


def _failure_text(checks: list[dict[str, Any]]) -> str:
    """Build a model-readable failure summary from failing checks.

    Includes both ERROR and WARNING diagnostic lines. Gates such as phpcs_wpcs
    fail on warnings, so extracting only ERROR lines (the earlier behaviour)
    starved the repair prompt of the exact issues the model had to fix — a model
    that produced WPCS warnings could never converge because it was never told
    which warnings. Strong models hit 0 warnings, which hid the gap.
    """
    lines: list[str] = []
    total = 0
    for c in checks[:20]:
        if c["status"] not in {"fail", "blocked"}:
            continue
        check_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(c.get("id", "check")))[:80]
        detail = str(c.get("detail", "")).replace("\\n", "\n")
        detail = re.sub(r"(?i)\b(api[_-]?key|token|password|secret|authorization)\b\s*[:=]\s*\S+", r"\1=[REDACTED]", detail)
        detail = re.sub(r"(?<![A-Za-z0-9_.-])/(?:[^\s/:]+/)+[^\s:]+", "[PATH]", detail)
        diag = [ln.strip() for ln in detail.splitlines()
                if ln.strip() and ("ERROR" in ln or "WARNING" in ln)]
        lines.append(f"- {check_id} ({c['status']}):")
        if diag:
            selected = diag[:10]
        else:
            selected = [detail[:500]]
        for item in selected:
            line = f"    {item[:500]}"
            if total + len(line.encode()) > 12_000:
                return "\n".join(lines + ["    [diagnostics truncated]"])
            lines.append(line)
            total += len(line.encode())
    return "\n".join(lines) if lines else "(gate failed without itemised detail)"


def _load_json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _nonpassing_check_ids(checks: list[dict[str, Any]]) -> list[str]:
    return [str(check.get("id", "check")) for check in checks
            if check.get("status") in {"fail", "blocked"}]


def _stage_failure(gate: str, detail: str, checks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    relevant = [c for c in (checks or []) if c.get("status") in {"fail", "blocked"}]
    diagnostics = _failure_text(relevant or [{"id": gate, "status": "fail", "detail": detail}])
    subordinate: list[dict[str, str]] = []
    seen: dict[str, int] = {}
    for check in relevant[:20]:
        base = re.sub(r"[^A-Za-z0-9_.-]", "_", str(check.get("id", "check")))[:80] or "check"
        seen[base] = seen.get(base, 0) + 1
        identifier = base if seen[base] == 1 else f"{base[:72]}-{seen[base]}"
        subordinate.append({"id": identifier, "status": str(check.get("status"))})
    return {"passed": False, "failing_gates": [gate], "failures": diagnostics,
            "gate_vector": {gate: {"status": "fail", "checks": subordinate}}}


# ---------------------------------------------------------------------------
# Cross-market generation providers (the dev-tool point: run on the models a WP
# dev actually has — local ollama, gemini flash, low-effort codex, haiku — not
# just frontier APIs). invoke.py covers claude/codex; these add the rest.
# ---------------------------------------------------------------------------


def _strip_model_noise(text: str) -> str:
    """Remove <think> reasoning blocks and a single wrapping code fence."""
    import re

    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _safe_subprocess(cmd: list[str], prompt: str, timeout: int) -> tuple[int, str, str]:
    """Run a generation CLI tolerantly: a timeout or missing CLI becomes a graceful
    failure (the loop records it and can repair/continue) instead of crashing.
    Slow local models make timeouts a normal event, not an exception."""
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, _strip_model_noise(proc.stdout or ""), proc.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"generation timed out after {timeout}s ({cmd[0]})"
    except FileNotFoundError as exc:
        return 127, "", f"CLI not found: {exc}"


def _run_ollama(prompt: str, model: str | None, timeout: int) -> tuple[int, str, str]:
    """Generate via the ollama HTTP API with an explicit large context window.

    `ollama run` defaults to num_ctx=4096, which truncates the persona+fixture prompt
    and leaves no room for a full materializable packet — the cause of the earlier
    "local truncation" (incomplete ~1.8KB packets). Driving the API directly lets us
    set num_ctx (default 32768; override via OLLAMA_NUM_CTX) so complete packets fit.
    """
    import os

    num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))
    payload = json.dumps({
        "model": model or "qwen2.5-coder:32b-instruct-q8_0",
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": num_ctx, "temperature": 0.2},
    })
    try:
        proc = subprocess.run(
            ["curl", "-sS", "-X", "POST", "http://localhost:11434/api/generate",
             "-H", "Content-Type: application/json", "--data-binary", "@-"],
            input=payload, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"ollama request timed out after {timeout}s (num_ctx={num_ctx})"
    if proc.returncode != 0:
        return proc.returncode, "", (proc.stderr or "curl failed")[:300]
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return 1, "", "non-JSON ollama response: " + (proc.stdout or "")[:200]
    text = data.get("response", "")
    if not text.strip():
        return 1, "", f"empty ollama response (done_reason={data.get('done_reason')})"
    return 0, _strip_model_noise(text), ""


def _run_gemini(prompt: str, model: str | None, timeout: int) -> tuple[int, str, str]:
    """Call the Gemini REST API directly with GOOGLE_API_KEY.

    The gemini-cli individual oauth tier is deprecated (-> Antigravity IDE), so the
    API key is the headless path. curl is used rather than urllib because the
    framework Python here fails TLS verification (CERTIFICATE_VERIFY_FAILED).
    Reads GOOGLE_API_KEY/GEMINI_API_KEY from env; the key is never logged.
    """
    import os

    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        return 127, "", "no GOOGLE_API_KEY / GEMINI_API_KEY in environment"
    m = model or "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 16384, "temperature": 0.2},
    })
    try:
        proc = subprocess.run(
            ["curl", "-sS", "-X", "POST", url, "-H", "Content-Type: application/json", "--data-binary", "@-"],
            input=payload, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"gemini request timed out after {timeout}s"
    if proc.returncode != 0:
        return proc.returncode, "", (proc.stderr or "curl failed")[:300]
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return 1, "", "non-JSON Gemini response: " + (proc.stdout or "")[:200]
    try:
        cand = data["candidates"][0]
        text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    except (KeyError, IndexError):
        return 1, "", "unexpected Gemini response: " + json.dumps(data)[:300]
    if not text.strip():
        return 1, "", f"empty Gemini text (finishReason={data.get('candidates', [{}])[0].get('finishReason')})"
    return 0, _strip_model_noise(text), ""


def _run_provider(provider: str, prompt: str, model: str | None, effort: str | None,
                  timeout: int) -> tuple[int, str, str]:
    if provider == "ollama":
        return _run_ollama(prompt, model, timeout)
    if provider == "gemini":
        return _run_gemini(prompt, model, timeout)
    if provider == "codex":
        rc, out, err, _dt = invoke._run_codex(prompt, timeout, 2, model=model, effort=effort)
        return rc, out, err
    if provider == "claude":
        rc, out, err, _dt = invoke._run_claude(prompt, None, timeout, 2, model=model, effort=effort)
        return rc, out, err
    raise ValueError(f"unknown provider: {provider}")


def _repair_body(failures: str, prior_text: str) -> str:
    return (
        "A WordPress release gate (Plugin Check / WPCS / wp-env activation) REJECTED your "
        "previous packet with these blocking issues. Fix ONLY these and re-emit the COMPLETE "
        "packet in the exact same format (first non-empty line must be '## Spec Conformance', "
        "same top-level headings in order, full materializable file contents, valid non-example.com "
        "URLs). Do not narrate.\n\n## Gate failures\n" + failures
        + "\n\n## Your previous packet\n\n" + prior_text
    )


# ---------------------------------------------------------------------------
# Real wiring: single-shot generation (invoke.py) + deterministic gate
# ---------------------------------------------------------------------------


def make_generate(suite: str, fixture: str, condition: str, run_dir: Path,
                  model: str | None, effort: str | None, timeout: int,
                  provider: str | None = None) -> GenerateFn:
    suite_dir = invoke.SUITES_ROOT / suite
    fixture_text = (suite_dir / "fixtures" / f"{fixture}.md").read_text(encoding="utf-8")
    settings = invoke.get_invocation_settings(suite)
    persona_path = invoke.agent_prompt_path(suite)
    persona = persona_path.read_text(encoding="utf-8").strip() if persona_path else ""

    if provider:
        # Cross-market lane: run the executor persona on an explicit cheap/local model
        # (ollama / gemini / low-effort codex / haiku) via the provider CLI directly.
        def generate(iteration: int, prior: Any, failures: str) -> Path:
            body = fixture_text if iteration == 0 else _repair_body(failures, Path(prior).read_text(encoding="utf-8"))
            prompt = (persona + "\n\n---\n\n" + body) if persona else body
            rc, out, err = _run_provider(provider, prompt, model, effort, timeout)
            pkt = run_dir / f"iter{iteration}.packet.md"
            pkt.write_text(out, encoding="utf-8")
            if not out.strip():
                (run_dir / f"iter{iteration}.generate.stderr.txt").write_text(err, encoding="utf-8")
                return None
            return pkt
        return generate

    # Default lane: invoke.py condition routing (claude skill / codex baseline-*).
    inv_provider, rmodel, reffort = invoke.resolve_invocation_runtime(settings, condition, model, effort)
    agent = suite if condition == "skill" else None
    baseline_prompt = ""
    if invoke.is_baseline_condition(condition):
        baseline_prompt = (suite_dir / "baselines" / f"{condition}.md").read_text(encoding="utf-8").strip()

    def generate(iteration: int, prior: Any, failures: str) -> Path:
        if iteration == 0:
            body = (
                fixture_text
                if condition == "skill"
                else baseline_prompt + "\n\n---\n\nUse this fixture:\n\n" + fixture_text.strip()
            )
        else:
            rb = _repair_body(failures, Path(prior).read_text(encoding="utf-8"))
            body = rb if condition == "skill" else baseline_prompt + "\n\n---\n\n" + rb
        rc, out, err, _dt = invoke._run_model(
            body, agent, timeout, 2, provider=inv_provider, model=rmodel, effort=reffort
        )
        pkt = run_dir / f"iter{iteration}.packet.md"
        pkt.write_text(out, encoding="utf-8")
        if not out.strip():
            (run_dir / f"iter{iteration}.generate.stderr.txt").write_text(err, encoding="utf-8")
            return None
        return pkt

    return generate


def make_certify(suite: str, executor: str, run_dir: Path, profile: str, timeout: int) -> CertifyFn:
    def certify(iteration: int, packet: Any) -> dict[str, Any]:
        try:
            art = create_named(run_dir, f"iter{iteration}.art", WorkspacePurpose.ARTIFACT_EXECUTION).root
            res = create_named(run_dir, f"iter{iteration}.cert", WorkspacePurpose.RESULT).root
        except FileExistsError:
            return _stage_failure("static_evidence", "iteration output already exists")
        evidence_id = f"{secrets.token_hex(16)}-iter{iteration}"
        packet_digest = hashlib.sha256(Path(packet).read_bytes()).hexdigest()

        # Stage A: static certify (packet contract + materialize + static heuristics).
        static_proc = subprocess.run(
            [sys.executable, str(HARNESS / "certify_wordpress_executor_artifact.py"),
             "--executor", executor, "--packet", str(packet), "--out-dir", str(art),
             "--result-dir", str(res), "--profile", "static", "--evidence-id", evidence_id],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        cert_json = res / "certification.json"
        static = _load_json_object(cert_json)
        if static_proc.returncode != 0:
            checks = _checks_with_status(static or {})
            checks.insert(0, {"id": "static_command", "status": "fail",
                              "detail": f"return code {static_proc.returncode}"})
            return _stage_failure("static_command", f"return code {static_proc.returncode}", checks)
        if static is None:
            return _stage_failure("static_evidence", "certification.json missing or malformed")
        candidates: list[Path] = []
        if executor == "plugin":
            candidates = [p for p in art.iterdir() if p.name != ".workspace-lease"]
            if (len(candidates) != 1 or stat.S_ISLNK(candidates[0].lstat().st_mode)
                    or not stat.S_ISDIR(candidates[0].lstat().st_mode)):
                return _stage_failure("static_evidence", "materialization did not produce exactly one plugin directory")
            artifact_path = candidates[0]
        elif executor == "blueprint":
            artifact_path = art / "blueprint.json"
        else:
            artifact_path = art
        try:
            observed_digest = digest_regular_tree(artifact_path)
        except (OSError, ValueError) as exc:
            return _stage_failure("static_evidence", f"artifact digest failed: {exc}")
        identity_ok = (
            static.get("schema_version") == 1 and static.get("evidence_id") == evidence_id
            and static.get("executor") == executor and static.get("profile") == "static"
            and static.get("packet_sha256") == packet_digest
            and static.get("artifact_digest") == observed_digest
        )
        if not identity_ok:
            return _stage_failure("static_evidence", "identity or digest mismatch")
        static_checks = _checks_with_status(static)
        static_failing = [c["id"] for c in static_checks if c["status"] == "fail"]
        if static.get("status") != "pass" or static.get("pass") is not True:
            repair_prompt = res / "repair-prompt.md"
            failures = repair_prompt.read_text(encoding="utf-8") if repair_prompt.exists() else _failure_text(static_checks)
            return {"passed": False, "failing_gates": static_failing or ["static_contract"],
                    "failures": failures, "gate_vector": {c["id"]: c["status"] for c in static_checks}}

        if profile == "static":
            return {"passed": True, "failing_gates": [], "failures": "",
                    "gate_vector": {c["id"]: c["status"] for c in static_checks}}

        if executor != "plugin":
            return _stage_failure("runtime_profile", "Plan 008 runtime profile supports plugin artifacts only")

        # Stage B: provisioned runtime gate (WPCS + Plugin Check + wp-env activation).
        runtime_artifact = candidates[0]
        expected_digest = digest_regular_tree(runtime_artifact)
        run_id = f"{run_dir.name}-iter{iteration}"
        runtime_root = res / "runtime"
        runtime_root.mkdir(exist_ok=False)
        runtime_proc = subprocess.run(
            [sys.executable, str(HARNESS / "run_wordpress_runtime_smoke.py"),
             "--artifact-path", str(runtime_artifact), "--artifact-kind", "plugin",
             "--provision-full-profile", "--strict-full-profile",
             "--write", "--run-id", run_id, "--results-root", str(runtime_root),
             "--evidence-id", evidence_id, "--expected-artifact-digest", expected_digest,
             "--timeout-sec", str(timeout)],
            capture_output=True, text=True, timeout=timeout + 120, check=False,
        )
        rj = runtime_root / run_id / "runtime-smoke.json"
        data = _load_json_object(rj)
        if runtime_proc.returncode != 0:
            checks = _checks_with_status(data or {})
            checks.insert(0, {"id": "runtime_command", "status": "fail",
                              "detail": f"return code {runtime_proc.returncode}"})
            return _stage_failure("runtime_command", f"return code {runtime_proc.returncode}", checks)
        if data is None:
            return _stage_failure("runtime_result", "exact runtime result missing or malformed")
        if not (
            data.get("schema_version") == 1 and data.get("run_id") == run_id
            and data.get("evidence_id") == evidence_id and data.get("artifact_kind") == "plugin"
            and data.get("input_artifact_digest") == expected_digest
        ):
            return _stage_failure("runtime_result", "runtime identity or artifact digest mismatch")
        if data.get("status") != "pass":
            return _stage_failure("runtime_status", f"top-level status {data.get('status')}", _checks_with_status(data))
        if (data.get("full_plugin_runtime_profile") or {}).get("status") != "pass":
            return _stage_failure("runtime_profile", "required full profile did not pass", _checks_with_status(data.get("full_plugin_runtime_profile") or {}))
        # Use only the runtime profile's check array (the one containing plugin_check / wp_env_smoke).
        runtime_checks: list[dict[str, Any]] = []
        for node in _walk_objects(data):
            checks = node.get("checks") if isinstance(node, dict) else None
            if isinstance(checks, list) and any(
                isinstance(c, dict) and c.get("id") in ("plugin_check", "wp_env_smoke") for c in checks
            ):
                runtime_checks = _checks_with_status({"checks": checks})
                break
        if not runtime_checks:
            runtime_checks = _checks_with_status(data)
        failing = _nonpassing_check_ids(runtime_checks)
        passed = bool(runtime_checks) and not failing
        return {"passed": passed, "failing_gates": failing,
                "failures": _failure_text(runtime_checks),
                "gate_vector": {c["id"]: c["status"] for c in runtime_checks}}

    return certify


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Automated WordPress executor repair loop.")
    p.add_argument("--suite", required=True)
    p.add_argument("--fixture", required=True)
    p.add_argument("--condition", default="skill", help="skill | baseline-zero-shot | baseline-few-shot")
    p.add_argument("--provider", default=None, choices=("codex", "claude", "ollama", "gemini"),
                   help="Override generation backend (runs the executor persona on this model). "
                        "Use with --model. For the cross-market cheaper-model sweep.")
    p.add_argument("--executor", default="plugin", choices=("plugin", "block", "blueprint"))
    p.add_argument("--max-repairs", type=int, default=2, help="Max repair iterations after the initial generation.")
    p.add_argument("--gen-retries", type=int, default=1,
                   help="Retries for a failed/empty generation (model timeout) before that slot is "
                        "recorded as a generation failure. Failures never discard the last-good packet.")
    p.add_argument("--profile", default="runtime", choices=("static", "runtime"))
    p.add_argument("--run-id", required=True)
    p.add_argument("--model", default=None)
    p.add_argument("--effort", default=None, choices=("low", "medium", "high", "xhigh", "max"))
    p.add_argument("--timeout-sec", type=int, default=900)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_dir = create_named(RESULTS, args.run_id, WorkspacePurpose.REPAIR_RUN).root
    except (ValueError, FileExistsError) as exc:
        print(f"repair run refused: {exc}", file=sys.stderr)
        return 2

    generate = make_generate(args.suite, args.fixture, args.condition, run_dir,
                             args.model, args.effort, args.timeout_sec, provider=args.provider)
    certify = make_certify(args.suite, args.executor, run_dir, args.profile, args.timeout_sec)

    result = orchestrate(generate, certify, args.max_repairs, args.gen_retries)

    summary = {
        "suite": args.suite, "fixture": args.fixture, "condition": args.condition,
        "provider": args.provider, "model": args.model,
        "executor": args.executor, "profile": args.profile, "max_repairs": args.max_repairs,
        "gen_retries": args.gen_retries,
        "green": result["green"], "pass_at_1": result["pass_at_1"],
        "pass_at_k": result["green"], "iterations_to_green": result["iterations_to_green"],
        "generations": result["generations"],
        "generation_failures": result.get("generation_failures", 0),
        "history": result["history"],
    }
    (run_dir / "repair-loop-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"=== repair loop: {args.condition} / {args.fixture} ({args.profile}) ===")
    for h in result["history"]:
        tag = "PASS" if h["passed"] else "fail"
        fails = "" if h["passed"] else f"  failing: {', '.join(h['failing_gates']) or '?'}"
        print(f"  iter {h['iteration']}: {tag}{fails}")
    if result["green"]:
        print(f"GREEN after {result['iterations_to_green']} repair(s)  (pass@1={result['pass_at_1']})")
    else:
        print(f"NOT GREEN within {args.max_repairs} repair(s)")
    if result.get("generation_failures"):
        print(f"  ({result['generation_failures']} generation failure(s) retried/skipped "
              "without discarding the last-good packet)")
    print(f"summary: {(run_dir / 'repair-loop-summary.json')}")
    return 0 if result["green"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
