"""Exact and sanitized Docker bind-mount policy checks."""
from __future__ import annotations

import json


PROPAGATION = "rprivate"
DETAIL_LIMIT = 512


def bind_spec(source, target):
    return f"type=bind,src={source},dst={target},readonly,bind-propagation={PROPAGATION}"


def _json_type(value):
    if value is None: return "null"
    if isinstance(value, bool): return "boolean"
    if isinstance(value, dict): return "object"
    if isinstance(value, list): return "array"
    if isinstance(value, str): return "string"
    if isinstance(value, (int, float)): return "number"
    return "unknown"


def _enum(value, expected):
    if value is None: return "absent"
    if value == expected: return expected
    return "other"


def _shape(mounts, source, target, live):
    count = len(mounts) if isinstance(mounts, list) else None
    mount = mounts[0] if count == 1 and isinstance(mounts[0], dict) else {}
    options = mount.get("BindOptions") if not live else None
    propagation = mount.get("Propagation") if live else options.get("Propagation") if isinstance(options, dict) else None
    destination = mount.get("Destination") if live else mount.get("Target")
    read_only = not mount.get("RW") if live and isinstance(mount.get("RW"), bool) else mount.get("ReadOnly")
    return {
        "inventory_json_type": _json_type(mounts),
        "entry_count": count,
        "entry_json_type": _json_type(mounts[0]) if count == 1 else "absent",
        "type": _enum(mount.get("Type"), "bind"),
        "source_matches": mount.get("Source") == source,
        "target_matches": destination == target,
        "read_only": read_only if isinstance(read_only, bool) else "other",
        "propagation": _enum(propagation, PROPAGATION),
    }


def _reject(label, mounts, source, target, live):
    detail = json.dumps(_shape(mounts, source, target, live), sort_keys=True, separators=(",", ":"))
    raise RuntimeError(f"{label} drift: {detail[:DETAIL_LIMIT]}")


def require_configured(mounts, source, target, label):
    if not isinstance(mounts, list) or len(mounts) != 1 or not isinstance(mounts[0], dict):
        _reject(label, mounts, source, target, False)
    mount = mounts[0]; options = mount.get("BindOptions")
    valid = (
        mount.get("Type") == "bind"
        and mount.get("Source") == source
        and mount.get("Target") == target
        and mount.get("ReadOnly") is True
        and isinstance(options, dict)
        and options.get("Propagation") == PROPAGATION
    )
    if not valid: _reject(label, mounts, source, target, False)


def require_live(mounts, source, target, label):
    if not isinstance(mounts, list) or len(mounts) != 1 or not isinstance(mounts[0], dict):
        _reject(label, mounts, source, target, True)
    mount = mounts[0]
    valid = (
        mount.get("Type") == "bind"
        and mount.get("Source") == source
        and mount.get("Destination") == target
        and mount.get("RW") is False
        and mount.get("Propagation") == PROPAGATION
    )
    if not valid: _reject(label, mounts, source, target, True)
