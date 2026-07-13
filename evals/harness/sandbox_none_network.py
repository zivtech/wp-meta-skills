"""Daemon-bound Docker 28 inspection gates for a running --network none endpoint."""
from __future__ import annotations

import json
import re
import time

import sandbox_python_preflight as preflight


class DaemonIdentityError(RuntimeError):
    """The authenticated Docker daemon became unavailable or changed."""


def _remaining(deadline):
    value=deadline-time.monotonic()
    if value<=0: raise TimeoutError("none-network inspection deadline exceeded")
    return min(30,value)


def _command(run,command,deadline,label):
    result=run(command,_remaining(deadline))
    if result.get("returncode") or result.get("stderr"):
        raise RuntimeError(f"{label} command failed")
    return result.get("stdout")


def _daemon(run,deadline):
    payload=_command(run,["docker","info","--format",preflight.DAEMON_ID_TEMPLATE],deadline,"Docker daemon identity")
    return preflight._strict_daemon_id(payload)


def require_daemon(run,expected,deadline,taint=lambda:None):
    try: observed=_daemon(run,deadline)
    except Exception as exc:
        taint(); raise DaemonIdentityError("Docker daemon identity unavailable; boundary unverified") from exc
    if observed!=expected:
        taint(); raise DaemonIdentityError("Docker daemon identity changed; boundary unverified")


def _network(run,deadline):
    payload=_command(run,["docker","network","inspect","none"],deadline,"none-network inspection")
    try: values=json.loads(payload,object_pairs_hook=preflight._unique_object,parse_constant=lambda token:(_ for _ in ()).throw(ValueError(token)))
    except (TypeError,ValueError,json.JSONDecodeError) as exc: raise RuntimeError("none-network inspection is malformed") from exc
    value=values[0] if type(values) is list and len(values)==1 and type(values[0]) is dict else None
    if value is None or value.get("Name")!="none" or value.get("Driver")!="null" or value.get("Scope")!="local" or re.fullmatch(r"[0-9a-f]{64}",value.get("Id", "")) is None:
        raise RuntimeError("none-network identity drift")
    return value


def admit(run,deadline,taint=lambda:None):
    daemon_id=_daemon(run,deadline); network=_network(run,deadline)
    require_daemon(run,daemon_id,deadline,taint)
    payload=_command(run,["docker","version","--format",preflight.ENGINE_TEMPLATE],deadline,"Docker engine tuple")
    if preflight._strict_engine(payload)!=preflight.HOSTED_28_ENGINE:
        raise RuntimeError("Docker engine tuple is not the reviewed hosted profile")
    require_daemon(run,daemon_id,deadline,taint)
    return daemon_id,network["Id"],preflight.HOSTED_28_ENGINE[-1]


def _endpoint(value,network_id):
    endpoint=value.get("none") if type(value) is dict and set(value)=={"none"} else None
    if type(endpoint) is not dict: raise RuntimeError("running none-network endpoint drift")
    endpoint_id=endpoint.get("EndpointID")
    expected={
        "IPAMConfig":None,"Links":None,"Aliases":None,"MacAddress":"",
        "NetworkID":network_id,"EndpointID":endpoint_id,"Gateway":"","IPAddress":"",
        "IPPrefixLen":0,"IPv6Gateway":"","GlobalIPv6Address":"",
        "GlobalIPv6PrefixLen":0,"DriverOpts":None,"DNSNames":None,"GwPriority":0,
    }
    exact_id=type(endpoint_id) is str and re.fullmatch(r"[0-9a-f]{64}",endpoint_id) is not None
    exact_integers=all(type(endpoint.get(key)) is int and endpoint[key]==0 for key in ("IPPrefixLen","GlobalIPv6PrefixLen","GwPriority"))
    if not exact_id or not exact_integers or endpoint!=expected:
        fields=sorted(endpoint) if all(type(key) is str and key.isascii() for key in endpoint) else []
        raise RuntimeError(f"running none-network endpoint drift (field_count={len(endpoint)} fields={','.join(fields)[:512]})")
    return endpoint_id


def require_running(run,data,name,network_id,daemon_id,deadline,taint=lambda:None):
    container_id=data.get("Id") if type(data) is dict else None
    exact_container=type(container_id) is str and re.fullmatch(r"[0-9a-f]{64}",container_id) is not None
    if not exact_container or data.get("Name")!=f"/{name}": raise RuntimeError("running none-network container identity drift")
    endpoint_id=_endpoint(data.get("NetworkSettings",{}).get("Networks"),network_id)
    require_daemon(run,daemon_id,deadline,taint); network=_network(run,deadline); require_daemon(run,daemon_id,deadline,taint)
    record=network.get("Containers",{}).get(container_id) if type(network.get("Containers")) is dict else None
    expected={"Name":name,"EndpointID":endpoint_id,"MacAddress":"","IPv4Address":"","IPv6Address":""}
    if network["Id"]!=network_id or record!=expected: raise RuntimeError("running none-network cross-inspection drift")
    return endpoint_id
