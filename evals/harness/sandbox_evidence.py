"""Canonical bounded-shape evidence payloads for package sandbox runs."""
from __future__ import annotations

import json


def encode(outcome, timings=None, metrics=None, error=None, resources=None):
    payload = {
        "outcome": outcome,
        "timings_seconds": dict(timings or {}),
        "metrics": dict(metrics or {}),
        "errors": [error] if error else [],
        "resource_events": list(resources or []),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def decode(detail):
    try:
        payload = json.loads(detail)
        if not isinstance(payload, dict) or not isinstance(payload.get("timings_seconds"), dict) or not isinstance(payload.get("metrics"), dict):
            raise ValueError("invalid evidence")
        payload.setdefault("errors", [])
        return payload
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"outcome": "unknown", "timings_seconds": {}, "metrics": {}, "errors": [str(detail)]}


def finalize(detail, *, outcome=None, error=None, timing=None, end_to_end=None, resources=None):
    payload = decode(detail)
    if outcome and payload.get("outcome") != outcome:
        payload["prior_outcome"] = payload.get("outcome")
        payload["outcome"] = outcome
    if error:
        payload["errors"].append(error)
    if timing:
        payload["timings_seconds"].update(timing)
    if end_to_end is not None:
        payload["timings_seconds"]["end_to_end"] = end_to_end
    if resources:
        payload.setdefault("resource_events", []).extend(resources)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
