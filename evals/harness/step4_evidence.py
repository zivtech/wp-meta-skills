"""Atomic, bounded evidence contract for the three Step 4 Linux legs."""
from __future__ import annotations

import ipaddress
import json
import math
import os
import re
import stat
from pathlib import Path

import dependency_egress_proxy
import runtime_image_provision
import sandbox_resource_contract
import sandbox_timing_contract

LEGS = ("npm_lifecycle", "composer_lifecycle", "controlled_connect")
PER_LEG_LIMIT = 32768
COMBINED_LIMIT = 131072
SCHEMA_VERSION = 1
MAX_DEPTH = 16
MAX_NODES = 4096
MAX_COLLECTION_LENGTH = 512
MAX_STRING_CHARACTERS = 8192
MAX_STRING_UTF8_BYTES = 16384
MAX_KEY_CHARACTERS = 128
MAX_KEY_UTF8_BYTES = 512
FAKE_PUBLIC_SUBNET = "93.184.216.32/28"
FAKE_PUBLIC_GATEWAY = "93.184.216.33"
FAKE_REGISTRY_IP = "93.184.216.34"
TIMING_KEYS = sandbox_timing_contract.EVIDENCE_KEYS
METRIC_KEYS = frozenset({"mem_available", "proxy_memory_peak", "package_memory_peak_pre_export", "workspace_bytes_used_pre_export", "package_memory_peak", "workspace_bytes_used"})
LIMIT_KEYS = frozenset({"package_memory_limit_bytes","workspace_limit_bytes","proxy_memory_limit_bytes","host_reserve_bytes","admission_required_bytes"})
IDENTITY_KEYS = frozenset({"profile_id", "manifest_sha256", "lock_sha256", "package_image_ref", "proxy_image_ref", "package_local_image_id", "proxy_local_image_id", "package_container_id", "proxy_container_id", "package_observed_image_id", "proxy_observed_image_id", "toolchain_versions", "runner_os", "runner_arch"})|LIMIT_KEYS
EXPECTED_PROFILES = {"npm_lifecycle":"block-scripts-32.4.1-smoke","composer_lifecycle":"plugin-phpunit-12.5.31"}
EXPECTED_LIMITS = {"package_memory_limit_bytes":1024**3,"workspace_limit_bytes":1200*1024**2,"proxy_memory_limit_bytes":256*1024**2,"host_reserve_bytes":1024**3}


def _commit_sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Step 4 evidence requires an exact lowercase commit SHA")
    return value


def _encode(value, limit):
    _preflight(value, limit)
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if len(encoded) > limit:
        raise ValueError(f"Step 4 evidence exceeds {limit} bytes")
    return encoded


def _text_budget(value, key=False):
    max_chars = MAX_KEY_CHARACTERS if key else MAX_STRING_CHARACTERS
    max_bytes = MAX_KEY_UTF8_BYTES if key else MAX_STRING_UTF8_BYTES
    if len(value) > max_chars: raise ValueError("Step 4 evidence text character limit exceeded")
    encoded = value.encode("utf-8")
    if len(encoded) > max_bytes: raise ValueError("Step 4 evidence text UTF-8 limit exceeded")
    return len(value), len(encoded)


def _preflight(value, limit):
    stack = [(value, 0, False)]; active = set(); nodes = characters = utf8_bytes = 0
    while stack:
        item, depth, leaving = stack.pop()
        if leaving: active.remove(id(item)); continue
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH: raise ValueError("Step 4 evidence structural limit exceeded")
        if isinstance(item, dict):
            if id(item) in active or len(item) > MAX_COLLECTION_LENGTH: raise ValueError("Step 4 evidence mapping is cyclic or oversized")
            active.add(id(item)); stack.append((item, depth, True))
            for key, child in item.items():
                if type(key) is not str: raise ValueError("Step 4 evidence keys must be strings")
                nodes += 1; chars, size = _text_budget(key, True); characters += chars; utf8_bytes += size
                stack.append((child, depth + 1, False))
        elif isinstance(item, list):
            if id(item) in active or len(item) > MAX_COLLECTION_LENGTH: raise ValueError("Step 4 evidence list is cyclic or oversized")
            active.add(id(item)); stack.append((item, depth, True)); stack.extend((child, depth + 1, False) for child in item)
        elif type(item) is str:
            chars, size = _text_budget(item); characters += chars; utf8_bytes += size
        elif item is None or type(item) is bool: pass
        elif type(item) is int:
            if item.bit_length() > 256: raise ValueError("Step 4 evidence integer is oversized")
        elif type(item) is float:
            if not math.isfinite(item): raise ValueError("Step 4 evidence number is nonfinite")
        else: raise ValueError("Step 4 evidence contains a non-JSON value")
        if nodes > MAX_NODES or characters > limit or utf8_bytes > limit: raise ValueError("Step 4 evidence aggregate budget exceeded")


def _strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError(f"duplicate Step 4 evidence key: {key}")
            result[key] = value
        return result
    reject = lambda value: (_ for _ in ()).throw(ValueError(f"nonfinite Step 4 evidence value: {value}"))
    return json.loads(data, object_pairs_hook=pairs, parse_constant=reject)


def _atomic_write(path, encoded):
    path = Path(path); root = path.parent; info = os.lstat(root)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or os.path.lexists(path):
        raise RuntimeError("Step 4 evidence destination is not a fresh real directory entry")
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0: raise OSError("Step 4 evidence write made no progress")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(directory)
    finally: os.close(directory)


def lifecycle_payload(result, acquisition_identity):
    detail = _strict_json(result.detail)
    events = sandbox_resource_contract.project(detail.get("resource_events", []),allow_termination=result.status!="pass")
    cleanup = [item for item in events if item.get("state") in {"detached", "removed", "retained"}]
    identity = dict(acquisition_identity)
    identity.update(getattr(result, "runtime_identity", None) or {})
    return {
        "cleanup_events": cleanup,
        "final_status": result.status,
        "identity": identity,
        "metrics": detail.get("metrics", {}),
        "resource_events": events,
        "timings_seconds": detail.get("timings_seconds", {}),
    }


def write_leg(leg, payload, directory=None, commit_sha=None):
    if leg not in LEGS or not isinstance(payload, dict):
        raise ValueError("invalid Step 4 evidence leg")
    configured = directory if directory is not None else os.environ.get("STEP4_EVIDENCE_DIR")
    if not configured:
        return None
    sha = _commit_sha(commit_sha if commit_sha is not None else os.environ.get("CANARY_COMMIT_SHA"))
    record = {"commit_sha": sha, "leg": leg, "payload": payload, "schema_version": SCHEMA_VERSION}
    path = Path(configured) / f"{leg}.json"
    _atomic_write(path, _encode(record, PER_LEG_LIMIT))
    return path


def _read_leg(path, leg, commit_sha):
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > PER_LEG_LIMIT:
        raise ValueError(f"invalid Step 4 evidence file metadata: {leg}")
    record = _strict_json(Path(path).read_bytes())
    _preflight(record, PER_LEG_LIMIT)
    if set(record) != {"commit_sha", "leg", "payload", "schema_version"} or type(record["schema_version"]) is not int or record["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"invalid Step 4 evidence record schema: {leg}")
    if record["leg"] != leg or record["commit_sha"] != commit_sha or not isinstance(record["payload"], dict):
        raise ValueError(f"Step 4 evidence identity mismatch: {leg}")
    return record


def _validate_identity(identity, leg):
    if not isinstance(identity, dict) or set(identity) != IDENTITY_KEYS:
        raise ValueError("Step 4 acquisition identity schema is invalid")
    string_keys=IDENTITY_KEYS-LIMIT_KEYS-{"toolchain_versions"}
    if any(type(identity[key]) is not str for key in string_keys) or type(identity["toolchain_versions"]) is not list or any(type(identity[key]) is not int for key in LIMIT_KEYS): raise ValueError("Step 4 acquisition identity types are invalid")
    profile = dependency_egress_proxy.ACQUISITION_PROFILES.get(identity["profile_id"])
    expected_kind = "npm" if leg == "npm_lifecycle" else "composer"
    if identity["profile_id"] != EXPECTED_PROFILES[leg] or profile is None or profile.kind != expected_kind or identity["runner_os"] != "Linux" or identity["runner_arch"] not in {"amd64", "arm64"}:
        raise ValueError("Step 4 acquisition profile or runner identity is invalid")
    arch = identity["runner_arch"]; inventory = runtime_image_provision.inventory()["images"]
    package = inventory[profile.image_key]; proxy = inventory["python"]
    digest = profile.amd64_digest if arch == "amd64" else profile.arm64_digest
    package_ref = f"{package['tag'].split(':')[0]}@{digest}"
    proxy_ref = f"{proxy['tag'].split(':')[0]}@{proxy[arch]}"
    expected = (profile.manifest_sha256, profile.lock_sha256, package_ref, proxy_ref, list(profile.versions))
    observed = (identity["manifest_sha256"], identity["lock_sha256"], identity["package_image_ref"], identity["proxy_image_ref"], identity["toolchain_versions"])
    if observed != expected: raise ValueError("Step 4 frozen acquisition identity drift")
    image_ids = (identity["package_local_image_id"], identity["proxy_local_image_id"])
    if image_ids[0] == image_ids[1] or any(not re.fullmatch(r"sha256:[0-9a-f]{64}", item) for item in image_ids):
        raise ValueError("Step 4 local image identity is invalid")
    container_ids = (identity["package_container_id"], identity["proxy_container_id"])
    observed_ids = (identity["package_observed_image_id"], identity["proxy_observed_image_id"])
    if container_ids[0] == container_ids[1] or any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in container_ids):
        raise ValueError("Step 4 live container identity is invalid")
    if observed_ids != image_ids:
        raise ValueError("Step 4 observed and local image identities differ")
    expected_limits=EXPECTED_LIMITS|{"admission_required_bytes":sum(EXPECTED_LIMITS.values())}
    if {key:identity[key] for key in LIMIT_KEYS} != expected_limits: raise ValueError("Step 4 lifecycle resource limits differ from the named Docker tests")


def _validate_numeric_evidence(payload):
    timings, metrics = payload["timings_seconds"], payload["metrics"]
    if not isinstance(timings, dict) or set(timings) != TIMING_KEYS:
        raise ValueError("Step 4 lifecycle timing schema is invalid")
    if any(type(value) not in {int, float} or not math.isfinite(value) or value < 0 for value in timings.values()):
        raise ValueError("Step 4 lifecycle timing value is invalid")
    if not isinstance(metrics, dict) or set(metrics) != METRIC_KEYS:
        raise ValueError("Step 4 lifecycle metric schema is invalid")
    if any(type(value) is not int or value < 0 for value in metrics.values()):
        raise ValueError("Step 4 lifecycle metric value is invalid")
    if any(value <= 0 for value in metrics.values()) or metrics["package_memory_peak"] < metrics["package_memory_peak_pre_export"]:
        raise ValueError("Step 4 successful lifecycle metrics are not meaningful")
    identity=payload["identity"]
    if metrics["mem_available"] < identity["admission_required_bytes"] or metrics["proxy_memory_peak"] > identity["proxy_memory_limit_bytes"]: raise ValueError("Step 4 lifecycle admission or proxy usage exceeds its envelope")
    if max(metrics["package_memory_peak_pre_export"],metrics["package_memory_peak"]) > identity["package_memory_limit_bytes"]: raise ValueError("Step 4 package usage exceeds its envelope")
    if max(metrics["workspace_bytes_used_pre_export"],metrics["workspace_bytes_used"]) > identity["workspace_limit_bytes"]: raise ValueError("Step 4 workspace usage exceeds its envelope")
    end_to_end=timings["end_to_end"]
    if any(value <= 0 or value > end_to_end for value in timings.values()): raise ValueError("Step 4 successful lifecycle timings are not meaningful")
    sequential=sum(value for key,value in timings.items() if key!="end_to_end")
    if sequential > end_to_end+1e-6: raise ValueError("Step 4 sequential lifecycle phases exceed end-to-end time")


def _expected_resource_histories(grouped):
    package = [name for kind, name in grouped if kind == "container" and re.fullmatch(r"wp-package-[0-9a-f]{16}", name)]
    if len(package) != 1: raise ValueError("Step 4 package resource identity is invalid")
    token = package[0].removeprefix("wp-package-")
    names = {"package":package[0],"proxy":f"wp-acquire-proxy-{token}","internal":f"wp-acquire-internal-{token}","egress":f"wp-acquire-egress-{token}","lease":f"wp-meta-skills-artifact-execution-{token}"}
    lease = [name for kind, name in grouped if kind == "lease"]
    if len(lease) != 1 or Path(lease[0]).name != names["lease"]: raise ValueError("Step 4 proxy-code lease run identity is invalid")
    return {
        ("container",names["package"]):["created","detached","removed"],
        ("container",names["proxy"]):["created","removed"],
        ("network",names["internal"]):["created","attached","attached","detached","removed"],
        ("network",names["egress"]):["created","attached","detached","removed"],
        ("lease",lease[0]):["created","removed"],
    }


def _validate_resource_events(payload):
    events, cleanup = payload["resource_events"], payload["cleanup_events"]
    if not isinstance(events, list) or not isinstance(cleanup, list) or not events:
        raise ValueError("Step 4 lifecycle resource evidence is invalid")
    kinds = sandbox_resource_contract.KINDS; states = sandbox_resource_contract.STATES
    for item in events:
        if not isinstance(item, dict) or set(item) != {"kind", "name", "state"}: raise ValueError("Step 4 lifecycle resource event schema is invalid")
        if item["kind"] not in kinds or item["state"] not in states or not isinstance(item["name"], str) or not item["name"]: raise ValueError("Step 4 lifecycle resource event value is invalid")
    expected_cleanup = [item for item in events if item["state"] in {"detached", "removed", "retained"}]
    if cleanup != expected_cleanup or any(item["state"] == "retained" for item in events): raise ValueError("Step 4 lifecycle cleanup is invalid")
    grouped = {}
    for item in events: grouped.setdefault((item["kind"], item["name"]), []).append(item["state"])
    expected = _expected_resource_histories(grouped)
    if grouped != expected or any(history[-1] != "removed" for history in grouped.values()):
        raise ValueError("Step 4 lifecycle transition history is incomplete or resurrected")


def _validate_lifecycle(payload, leg):
    required = {"cleanup_events", "final_status", "identity", "metrics", "resource_events", "timings_seconds"}
    if not isinstance(payload, dict) or set(payload) != required or payload["final_status"] != "pass":
        raise ValueError("Step 4 lifecycle did not pass exact schema")
    _validate_identity(payload["identity"], leg)
    _validate_numeric_evidence(payload)
    _validate_resource_events(payload)


def _validate_topology(topology):
    if not isinstance(topology, dict) or set(topology) != {"containers", "networks"}:
        raise ValueError("controlled CONNECT topology schema is invalid")
    containers, networks = topology["containers"], topology["networks"]
    if not isinstance(containers, dict) or not isinstance(networks, dict) or set(containers) != {"package", "proxy", "registry"} or set(networks) != {"internal", "egress"}:
        raise ValueError("controlled CONNECT topology inventory is incomplete")
    network_keys = {"id", "name", "internal", "subnet", "gateway"}
    if any(not isinstance(item, dict) or set(item) != {"id", "name", "ips"} for item in containers.values()) or any(not isinstance(item, dict) or set(item) != network_keys for item in networks.values()):
        raise ValueError("controlled CONNECT topology item schema is invalid")
    for item in (*containers.values(), *networks.values()):
        if type(item.get("id")) is not str or not re.fullmatch(r"[0-9a-f]{64}", item["id"]):
            raise ValueError("controlled CONNECT topology ID is invalid")
    for item in containers.values():
        if not isinstance(item.get("ips"), dict) or not item["ips"] or any(type(address) is not str for address in item["ips"].values()):
            raise ValueError("controlled CONNECT live IP inventory is absent")
        if not isinstance(item.get("name"), str) or not item["name"]: raise ValueError("controlled CONNECT container name is invalid")
    if len({item["name"] for item in containers.values()}) != 3: raise ValueError("controlled CONNECT container names are not distinct")
    if any(not isinstance(item.get("name"), str) or not item["name"] for item in networks.values()): raise ValueError("controlled CONNECT network name is invalid")
    internal, egress = networks["internal"]["name"], networks["egress"]["name"]
    if internal == egress or networks["internal"]["id"] == networks["egress"]["id"]:
        raise ValueError("controlled CONNECT networks are not distinct")
    patterns={"package":r"wp-package-fake-([0-9a-f]{12})","proxy":r"wp-proxy-fake-([0-9a-f]{12})","registry":r"wp-registry-fake-([0-9a-f]{12})","internal":r"wp-fake-internal-([0-9a-f]{12})","egress":r"wp-fake-egress-([0-9a-f]{12})"}
    named={role:item["name"] for role,item in containers.items()}|{role:item["name"] for role,item in networks.items()}
    matches={role:re.fullmatch(patterns[role],name) for role,name in named.items()}
    if any(match is None for match in matches.values()) or len({match.group(1) for match in matches.values()}) != 1: raise ValueError("controlled CONNECT names do not share the production run token")
    expected = {"package": {internal}, "proxy": {internal, egress}, "registry": {egress}}
    if any(set(containers[key]["ips"]) != names for key, names in expected.items()):
        raise ValueError("controlled CONNECT endpoint membership is invalid")
    ids = [item["id"] for item in containers.values()] + [item["id"] for item in networks.values()]
    if len(set(ids)) != 5: raise ValueError("controlled CONNECT identities are not distinct")
    if any(type(networks[role][key]) is not str for role in networks for key in ("subnet","gateway")): raise ValueError("controlled CONNECT network address types are invalid")
    internal_net = ipaddress.ip_network(networks["internal"]["subnet"]); internal_gateway = ipaddress.ip_address(networks["internal"]["gateway"])
    fake_net = ipaddress.ip_network(networks["egress"]["subnet"]); fake_gateway = ipaddress.ip_address(networks["egress"]["gateway"])
    if not isinstance(internal_net,ipaddress.IPv4Network) or not isinstance(internal_gateway,ipaddress.IPv4Address) or internal_gateway in {internal_net.network_address,internal_net.broadcast_address}:
        raise ValueError("controlled CONNECT internal network is not usable IPv4")
    if not isinstance(fake_net,ipaddress.IPv4Network) or not isinstance(fake_gateway,ipaddress.IPv4Address) or fake_gateway in {fake_net.network_address,fake_net.broadcast_address}:
        raise ValueError("controlled CONNECT fake network is not usable IPv4")
    if networks["internal"]["internal"] is not True or not internal_net.is_private or internal_gateway not in internal_net:
        raise ValueError("controlled CONNECT internal network policy drift")
    if networks["egress"]["internal"] is not False or str(fake_net) != FAKE_PUBLIC_SUBNET or str(fake_gateway) != FAKE_PUBLIC_GATEWAY:
        raise ValueError("controlled CONNECT fake egress policy drift")
    package_ip = ipaddress.ip_address(containers["package"]["ips"][internal]); proxy_internal = ipaddress.ip_address(containers["proxy"]["ips"][internal])
    proxy_egress = ipaddress.ip_address(containers["proxy"]["ips"][egress]); registry_ip = ipaddress.ip_address(containers["registry"]["ips"][egress])
    if any(not isinstance(item,ipaddress.IPv4Address) for item in (package_ip,proxy_internal,proxy_egress,registry_ip)): raise ValueError("controlled CONNECT endpoints are not IPv4")
    if len({package_ip, proxy_internal, proxy_egress, registry_ip}) != 4: raise ValueError("controlled CONNECT endpoint IPs are not distinct")
    internal_forbidden={internal_net.network_address,internal_net.broadcast_address,internal_gateway}
    fake_forbidden={fake_net.network_address,fake_net.broadcast_address,fake_gateway}
    if any(not item.is_private or item not in internal_net or item in internal_forbidden for item in (package_ip, proxy_internal)): raise ValueError("controlled CONNECT internal endpoints are invalid")
    if registry_ip != ipaddress.ip_address(FAKE_REGISTRY_IP) or any(item not in fake_net or item in fake_forbidden for item in (proxy_egress,registry_ip)) or proxy_egress == registry_ip: raise ValueError("controlled CONNECT fake endpoints are invalid")


def _validate_controlled_cleanup(cleanup, topology):
    if not isinstance(cleanup,dict) or set(cleanup) != {"complete","retained","removed"}: raise ValueError("controlled CONNECT cleanup schema is invalid")
    if cleanup["complete"] is not True or type(cleanup["retained"]) is not list or cleanup["retained"] != []: raise ValueError("controlled CONNECT cleanup is incomplete")
    expected={kind:{role:{"id":item["id"],"name":item["name"]} for role,item in topology[kind].items()} for kind in ("containers","networks")}
    if cleanup["removed"] != expected: raise ValueError("controlled CONNECT removed inventory does not match topology")


def _validate_controlled(payload):
    required = {"cleanup_disposition", "proxy_status", "relay_nonce", "run_nonce", "topology"}
    if not isinstance(payload,dict) or set(payload) != required:
        raise ValueError("controlled CONNECT evidence schema is invalid")
    _validate_topology(payload["topology"])
    _validate_controlled_cleanup(payload["cleanup_disposition"],payload["topology"])
    for key in ("relay_nonce", "run_nonce"):
        if type(payload.get(key)) is not str or not re.fullmatch(r"[a-z0-9-]{8,128}", payload[key]):
            raise ValueError("controlled CONNECT nonce is invalid")
    status = payload["proxy_status"]
    expected = {"nonce", "accepted", "active", "completed", "rejected", "rejected_peer", "rejected_capacity", "rejected_handler", "client_bytes", "upstream_bytes"}
    if not isinstance(status,dict) or set(status) != expected or status["nonce"] != payload["run_nonce"]:
        raise ValueError("controlled CONNECT proxy status identity is invalid")
    if any(type(status[key]) is not int or status[key] < 0 for key in expected - {"nonce"}):
        raise ValueError("controlled CONNECT proxy status values are invalid")
    if status["rejected"] != sum(status[key] for key in ("rejected_peer", "rejected_capacity", "rejected_handler")):
        raise ValueError("controlled CONNECT proxy status rejection counters are invalid")
    if (status["accepted"], status["active"], status["completed"], status["rejected"]) != (1, 0, 1, 0):
        raise ValueError("controlled CONNECT proxy status counters are invalid")
    if status["client_bytes"] != len(payload["relay_nonce"]) or status["upstream_bytes"] != len(payload["relay_nonce"]):
        raise ValueError("controlled CONNECT proxy byte counters are invalid")


def _lifecycle_run_token(payload):
    names=[item["name"] for item in payload["resource_events"] if item["kind"]=="container" and item["name"].startswith("wp-package-")]
    match=re.fullmatch(r"wp-package-([0-9a-f]{16})",names[0]) if len(set(names))==1 else None
    if match is None: raise ValueError("Step 4 lifecycle run token is invalid")
    return match.group(1)


def _validate_cross_leg(records,duration_seconds):
    npm=records["npm_lifecycle"]["payload"]; composer=records["composer_lifecycle"]["payload"]; controlled=records["controlled_connect"]["payload"]
    identities=(npm["identity"],composer["identity"])
    if len({(item["runner_os"],item["runner_arch"]) for item in identities}) != 1: raise ValueError("Step 4 lifecycle runner identities differ")
    proxy_keys=("proxy_image_ref","proxy_local_image_id","proxy_observed_image_id")
    if len({tuple(item[key] for key in proxy_keys) for item in identities}) != 1: raise ValueError("Step 4 lifecycle proxy identities differ")
    if _lifecycle_run_token(npm)==_lifecycle_run_token(composer): raise ValueError("Step 4 lifecycle run tokens are not distinct")
    lifecycle_ids=[item[key] for item in identities for key in ("package_container_id","proxy_container_id")]
    controlled_ids=[item["id"] for item in controlled["topology"]["containers"].values()]
    if len(set(lifecycle_ids+controlled_ids)) != 7: raise ValueError("Step 4 container identities are not globally distinct")
    end_to_end=[payload["timings_seconds"]["end_to_end"] for payload in (npm,composer)]
    if any(value > duration_seconds+1 for value in end_to_end) or sum(end_to_end) > duration_seconds+1: raise ValueError("Step 4 lifecycle duration exceeds the sequential pytest wall clock")


def combine_records(directory, output_path, commit_sha, pytest_status, duration_seconds):
    root = Path(directory); sha = _commit_sha(commit_sha)
    root_info = os.lstat(root)
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise ValueError("Step 4 evidence root is not a real directory")
    expected = {f"{leg}.json" for leg in LEGS}
    if {item.name for item in root.iterdir()} != expected:
        raise ValueError("Step 4 evidence directory is missing legs or contains extras")
    if type(pytest_status) is not int or pytest_status != 0 or type(duration_seconds) is not int or not 0 < duration_seconds <= 3600:
        raise ValueError("Step 4 evidence is ineligible because Docker pytest status or duration is invalid")
    records = {leg: _read_leg(root / f"{leg}.json", leg, sha) for leg in LEGS}
    _validate_lifecycle(records["npm_lifecycle"]["payload"], "npm_lifecycle")
    _validate_lifecycle(records["composer_lifecycle"]["payload"], "composer_lifecycle")
    _validate_controlled(records["controlled_connect"]["payload"])
    _validate_cross_leg(records,duration_seconds)
    combined = {"commit_sha": sha, "duration_seconds": duration_seconds, "legs": records, "pytest_status": pytest_status, "schema_version": SCHEMA_VERSION}
    _atomic_write(output_path, _encode(combined, COMBINED_LIMIT))
    return Path(output_path)
