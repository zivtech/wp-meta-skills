"""Bounded allowlist diagnostics for generated dependency acquisition."""
from __future__ import annotations

import hashlib
import json
import re


_CURL_CATEGORIES = {
    5: "proxy-connect", 6: "dns", 7: "proxy-connect", 22: "http-status",
    28: "proxy-connect", 35: "tls", 51: "tls", 58: "tls", 60: "tls",
}
_PROXY_KEYS = ("accepted", "active", "completed", "rejected", "rejected_peer", "rejected_capacity", "rejected_handler")


def _stream_bytes(value):
    if isinstance(value, bytes): return value
    if isinstance(value, str): return value.encode("utf-8", "replace")
    return b""


def _sample(stdout, stderr):
    combined = stdout + b"\n" + stderr
    bounded = combined if len(combined) <= 8192 else combined[:4096] + combined[-4096:]
    return bounded.decode("utf-8", "replace").lower()


def _recognized_hosts(text, allowed_hosts):
    found = []
    for host in sorted(allowed_hosts):
        pattern = rf"(?<![a-z0-9.-]){re.escape(host.lower())}(?![a-z0-9.-])"
        if re.search(pattern, text): found.append(host.lower())
    return tuple(found)


def _classify(text):
    if any(item in text for item in ("api rate limit", "rate limit exceeded", "too many requests")):
        return "http-status", "rate-limit"
    if match := re.search(r"curl error\s+(\d{1,3})", text):
        code = int(match.group(1)); return _CURL_CATEGORIES.get(code, "unclassified"), f"curl-{code}"
    if match := re.search(r"(?:http(?:/\S+)?[ :]|status(?: code)?[ =])\s*([45]\d\d)\b", text):
        return "http-status", f"http-{match.group(1)}"
    if any(item in text for item in ("could not resolve host", "name or service not known")): return "dns", "resolver"
    if any(item in text for item in ("certificate", "ssl", "tls")): return "tls", "transport"
    if any(item in text for item in ("checksum verification", "content-length mismatch", "does not match its expected")): return "integrity", "artifact"
    if any(item in text for item in ("could not find a matching version", "your requirements could not be resolved")): return "dependency-resolution", "solver"
    if any(item in text for item in ("plugin blocked", "scripts are disabled", "not allowed")): return "policy", "denied"
    return "unclassified", "none"


def describe(profile, result, proxy_status=None):
    stdout = _stream_bytes(result.get("stdout")); stderr = _stream_bytes(result.get("stderr"))
    text = _sample(stdout, stderr); category, detail = _classify(text); hosts = _recognized_hosts(text, profile.allowed_hosts)
    code = result.get("returncode"); code = code if isinstance(code, int) and not isinstance(code, bool) else -1
    payload = {
        "category": category,
        "detail": detail,
        "hosts": list(hosts),
        "returncode": code,
        "stderr": {"bytes": len(stderr), "sha256": hashlib.sha256(stderr).hexdigest()},
        "stdout": {"bytes": len(stdout), "sha256": hashlib.sha256(stdout).hexdigest()},
    }
    if proxy_status is not None:
        payload["proxy_status"] = {key: proxy_status[key] if type(proxy_status.get(key)) is int and proxy_status[key] >= 0 else -1 for key in _PROXY_KEYS}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
