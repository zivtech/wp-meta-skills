"""Exact final Compose topology for generated WordPress code."""
from __future__ import annotations

import json
import re

import isolated_runtime_contract as contract

SERVICE_NETWORKS = {
    "database": ["backend"],
    "wordpress": ["backend", "application"],
    "cli": ["backend"],
    "gateway": ["application", "frontend"],
    "browser": ["frontend"],
}
ISOLATED_BRIDGE_OPTIONS={"com.docker.network.bridge.gateway_mode_ipv4":"isolated"}
PRIMARY_NETWORK = {
    "database": "backend", "wordpress": "application", "cli": "backend",
    "gateway": "application", "browser": "frontend",
}
WRITABLE_PATHS = {
    "database": {"/var/lib/mysql", "/run/mysqld", "/tmp", "/dev/shm"},
    "wordpress": {"/tmp", "/var/www/html/wp-content/uploads", "/dev/shm"},
    "cli": {"/tmp", "/dev/shm"},
    "gateway": {"/tmp", "/dev/shm"},
    "browser": {"/tmp", "/dev/shm"},
}
WRITABLE_LIMITS = {
    "database": {"/var/lib/mysql": (134217728, 8192),
                 "/run/mysqld": (8388608, 512),
                 "/tmp": (16777216, 1024), "/dev/shm": (16777216, 1024)},
    "wordpress": {"/tmp": (33554432, 2048),
                  "/var/www/html/wp-content/uploads": (33554432, 2048),
                  "/dev/shm": (16777216, 1024)},
    "cli": {"/tmp": (16777216, 1024), "/dev/shm": (16777216, 1024)},
    "gateway": {"/tmp": (16777216, 1024), "/dev/shm": (16777216, 1024)},
    "browser": {"/tmp": (67108864, 4096), "/dev/shm": (16777216, 1024)},
}
BASE_FIELDS = {
    "image", "read_only", "cap_drop", "security_opt", "user", "networks",
    "tmpfs", "pids_limit", "mem_limit", "memswap_limit", "cpus", "ulimits",
    "logging", "init", "shm_size",
}


def _limits() -> dict:
    return {
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "pids_limit": 128,
        "mem_limit": "512m",
        "memswap_limit": "512m",
        "cpus": "0.5",
        "ulimits": {
            "nofile": {"soft": 1024, "hard": 1024},
            "nproc": {"soft": 256, "hard": 256},
        },
        "logging": {"driver": "none"},
        "init": True,
        "shm_size":"16m",
    }


def _tmpfs(path: str, identity: str, size: int, inodes: int) -> str:
    uid, gid = identity.split(":")
    return f"{path}:uid={uid},gid={gid},mode=0700,size={size},nr_inodes={inodes},nosuid,nodev,noexec"


def _gateway_command(plugin_slug: str, runtime_profile: str, block_post_id: int) -> list[str]:
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?",plugin_slug):
        raise ValueError("gateway plugin slug is unsafe")
    if runtime_profile not in contract.REQUIRED_CHECKS_BY_PROFILE:
        raise ValueError("gateway runtime profile is unsafe")
    expected = contract.BLOCK_CANARY_POST_ID if runtime_profile == contract.BLOCK_PROFILE else 0
    if block_post_id != expected:
        raise ValueError("gateway block post identity is unsafe")
    return ["/opt/wp-runtime/gateway-policy.js",plugin_slug,runtime_profile,str(block_post_id)]


def build_compose(
    images: dict, identities: dict, artifact_image:str, plugin_slug:str="runtime-plugin",
    runtime_profile:str=contract.STANDARD_PROFILE, block_post_id:int=0,
) -> dict:
    gateway_command = _gateway_command(plugin_slug, runtime_profile, block_post_id)
    services = {
        "database": {**_limits(), "image": images["database"], "user": identities["database"],
            "networks": ["backend"], "tmpfs": [
                _tmpfs("/var/lib/mysql", identities["database"], 134217728, 8192),
                _tmpfs("/run/mysqld", identities["database"], 8388608, 512),
                _tmpfs("/tmp", identities["database"], 16777216, 1024),
                _tmpfs("/dev/shm", identities["database"], 16777216, 1024),
            ]},
        "wordpress": {**_limits(), "image": artifact_image, "user": identities["wordpress"],
            "networks": {"backend": {},
                         "application": {"aliases": ["wordpress-application"]}}, "tmpfs": [
                _tmpfs("/tmp", identities["wordpress"], 33554432, 2048),
                _tmpfs("/var/www/html/wp-content/uploads", identities["wordpress"], 33554432, 2048),
                _tmpfs("/dev/shm", identities["wordpress"], 16777216, 1024),
            ]},
        "cli": {**_limits(), "image": artifact_image, "user": identities["wordpress"],
            "networks": ["backend"], "entrypoint": ["sleep"],
            "command": ["infinity"], "tmpfs": [
                _tmpfs("/tmp", identities["wordpress"], 16777216, 1024),
                _tmpfs("/dev/shm", identities["wordpress"], 16777216, 1024),
            ]},
        "gateway": {**_limits(), "image": images["browser"], "user": identities["browser"],
            "networks": {
                "application": {"aliases": ["gateway-application"]},
                "frontend": {"aliases": ["gateway-frontend"]},
            }, "entrypoint": ["node"],
            "command": gateway_command,
            "tmpfs": [_tmpfs("/tmp", identities["browser"], 16777216, 1024),
                      _tmpfs("/dev/shm", identities["browser"], 16777216, 1024)]},
        "browser": {**_limits(), "image": images["browser"], "user": identities["browser"],
            "networks": ["frontend"], "entrypoint": ["sleep"], "command": ["infinity"],
            "tmpfs": [_tmpfs("/tmp", identities["browser"], 67108864, 4096),
                      _tmpfs("/dev/shm", identities["browser"], 16777216, 1024)]},
    }
    networks={name:{"driver":"bridge","driver_opts":dict(ISOLATED_BRIDGE_OPTIONS),
                    "internal":True}
              for name in ("backend","application","frontend")}
    return {"services": services, "networks": networks}


def _validate_service_schema(name,service):
    extras = {"database": set(), "wordpress": set(),
              "cli": {"entrypoint", "command"},
              "gateway":{"entrypoint","command"},
              "browser": {"entrypoint", "command"}}
    if set(service) != BASE_FIELDS | extras[name]:
        raise ValueError(f"unknown or missing {name} service field")
    if list(service["networks"]) != SERVICE_NETWORKS[name]:
        raise ValueError(f"{name} network drift")
    aliases={
        "wordpress":{"backend":{},
                     "application":{"aliases":["wordpress-application"]}},
        "gateway":{"application":{"aliases":["gateway-application"]},
                   "frontend":{"aliases":["gateway-frontend"]}},
    }
    if name in aliases and service["networks"]!=aliases[name]:
        raise ValueError(f"{name} network aliases drift")


def _validate_service_limits(name,service):
    if (service["cap_drop"] != ["ALL"]
            or service["security_opt"] != ["no-new-privileges:true"]):
        raise ValueError(f"{name} privilege policy drift")
    if not service["read_only"] or service["logging"] != {"driver": "none"}:
        raise ValueError(f"{name} filesystem or logging policy drift")
    if not re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", service["user"]):
        raise ValueError(f"{name} user is not numeric and non-root")
    expected=(128,"512m","512m","0.5",True,"16m")
    actual=(service["pids_limit"],service["mem_limit"],service["memswap_limit"],
            service["cpus"],service["init"],service["shm_size"])
    ulimits={"nofile":{"soft":1024,"hard":1024},"nproc":{"soft":256,"hard":256}}
    if actual != expected or service["ulimits"] != ulimits:
        raise ValueError(f"{name} resource policy drift")


def _validate_service_storage(name,service,artifact_image):
    if not service["image"].startswith("sha256:"):
        raise ValueError(f"{name} image is not an exact local image ID")
    paths={entry.split(":",1)[0] for entry in service["tmpfs"]}
    required={"nosuid","nodev","noexec"}
    malformed=any("size=" not in item or "nr_inodes=" not in item
                  or not required<=set(item.split(",")) for item in service["tmpfs"])
    if paths!=WRITABLE_PATHS[name] or malformed or service.get("volumes"):
        raise ValueError(f"{name} mutable path policy drift")
    if name in {"wordpress","cli"} and service["image"]!=artifact_image:
        raise ValueError(f"{name} did not receive the exact derived artifact image")


def _validate_service_command(name,service,plugin_slug,runtime_profile,block_post_id):
    sleepers={"cli","browser"}
    if name in sleepers and (service["entrypoint"]!=["sleep"] or service["command"]!=["infinity"]):
        raise ValueError(f"{name} command drift")
    expected=_gateway_command(plugin_slug,runtime_profile,block_post_id)
    if name=="gateway" and (service["entrypoint"]!=["node"] or service["command"]!=expected):
        raise ValueError("gateway command drift")


def validate_compose(
    spec: dict, artifact_image:str, plugin_slug:str="runtime-plugin",
    runtime_profile:str=contract.STANDARD_PROFILE, block_post_id:int=0,
) -> bool:
    networks={name:{"driver":"bridge","driver_opts":dict(ISOLATED_BRIDGE_OPTIONS),
                    "internal":True}
              for name in ("backend","application","frontend")}
    if set(spec)!={"services","networks"} or spec.get("networks")!=networks:
        raise ValueError("unknown or non-internal final Compose topology")
    if set(spec["services"])!=set(SERVICE_NETWORKS):
        raise ValueError("final service inventory drift")
    for name,service in spec["services"].items():
        _validate_service_schema(name,service)
        _validate_service_limits(name,service)
        _validate_service_storage(name,service,artifact_image)
        _validate_service_command(name,service,plugin_slug,runtime_profile,block_post_id)
    return True


def write_compose(
    path, images: dict, identities: dict, artifact_image:str, plugin_slug:str,
    runtime_profile:str, block_post_id:int,
) -> dict:
    spec = build_compose(
        images, identities, artifact_image,plugin_slug,runtime_profile,block_post_id,
    )
    validate_compose(
        spec, artifact_image,plugin_slug,runtime_profile,block_post_id,
    )
    path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    return spec
