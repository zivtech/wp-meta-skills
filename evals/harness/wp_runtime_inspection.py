"""Static-normalized and live inspection of the generated-code runtime."""
from __future__ import annotations

import json
from pathlib import Path

import runtime_image_provision as transport
import wp_runtime_topology as topology
from wp_runtime_evidence import RuntimeDeadline, scrub_tail

NORMALIZED_BASE={"image","read_only","cap_drop","security_opt","user","networks","tmpfs",
    "pids_limit","mem_limit","memswap_limit","cpus","ulimits","logging","init",
    "shm_size","entrypoint","command"}
NORMALIZED_EXTRAS={"database":set(),"wordpress":set(),"cli":set(),"gateway":set(),"browser":set()}


def _run(command: list[str], timeout: int = 60,deadline:RuntimeDeadline|None=None) -> dict:
    if deadline is not None: timeout=deadline.remaining(timeout)
    result = transport.run_capped(command, timeout=timeout, limit=131072)
    if result["returncode"]:
        detail = scrub_tail(
            (result.get("stderr") or "") + (result.get("stdout") or ""), 500,
        )
        raise RuntimeError(
            f"runtime inspection command failed rc={result['returncode']}: {detail}"
        )
    return result


def _normalized_mounts(service,values):
    if values: raise RuntimeError(f"normalized {service} mount inventory drift")


def _tmpfs_options(entries):
    result={}
    for entry in entries:
        path,raw=entry.split(":",1)
        options={}
        for item in raw.split(","):
            key,separator,value=item.partition("=")
            options[key]=value if separator else True
        result[path]=options
    return result


def _normalized_service(name,service,image,identity,expected_service):
    if set(service) != NORMALIZED_BASE|NORMALIZED_EXTRAS[name]:
        raise RuntimeError(f"normalized {name} field schema drift")
    if service["image"]!=image or service["cap_drop"] != ["ALL"]:
        raise RuntimeError(f"normalized {name} image or capability drift")
    if service["security_opt"] != ["no-new-privileges:true"] or not service["read_only"]:
        raise RuntimeError(f"normalized {name} security policy drift")
    expected_command={"database":None,"wordpress":None,"cli":["infinity"],
        "gateway":expected_service.get("command"),"browser":["infinity"]}
    expected_entrypoint={"database":None,"wordpress":None,"cli":["sleep"],
        "gateway":["node"],"browser":["sleep"]}
    expected_ulimits={"nofile":{"soft":1024,"hard":1024},"nproc":{"soft":256,"hard":256}}
    if (service["user"]!=identity or service["command"]!=expected_command[name]
            or service["entrypoint"]!=expected_entrypoint[name]):
        raise RuntimeError(f"normalized {name} identity or command drift")
    if (service["pids_limit"]!=128 or service["mem_limit"]!="536870912"
            or service["memswap_limit"]!="536870912" or service["cpus"]!=0.5
            or service["ulimits"]!=expected_ulimits or service["logging"]!={"driver":"none"}
            or service["init"] is not True or service["shm_size"]!="16777216"):
        raise RuntimeError(f"normalized {name} resource policy drift")
    if _tmpfs_options(service["tmpfs"])!=_tmpfs_options(expected_service["tmpfs"]):
        raise RuntimeError(f"normalized {name} tmpfs policy drift")
    networks=set(service["networks"] if isinstance(service["networks"],dict) else service["networks"])
    if networks != set(topology.SERVICE_NETWORKS[name]):
        raise RuntimeError(f"normalized {name} network drift")
    expected_networks = {
        "wordpress": {"backend": {},
                      "application": {"aliases": ["wordpress-application"]}},
        "gateway": {"application": {"aliases": ["gateway-application"]},
                    "frontend": {"aliases": ["gateway-frontend"]}},
    }.get(name, {network: None for network in networks})
    if service["networks"] != expected_networks:
        raise RuntimeError(f"normalized {name} network attachment options drift")
    _normalized_mounts(name,service.get("volumes",[]))


def inspect_normalized(base: list[str], images: dict[str, str], identities:dict[str,str], artifact_image:str,plugin_slug:str,deadline=None) -> dict:
    payload = _run(base + ["config", "--format", "json"],deadline=deadline)["stdout"]
    config = json.loads(payload)
    if set(config)!={"name","services","networks"} or not isinstance(config["name"],str):
        raise RuntimeError("normalized Compose top-level schema drift")
    if set(config.get("services", {})) != set(topology.SERVICE_NETWORKS):
        raise RuntimeError("normalized Compose service inventory drift")
    if set(config.get("networks", {})) != {"backend", "application", "frontend"}:
        raise RuntimeError("normalized Compose network inventory drift")
    if not all(set(value)=={"name","ipam","internal"} and value.get("internal") is True
               and value.get("ipam")=={} and isinstance(value.get("name"),str)
               for value in config["networks"].values()):
        raise RuntimeError("normalized Compose contains an external network")
    observed = {name: service.get("image") for name, service in config["services"].items()}
    expected = {"database": images["database"], "wordpress": artifact_image,
                "cli": artifact_image,"gateway":images["browser"],"browser": images["browser"]}
    if observed != expected:
        raise RuntimeError("normalized Compose image identity drift")
    expected_spec=topology.build_compose(images,identities,artifact_image,plugin_slug)
    for name,service in config["services"].items():
        identity=identities["wordpress"] if name=="cli" else identities["browser"] if name=="gateway" else identities[name]
        _normalized_service(name,service,expected[name],identity,expected_spec["services"][name])
    return {"services": sorted(observed), "images": observed, "networks": sorted(config["networks"])}


def _validate_live_host(service, inspected, image):
    host = inspected["HostConfig"]
    if inspected["Image"] != image or not host["ReadonlyRootfs"]:
        raise RuntimeError(f"{service} live image or root filesystem drift")
    if host["CapDrop"] != ["ALL"] or host.get("CapAdd") not in (None,[]) or host["PidsLimit"] != 128 or host["Memory"] != 536870912:
        raise RuntimeError(f"{service} live resource policy drift")
    if (host["MemorySwap"] != 536870912 or host["NanoCpus"] != 500000000
            or host["SecurityOpt"] != ["no-new-privileges:true"] or host.get("ShmSize")!=16777216):
        raise RuntimeError(f"{service} live CPU or security policy drift")
    ulimits={item["Name"]:(item["Soft"],item["Hard"]) for item in host.get("Ulimits") or []}
    if ulimits != {"nofile":(1024,1024),"nproc":(256,256)}:
        raise RuntimeError(f"{service} live file limit drift")
    if (host["LogConfig"]["Type"] != "none" or host.get("PortBindings") or host.get("ExtraHosts")
            or host.get("PublishAllPorts") or host.get("Dns") or host.get("DnsOptions") or host.get("DnsSearch")
            or host.get("Init") is not True):
        raise RuntimeError(f"{service} live logging or host surface drift")
    forbidden=(host.get("Devices"),host.get("DeviceRequests"),host.get("GroupAdd"),host.get("VolumesFrom"),host.get("Links"),host.get("Sysctls"))
    namespaces=(host.get("IpcMode"),host.get("PidMode"),host.get("UTSMode"),host.get("UsernsMode"))
    if any(forbidden) or any(value in {"host"} or str(value).startswith("container:") for value in namespaces) or host.get("Privileged"):
        raise RuntimeError(f"{service} live device, DNS, or privilege drift")
    return host


def _validate_live(service: str, inspected: dict, image: str, identity:str,
                   expected_service:dict, require_running:bool=True) -> dict:
    host = _validate_live_host(service, inspected, image)
    live_mounts=inspected.get("Mounts",[]); mounts={(item["Source"],item["Destination"]) for item in live_mounts}
    if mounts or live_mounts:
        raise RuntimeError(f"{service} live artifact mount drift")
    binds=host.get("Binds")
    if binds not in (None,[]):
        raise RuntimeError(f"{service} live bind inventory drift")
    tmpfs = host.get("Tmpfs") or {}
    observed_tmpfs=_tmpfs_options(f"{path}:{options}" for path,options in tmpfs.items())
    if observed_tmpfs != _tmpfs_options(expected_service["tmpfs"]):
        raise RuntimeError(f"{service} live tmpfs bound drift")
    if any(item.split("=", 1)[0].lower().endswith("proxy") for item in inspected["Config"].get("Env", [])):
        raise RuntimeError(f"{service} inherited a proxy variable")
    if inspected["Config"]["User"]!=identity:
        raise RuntimeError(f"{service} live user is not numeric and non-root")
    names = set(inspected["NetworkSettings"]["Networks"])
    expected = set(topology.SERVICE_NETWORKS[service])
    observed = {name.rsplit("_", 1)[-1] for name in names}
    if observed != expected:
        raise RuntimeError(f"{service} live network inventory drift")
    if not str(host.get("NetworkMode","")).endswith("_"+topology.PRIMARY_NETWORK[service]):
        raise RuntimeError(f"{service} live primary network mode drift")
    endpoints=inspected["NetworkSettings"]["Networks"]
    state=inspected.get("State",{}); running=state.get("Running") is True
    if require_running and not running:
        raise RuntimeError(f"{service} final container is not running")
    if not require_running and state.get("Status")!="created":
        raise RuntimeError(f"{service} pre-start container state drift")
    if require_running and any(not item.get("IPAddress") for item in endpoints.values()):
        raise RuntimeError(f"{service} live network address is missing")
    restart=host.get("RestartPolicy") or {}
    if restart != {"Name":"no","MaximumRetryCount":0}:
        raise RuntimeError(f"{service} live restart policy drift")
    return {"id":inspected["Id"],"image":inspected["Image"],"mounts":sorted(mounts),
            "networks":sorted(names),"addresses":{key:value["IPAddress"] for key,value in endpoints.items()}}


def _inspect_networks(evidence,project,deadline=None):
    names={name for item in evidence.values() for name in item["networks"]}
    result={}
    for name in names:
        network=json.loads(_run(["docker","network","inspect",name],deadline=deadline)["stdout"])[0]
        labels=network.get("Labels") or {}; actual=set((network.get("Containers") or {}).keys())
        key=name.rsplit("_",1)[-1]
        expected={item["id"] for service,item in evidence.items() if key in topology.SERVICE_NETWORKS[service]}
        if not network.get("Internal") or labels.get("com.docker.compose.project")!=project or actual!=expected:
            raise RuntimeError("live network identity, label, or member drift")
        result[name]={"id":network["Id"],"internal":True,"members":sorted(actual),
            "gateway":[item.get("Gateway") for item in (network.get("IPAM",{}).get("Config") or [])]}
    return result


def inspect_live(base: list[str], images: dict, identities:dict[str,str], artifact_image:str,
                 project:str,plugin_slug:str,deadline=None,require_running:bool=True) -> dict:
    expected = {"database": images["database"], "wordpress": artifact_image,
                "cli": artifact_image,"gateway":images["browser"],"browser": images["browser"]}
    expected_spec=topology.build_compose(images,identities,artifact_image,plugin_slug)
    evidence = {}
    for service, image in expected.items():
        container = _run(
            base + ["ps", "-q", "--all", service], deadline=deadline,
        )["stdout"].strip()
        if not container:
            raise RuntimeError(f"{service} final container is missing")
        inspected = json.loads(_run(["docker", "inspect", container],deadline=deadline)["stdout"])[0]
        identity=identities["wordpress"] if service=="cli" else identities["browser"] if service=="gateway" else identities[service]
        evidence[service] = _validate_live(
            service,inspected,image,identity,expected_spec["services"][service],require_running
        )
        if inspected.get("State",{}).get("Running"):
            status=_run(["docker","exec",container,"sh","-c","grep '^Seccomp:' /proc/1/status"],deadline=deadline)["stdout"].strip()
            if status!="Seccomp:\t2": raise RuntimeError(f"{service} live seccomp is not filtering")
            evidence[service]["seccomp"]=2
    networks=_inspect_networks(evidence,project,deadline) if require_running else {}
    return {"services":evidence,"networks":networks,"require_running":require_running}


def inspect_named_canary(base: list[str], service: str, name: str,
                         deadline: RuntimeDeadline) -> dict:
    """Prove a running Compose one-off has the service's full sandbox profile."""
    inspected = json.loads(_run(
        ["docker", "inspect", name], deadline=deadline,
    )["stdout"])[0]
    candidates = _run(
        base + ["ps", "-q", "--all", service], deadline=deadline,
    )["stdout"].split()
    references = [candidate for candidate in candidates if candidate != inspected["Id"]]
    if len(references) != 1:
        raise RuntimeError(f"{service} reference container inventory is not exact")
    reference_id = references[0]
    reference = json.loads(_run(
        ["docker", "inspect", reference_id], deadline=deadline,
    )["stdout"])[0]
    tmpfs = reference["HostConfig"].get("Tmpfs") or {}
    expected_service = {"tmpfs": [
        f"{path}:{options}" for path, options in sorted(tmpfs.items())
    ]}
    evidence = _validate_live(
        service, inspected, reference["Image"], reference["Config"]["User"],
        expected_service, True,
    )
    status = _run(
        ["docker", "exec", name, "sh", "-c", "grep '^Seccomp:' /proc/1/status"],
        deadline=deadline,
    )["stdout"].strip()
    if status != "Seccomp:\t2":
        raise RuntimeError(f"named {service} canary seccomp is not filtering")
    evidence["seccomp"] = 2
    evidence["profile_source"] = reference_id
    return evidence
