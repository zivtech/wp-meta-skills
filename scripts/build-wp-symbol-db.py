#!/usr/bin/env python3
"""Build the deterministic WordPress core-symbol snapshot from pinned sources.

This maintainer command fetches two immutable MIT-licensed inputs through the
bounded public transport, verifies their bytes, and introspects the stubs in the
reviewed Composer/PHP container. Ordinary CI validates the committed snapshot;
it does not perform this network rebuild.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "evals" / "harness"
sys.path.insert(0, str(HARNESS))

import safe_curl  # noqa: E402

DEFAULT_OUT = HARNESS / "data" / "wp-symbols.json"
LOCK_PATH = HARNESS / "php-tools" / "composer.lock"
INVENTORY_PATH = HARNESS / "container-images.json"
CANONICAL_COMMAND = (
    "python3 scripts/build-wp-symbol-db.py --wp-version 7.0 "
    "--out evals/harness/data/wp-symbols.json"
)


@dataclass(frozen=True)
class SourceSpec:
    package: str
    version: str
    commit: str
    url: str
    license: str
    sha256: str


SOURCES = {
    "wordpress_stubs": SourceSpec(
        "php-stubs/wordpress-stubs",
        "v7.0.0",
        "d74b963ed4f47303859bf73c741c80f554c83dc6",
        "https://raw.githubusercontent.com/php-stubs/wordpress-stubs/"
        "d74b963ed4f47303859bf73c741c80f554c83dc6/wordpress-stubs.php",
        "MIT",
        "1fa69deee70f8a1be7e3a0498327ca16e36ee2b5c243a5b2ab1926bec456fd44",
    ),
    "wp_compat": SourceSpec(
        "johnbillion/wp-compat",
        "1.5.0",
        "2ccebedbbbc6b6eec3fba4a568cff0a4ec05bf6e",
        "https://raw.githubusercontent.com/johnbillion/wp-compat/"
        "2ccebedbbbc6b6eec3fba4a568cff0a4ec05bf6e/symbols.json",
        "MIT",
        "d5f7210cb8804263f71b888d1f34cd7593c4d166077efa055a9232ce2327a298",
    ),
}

INTROSPECT_PHP = r"""<?php
$stubs = $argv[1];
$builtins = get_defined_functions()["internal"];
$before = array_merge(get_declared_classes(), get_declared_interfaces(), get_declared_traits());
require $stubs;
$functions = [];
foreach (get_defined_functions()["user"] as $fn) {
    $entry = [];
    try { $doc = (string) (new ReflectionFunction($fn))->getDocComment(); }
    catch (ReflectionException $e) { $doc = ""; }
    if (preg_match('/@deprecated\s+(\d+[\d.]*)([^\n]*)/', $doc, $m)) {
        $entry["deprecated"] = $m[1];
        if (preg_match('/([A-Za-z_][A-Za-z0-9_:\\\\>-]*)\s*\(\)/', $m[2], $r)) {
            $entry["replacement"] = $r[1] . "()";
        }
    }
    $functions[strtolower($fn)] = empty($entry) ? new stdClass() : $entry;
}
$classes = [];
$after = array_merge(get_declared_classes(), get_declared_interfaces(), get_declared_traits());
foreach (array_diff($after, $before) as $cls) { $classes[strtolower($cls)] = new stdClass(); }
echo json_encode(["php_builtins" => array_map("strtolower", $builtins),
    "functions" => $functions, "classes" => $classes], JSON_THROW_ON_ERROR);
"""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def symbol_digest(snapshot: dict[str, Any]) -> str:
    symbols = {"functions": snapshot.get("functions"), "classes": snapshot.get("classes")}
    return hashlib.sha256(_canonical_json(symbols)).hexdigest()


def fetch_source(spec: SourceSpec) -> bytes:
    parsed = urlsplit(spec.url)
    policy = safe_curl.CurlPolicy(
        ("https://raw.githubusercontent.com",),
        (parsed.path,),
        16 * 1024 * 1024,
        10,
    )
    request = safe_curl.CurlRequest("GET", spec.url, policy, timeout_seconds=120)
    result = safe_curl.execute(request)
    if not result.ok:
        raise RuntimeError(f"pinned source fetch failed: {result.error_code}")
    if hashlib.sha256(result.body).hexdigest() != spec.sha256:
        raise RuntimeError("pinned source SHA-256 mismatch")
    return result.body


def _docker_executable() -> str:
    candidate = shutil.which("docker")
    if not candidate:
        raise RuntimeError("Docker CLI is unavailable")
    resolved = Path(candidate).resolve(strict=True)
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise RuntimeError("Docker CLI is not an executable file")
    if resolved.stat().st_mode & 0o022:
        raise RuntimeError("Docker CLI is group/world writable")
    return str(resolved)


def _run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("bounded Docker command timed out") from exc


def _container_identity(docker: str) -> tuple[str, dict[str, Any]]:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    item = inventory["images"]["composer"]
    version = _run([docker, "version", "--format", "{{.Server.Arch}}"])
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        version.stdout.strip().lower()
    )
    if version.returncode or arch is None:
        raise RuntimeError("unsupported or unavailable Docker daemon architecture")
    image = f"composer@{item[arch]}"
    inspected = _run([docker, "image", "inspect", image, "--format", "{{json .RepoDigests}}"])
    try:
        repo_digests = json.loads(inspected.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("pinned Composer image inspection failed") from exc
    if inspected.returncode or not any(value.endswith(f"@{item[arch]}") for value in repo_digests):
        raise RuntimeError("pinned Composer image is not locally provisioned")
    return image, item


def introspect_stubs(stubs: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    docker = _docker_executable()
    image, container = _container_identity(docker)
    name = f"wp-symbol-db-{uuid.uuid4().hex[:16]}"
    with tempfile.TemporaryDirectory(prefix="wp-symbol-db-") as directory:
        root = Path(directory)
        (root / "wordpress-stubs.php").write_bytes(stubs)
        (root / "introspect.php").write_text(INTROSPECT_PHP, encoding="utf-8")
        command = _introspection_command(docker, name, image, root)
        try:
            result = _run(command, timeout=600)
        finally:
            _run([docker, "rm", "--force", name], timeout=30)
    if result.returncode:
        raise RuntimeError(f"PHP introspection failed: {result.stderr[-2000:]}")
    try:
        return json.loads(result.stdout), container
    except json.JSONDecodeError as exc:
        raise RuntimeError("PHP introspection returned malformed JSON") from exc


def _introspection_command(docker: str, name: str, image: str, root: Path) -> list[str]:
    return [
        docker, "run", "--rm", "--name", name, "--pull", "never", "--network", "none",
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "64", "--memory", "1g", "--memory-swap", "1g", "--cpus", "2",
        "--user", f"{os.getuid()}:{os.getgid()}", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m",
        "--mount", f"type=bind,src={root},dst=/input,readonly", "--entrypoint", "php", image,
        "-d", "memory_limit=1G", "/input/introspect.php", "/input/wordpress-stubs.php",
    ]


def _source_metadata(spec: SourceSpec) -> dict[str, str]:
    return {
        "package": spec.package,
        "version": spec.version,
        "commit": spec.commit,
        "url": spec.url,
        "license": spec.license,
        "sha256": spec.sha256,
    }


def build_snapshot(stubs: bytes, compat_bytes: bytes) -> dict[str, Any]:
    introspected, container = introspect_stubs(stubs)
    compat = json.loads(compat_bytes)
    functions = introspected["functions"]
    for symbol, meta in compat.get("symbols", {}).items():
        name = symbol.lower()
        if "::" not in symbol and meta.get("since") and name in functions:
            functions[name] = dict(functions[name] or {})
            functions[name]["since"] = meta["since"]
    snapshot = {
        "schema_version": 1,
        "wp_version": "7.0",
        "sources": {key: _source_metadata(spec) for key, spec in SOURCES.items()},
        "generator": {
            "schema_version": 1,
            "version": 1,
            "command": CANONICAL_COMMAND,
            "container": {
                "inventory_key": "composer",
                "index": container["index"],
                "platform_digests": {"amd64": container["amd64"], "arm64": container["arm64"]},
            },
        },
        "php_builtins": sorted(set(introspected["php_builtins"])),
        "functions": {name: functions[name] or {} for name in sorted(functions)},
        "classes": {name: introspected["classes"][name] or {} for name in sorted(introspected["classes"])},
    }
    snapshot["generator"]["symbols_sha256"] = symbol_digest(snapshot)
    return snapshot


def _lock_packages() -> dict[str, dict[str, Any]]:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    return {item["name"]: item for item in lock.get("packages", [])}


def _validate_source_metadata(snapshot: dict[str, Any]) -> None:
    packages = _lock_packages()
    sources = snapshot.get("sources")
    if not isinstance(sources, dict) or set(sources) != set(SOURCES):
        raise ValueError("source metadata is incomplete")
    for key, spec in SOURCES.items():
        actual = sources.get(key)
        if not isinstance(actual, dict) or set(actual) != set(_source_metadata(spec)):
            raise ValueError("source metadata is incomplete")
        if actual.get("url") != spec.url:
            raise ValueError("source immutable URL does not match the reviewed commit")
        locked = packages.get(spec.package, {})
        locked_version = locked.get("version")
        locked_commit = locked.get("source", {}).get("reference")
        if (actual.get("package"), actual.get("version"), actual.get("commit")) != (
            spec.package, locked_version, locked_commit
        ) or (locked_version, locked_commit) != (spec.version, spec.commit):
            raise ValueError("source metadata does not match Composer lock")
        if actual.get("license") != spec.license or actual.get("sha256") != spec.sha256:
            raise ValueError("source metadata does not match the reviewed input")


def _validate_container(generator: Any) -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))["images"]["composer"]
    expected = {
        "inventory_key": "composer",
        "index": inventory["index"],
        "platform_digests": {"amd64": inventory["amd64"], "arm64": inventory["arm64"]},
    }
    if not isinstance(generator, dict) or generator.get("container") != expected:
        raise ValueError("generator container inventory does not match")
    if (
        generator.get("command") != CANONICAL_COMMAND
        or generator.get("schema_version") != 1
        or generator.get("version") != 1
    ):
        raise ValueError("generator metadata does not match the canonical rebuild")


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    if snapshot.get("schema_version") != 1:
        raise ValueError("unsupported symbol snapshot schema")
    if snapshot.get("wp_version") != "7.0":
        raise ValueError("WordPress version must be 7.0")
    _validate_source_metadata(snapshot)
    generator = snapshot.get("generator")
    _validate_container(generator)
    for key in ("php_builtins", "functions", "classes"):
        value = snapshot.get(key)
        if not isinstance(value, (list if key == "php_builtins" else dict)):
            raise ValueError(f"symbol snapshot {key} is malformed")
        names = value if isinstance(value, list) else list(value)
        if names != sorted(names) or len(names) != len(set(names)):
            raise ValueError(f"symbol snapshot {key} contains duplicate or unsorted symbols")
    if generator.get("symbols_sha256") != symbol_digest(snapshot):
        raise ValueError("symbol digest does not match normalized functions/classes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stubs", default=SOURCES["wordpress_stubs"].url)
    parser.add_argument("--wp-compat", default=SOURCES["wp_compat"].url)
    parser.add_argument("--wp-version", required=True)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    if args.wp_version != "7.0":
        parser.error("--wp-version must be 7.0")
    if args.stubs != SOURCES["wordpress_stubs"].url or args.wp_compat != SOURCES["wp_compat"].url:
        parser.error("source overrides must equal the reviewed immutable URLs")
    snapshot = build_snapshot(fetch_source(SOURCES["wordpress_stubs"]), fetch_source(SOURCES["wp_compat"]))
    validate_snapshot(snapshot)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(_canonical_json(snapshot) + b"\n")
    print(f"Wrote {out} — WP 7.0: {len(snapshot['functions'])} functions, {len(snapshot['classes'])} classes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
