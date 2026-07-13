import json
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))
import sandbox_dns_guard


def _successful_run(commands):
    def run(command, _timeout):
        commands.append(command)
        if command[:2] == ["docker", "inspect"]:
            return {"returncode": 0, "stdout": json.dumps([{"HostConfig": {"Dns": ["127.0.0.1"]}}]), "stderr": ""}
        if command[-2:] == ["cat", "/etc/resolv.conf"]:
            return {"returncode": 0, "stdout": "nameserver 127.0.0.11\n# ExtServers: [127.0.0.1]\n", "stderr": ""}
        return {"returncode": 0, "stdout": "", "stderr": ""}
    return run


@pytest.mark.parametrize("kind,tokens", [("npm", ("resolve4", "resolve6")), ("composer", ("DNS_A", "DNS_AAAA"))])
def test_pre_acquisition_dns_gate_checks_stub_and_both_address_families(kind, tokens):
    commands = []
    sandbox_dns_guard.pre_acquisition("package", kind, _successful_run(commands))
    script = commands[-1][-1]
    assert all(token in script for token in tokens)
    assert commands[0] == ["docker", "inspect", "package"]


@pytest.mark.parametrize("failure", ["host", "resolv", "lookup"])
def test_pre_acquisition_dns_gate_fails_closed(failure):
    calls = []
    base = _successful_run(calls)
    def run(command, timeout):
        result = base(command, timeout)
        if failure == "host" and command[:2] == ["docker", "inspect"]:
            result["stdout"] = json.dumps([{"HostConfig": {"Dns": []}}])
        elif failure == "resolv" and command[-2:] == ["cat", "/etc/resolv.conf"]:
            result["stdout"] = "nameserver 8.8.8.8\n"
        elif failure == "lookup" and command[:3] == ["docker", "exec", "package"] and command[-2:] != ["cat", "/etc/resolv.conf"]:
            result["returncode"] = 1
        return result
    with pytest.raises(RuntimeError):
        sandbox_dns_guard.pre_acquisition("package", "npm", run)
