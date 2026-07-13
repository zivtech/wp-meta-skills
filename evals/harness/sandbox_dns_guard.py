"""Fail-closed DNS configuration and lookup proof for acquisition containers."""
from __future__ import annotations

import json
import uuid


def pre_acquisition(name, kind, run):
    inspected = run(["docker", "inspect", name], 30)
    if inspected["returncode"]:
        raise RuntimeError("pre-acquisition DNS inspection failed")
    data = json.loads(inspected["stdout"])[0]
    if data["HostConfig"].get("Dns") != ["127.0.0.1"]:
        raise RuntimeError("pre-acquisition HostConfig DNS drift")
    resolv = run(["docker", "exec", name, "cat", "/etc/resolv.conf"], 5)
    required = ("nameserver 127.0.0.11", "ExtServers: [127.0.0.1]")
    if resolv["returncode"] or any(item not in resolv["stdout"] for item in required):
        raise RuntimeError("pre-acquisition resolver stub or upstream drift")
    domain = f"wp-pre-acquire-{uuid.uuid4().hex}.invalid"
    result = run(_lookup_command(name, kind, domain), 10)
    if result["returncode"]:
        raise RuntimeError("pre-acquisition A and AAAA denial failed")


def _lookup_command(name, kind, domain):
    if kind == "npm":
        script = """const d=require('dns'),q=%s;let n=2,b=false;
const done=(e)=>{if(!e)b=true;if(!--n)process.exit(b?1:0)};
d.resolve4(q,done);d.resolve6(q,done);setTimeout(()=>process.exit(2),1800);""" % json.dumps(domain)
        return ["docker", "exec", name, "timeout", "2", "node", "-e", script]
    script = "$h=%s;$r=@dns_get_record($h,DNS_A|DNS_AAAA);exit(($r===false||count($r)===0)?0:1);" % json.dumps(domain)
    return ["docker", "exec", name, "timeout", "8", "php", "-r", script]
