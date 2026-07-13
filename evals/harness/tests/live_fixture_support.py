"""Exact-ID lifecycle helpers for live Docker boundary fixtures."""
from __future__ import annotations

import os
import re
import time

import sandboxed_package_runner as runner
import step4_evidence
import workspace_lease


def run(ledger, command, timeout, error):
    result = runner._bound_control(ledger, command, timeout)
    if result["returncode"]:
        raise RuntimeError(error)
    return result


def create(ledger, kind, name, command, timeout=120):
    ledger.record(kind, name, "attempted")
    result = run(ledger, command, timeout, f"{kind} fixture create failed")
    target = runner.resource_identity.exact_created_id(result, f"{kind} fixture")
    ledger.bind(name, target); ledger.record(kind, name, "created")
    return target


def _absence_command(kind, boundary, value):
    noun = "container" if kind == "container" else "network"
    name_field = "Names" if kind == "container" else "Name"
    options = ["-a"] if kind == "container" else []
    pattern = f"^/{value}$" if kind == "container" and boundary == "name" else f"^{value}$"
    selected = value if boundary == "id" else pattern
    return ["docker", noun, "ls", *options, "--no-trunc", "--filter", f"{boundary}={selected}", "--format", f"{{{{.ID}}}}\t{{{{.{name_field}}}}}"]


def _listed_rows(result, expected_name=None):
    if result["returncode"] or result["stderr"]:
        raise RuntimeError("authenticated absence listing failed")
    if not result["stdout"]:
        return ()
    if not result["stdout"].endswith("\n"):
        raise RuntimeError("authenticated absence listing is noncanonical")
    rows = []
    for line in result["stdout"].splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or not re.fullmatch(r"[0-9a-f]{64}", fields[0]) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", fields[1]):
            raise RuntimeError("authenticated absence listing is malformed")
        if expected_name is not None and fields[1] != expected_name:
            raise RuntimeError("authenticated name listing escaped its exact filter")
        rows.append(tuple(fields))
    return tuple(rows)


def _prove_absent(ledger, kind, name, target):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", name):
        return f"{kind}:{name}:invalid-logical-name"
    for boundary, value in (("id", target), ("name", name)):
        command = _absence_command(kind, boundary, value)
        try: rows = _listed_rows(runner._bound_control(ledger, command, 30), name if boundary == "name" else None)
        except Exception as exc: return f"{kind}:{name}:{boundary}-absence-{type(exc).__name__}"
        if rows:
            state = "retained" if boundary == "id" else "name-replaced"
            return f"{kind}:{name}:{state}:{rows[0][0]}"
    return None


def _remove(ledger, kind, name):
    states = [event.state for event in ledger.events if event.kind == kind and event.name == name]
    if not states or states[-1] == "removed":
        return None
    target = ledger.target(name)
    if "created" not in states or not re.fullmatch(r"[0-9a-f]{64}", target):
        return f"{kind}:{name}:unverified"
    if ledger.identity_tainted:
        return f"{kind}:{name}:{target}:daemon-tainted"
    command = ["docker", "rm", "-f", target] if kind == "container" else ["docker", "network", "rm", target]
    try: removed = runner._bound_control(ledger, command, 60)
    except Exception as exc: return f"{kind}:{name}:{type(exc).__name__}"
    if removed["returncode"]: return f"{kind}:{name}:remove-failed"
    if issue := _prove_absent(ledger, kind, name, target): return issue
    ledger.record(kind, name, "removed"); return None


def cleanup(ledger, containers, networks):
    retained = []
    for kind, names in (("container", containers), ("network", networks)):
        for name in names:
            if issue := _remove(ledger, kind, name): retained.append(issue)
    return retained


def finish(context, stopped, ledger, containers, networks, code, capability, tree, payload):
    retained = []
    if context is not None and context.supervisor is not None and not stopped:
        try:
            if ledger.identity_tainted: runner.proxy_supervisor.reap_host(context.supervisor)
            else:
                gate = lambda: runner.daemon_control.require(ledger, runner._control_run, time.monotonic() + 60)
                runner.proxy_supervisor.abort(context.supervisor, lambda command, timeout: runner._bound_control(ledger, command, timeout), gate)
        except Exception as abort_error:
            try: runner.proxy_supervisor.reap_host(context.supervisor)
            except Exception as reap_error: retained.append(f"supervisor:abort-{type(abort_error).__name__}:reap-{type(reap_error).__name__}")
    retained.extend(cleanup(ledger, containers, networks))
    os.close(capability.root_fd); os.close(capability.lease_fd)
    if not retained:
        if code is not None: runner._release_proxy_code(code)
        workspace_lease.cleanup(tree.lease)
    assert not retained, retained
    if payload is not None:
        topology = payload["topology"]
        payload["cleanup_disposition"] = {"complete": True, "retained": [], "removed": {kind: {role: {"id": item["id"], "name": item["name"]} for role, item in topology[kind].items()} for kind in ("containers", "networks")}}
        step4_evidence.write_leg("controlled_connect", payload)
