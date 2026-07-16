"""Projection contract from diagnostic resource ledgers to lifecycle evidence."""
import re

KINDS=frozenset({"container","network","lease"})
STATES=frozenset({"created","attached","detached","removed","retained"})
TERMINATIONS=frozenset({"whole-container-cleanup","pid-identity-loss","authenticated-kill","host-term","host-kill"})
ATTEMPTED={"container":re.compile(r"wp-(?:package|acquire-proxy)-[0-9a-f]{16}"),"network":re.compile(r"wp-acquire-(?:internal|egress)-[0-9a-f]{16}")}


def project(events,allow_termination=False):
    if type(events) is not list: raise ValueError("resource ledger must be a list")
    projected=[]
    for item in events:
        if type(item) is not dict or set(item)!={"kind","name","state"} or any(type(item[key]) is not str for key in item): raise ValueError("resource ledger record is malformed")
        kind,name,state=item["kind"],item["name"],item["state"]
        if kind=="termination":
            if not re.fullmatch(r"wp-acquire-proxy-[0-9a-f]{16}",name) or state not in TERMINATIONS: raise ValueError("resource termination diagnostic is invalid")
            if not allow_termination: raise ValueError("resource termination diagnostic is ineligible for a passing lifecycle")
            continue
        if kind not in KINDS or name.startswith("wp-proxy-preflight-"): raise ValueError("resource ledger kind or name is invalid")
        if state=="attempted":
            if kind not in ATTEMPTED or not ATTEMPTED[kind].fullmatch(name): raise ValueError("resource attempt identity is invalid")
            created=any(type(other) is dict and other.get("kind")==kind and other.get("name")==name and other.get("state")=="created" for other in events)
            if not created: raise ValueError("resource attempt has no matching created record")
            continue
        if state not in STATES: raise ValueError("resource ledger state is invalid")
        projected.append(dict(item))
    return projected
