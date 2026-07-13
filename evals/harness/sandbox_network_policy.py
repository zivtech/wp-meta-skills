"""Explicit, collision-resistant IPv4 policy for sandbox Docker networks.

The identity-to-subnet mapping is deterministic and intentionally has no
retry/remap path. A rare Docker overlap therefore blocks with the daemon's
bounded diagnostic instead of silently changing the reviewed topology.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from types import MappingProxyType


NETWORK_PREFIX = 29
SLOTS_PER_POOL = 524_288
GOLDEN_IDENTITY = "wp-meta-golden-v1"
INTERNAL_POOL = ipaddress.ip_network("10.64.0.0/10")
EGRESS_POOL = ipaddress.ip_network("10.128.0.0/10")
FIXTURE_POOL = ipaddress.ip_network("10.192.0.0/10")
POOLS = MappingProxyType({"internal": INTERNAL_POOL, "egress": EGRESS_POOL, "fixture": FIXTURE_POOL})


@dataclass(frozen=True)
class NetworkSpec:
    subnet: str
    gateway: str
    package_ip: str
    proxy_ip: str


@dataclass(frozen=True)
class NetworkSnapshot:
    name: str
    network_id: str
    internal: bool
    spec: NetworkSpec
    containers: frozenset[str]

    @property
    def addresses(self) -> tuple[str, str, str]:
        return self.spec.gateway, self.spec.package_ip, self.spec.proxy_ip


def _validate_identity(identity: str, pool_name: str) -> None:
    if identity == GOLDEN_IDENTITY:
        return
    pattern = r"[0-9a-f]{12}" if pool_name == "fixture" else r"[0-9a-f]{16}"
    if re.fullmatch(pattern, identity) is None:
        raise ValueError("sandbox network identity does not match its bounded role")


def specification(identity: str, pool_name: str) -> NetworkSpec:
    """Derive one /29 from a reviewed, role-separated RFC1918 pool."""
    if pool_name not in POOLS or not identity or not identity.isascii():
        raise ValueError("invalid sandbox network identity or pool")
    _validate_identity(identity, pool_name)
    pool = POOLS[pool_name]
    slots = 1 << (NETWORK_PREFIX - pool.prefixlen)
    if slots != SLOTS_PER_POOL:
        raise RuntimeError("sandbox network slot policy drift")
    digest = hashlib.sha256(f"wp-meta-network-v1:{pool_name}:{identity}".encode()).digest()
    slot = int.from_bytes(digest[:8], "big") % slots
    address = int(pool.network_address) + slot * (1 << (32 - NETWORK_PREFIX))
    subnet = ipaddress.ip_network((address, NETWORK_PREFIX))
    return NetworkSpec(
        str(subnet),
        str(subnet.network_address + 1),
        str(subnet.network_address + 2),
        str(subnet.network_address + 3),
    )


def create_command(name: str, spec: NetworkSpec, *, internal: bool, label: str | None = None) -> list[str]:
    command = [
        "docker", "network", "create", "--driver", "bridge",
        "--subnet", spec.subnet, "--gateway", spec.gateway,
    ]
    if internal:
        command.append("--internal")
    if label is not None:
        command.extend(("--label", label))
    command.append(name)
    return command


def validate_inspection(data: dict, name: str, spec: NetworkSpec, *, internal: bool) -> None:
    """Fail closed unless live Docker IPAM exactly matches the requested policy."""
    configs = data.get("IPAM", {}).get("Config", [])
    if data.get("Name") != name or data.get("Driver") != "bridge":
        raise RuntimeError("sandbox network identity or driver drift")
    if data.get("Internal") is not internal or data.get("EnableIPv6") is not False:
        raise RuntimeError("sandbox network isolation classification drift")
    if len(configs) != 1:
        raise RuntimeError("sandbox network has ambiguous IPAM")
    if configs[0].get("Subnet") != spec.subnet or configs[0].get("Gateway") != spec.gateway:
        raise RuntimeError("sandbox network subnet or gateway drift")
    subnet = ipaddress.ip_network(spec.subnet)
    endpoints = tuple(ipaddress.ip_address(item) for item in (spec.gateway, spec.package_ip, spec.proxy_ip))
    if not any(subnet.subnet_of(pool) for pool in POOLS.values()):
        raise RuntimeError("sandbox network escaped reviewed address pools")
    expected = tuple(subnet.network_address + offset for offset in (1, 2, 3))
    if endpoints != expected:
        raise RuntimeError("sandbox network endpoint policy is invalid")


def inspect(run, name: str, spec: NetworkSpec, *, internal: bool) -> NetworkSnapshot:
    result = run(["docker", "network", "inspect", name], 30)
    if result["returncode"]:
        raise RuntimeError(f"sandbox network inspection failed: {bounded_docker_error(result)}")
    try:
        data = json.loads(result["stdout"])[0]
    except (IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("sandbox network inspection is malformed") from exc
    validate_inspection(data, name, spec, internal=internal)
    containers = data.get("Containers", {})
    if not isinstance(containers, dict) or not all(re.fullmatch(r"[0-9a-f]{64}", item) for item in containers):
        raise RuntimeError("sandbox network peer inventory is malformed")
    network_id = data.get("Id")
    if not isinstance(network_id, str) or re.fullmatch(r"[0-9a-f]{64}", network_id) is None:
        raise RuntimeError("sandbox network ID is malformed")
    return NetworkSnapshot(name, network_id, internal, spec, frozenset(containers))


def acquisition_specifications(internal_name: str, egress_name: str) -> tuple[NetworkSpec, NetworkSpec]:
    prefix = "wp-acquire-internal-"
    if not internal_name.startswith(prefix):
        raise RuntimeError("acquisition internal network name drift")
    token = internal_name.removeprefix(prefix)
    if egress_name != f"wp-acquire-egress-{token}":
        raise RuntimeError("acquisition network token drift")
    return specification(token, "internal"), specification(token, "egress")


def bounded_docker_error(result: dict) -> str:
    detail = re.sub(r"/proc/[0-9]+/fd/[0-9]+", "/proc/<pid>/fd/<fd>", result.get("stderr", ""))
    detail = re.sub(r"[^\x20-\x7e]+", " ", detail)
    return re.sub(r" +", " ", detail).strip()[:2048] or "no bounded Docker diagnostic"
