"""Exact, label-authenticated ownership recovery for Docker resources."""
from __future__ import annotations

import json
import re

import sandbox_network_policy


def exact_created_id(result: dict, boundary: str) -> str:
    target = result.get("stdout", "").strip()
    if re.fullmatch(r"[0-9a-f]{64}", target) is None:
        raise RuntimeError(f"{boundary} create identity is malformed")
    return target


def labels(token: str, role: str) -> tuple[str, str]:
    if re.fullmatch(r"[0-9a-f]{16}", token) is None:
        raise ValueError("resource ownership token is malformed")
    if role not in {"package", "proxy", "internal", "egress"}:
        raise ValueError("resource ownership role is unsupported")
    return f"wp-meta-run={token}", f"wp-meta-role={role}"


def _label_map(data: dict) -> dict:
    observed = data.get("Labels")
    return observed if isinstance(observed, dict) else {}


def _matches(data: dict, name: str, token: str, role: str) -> bool:
    observed = _label_map(data)
    return data.get("Name", "").lstrip("/") == name and observed.get("wp-meta-run") == token and observed.get("wp-meta-role") == role


def _record(ledger, kind: str, name: str, target: str) -> bool:
    if re.fullmatch(r"[0-9a-f]{64}", target) is None:
        return False
    ledger.bind(name, target)
    if not ledger.created(kind, name):
        ledger.record(kind, name, "created")
    return True


def discover_container(run, name: str, token: str, role: str, ledger) -> bool:
    result = run(["docker", "inspect", name], 30)
    if result["returncode"]:
        return False
    try:
        payload = json.loads(result["stdout"])
        data = payload[0] if len(payload) == 1 else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    config = data.get("Config", {})
    if not _matches({"Name": data.get("Name"), "Labels": config.get("Labels")}, name, token, role):
        return False
    return _record(ledger, "container", name, data.get("Id", ""))


def discover_network(run, name: str, token: str, role: str, spec, internal: bool, ledger) -> bool:
    result = run(["docker", "network", "inspect", name], 30)
    if result["returncode"]:
        return False
    try:
        payload = json.loads(result["stdout"])
        data = payload[0] if len(payload) == 1 else {}
        sandbox_network_policy.validate_inspection(data, name, spec, internal=internal)
    except (TypeError, ValueError, json.JSONDecodeError, RuntimeError):
        return False
    if not _matches(data, name, token, role):
        return False
    return _record(ledger, "network", name, data.get("Id", ""))
