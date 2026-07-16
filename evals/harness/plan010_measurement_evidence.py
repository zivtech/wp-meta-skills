"""Toolchain identity for Plan 010 certification measurements."""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

import wp_api_lint
from bounded_subprocess import run_bounded


def _command_version(command: list[str]) -> str | None:
    try:
        result = run_bounded(
            command,
            deadline_monotonic=time.monotonic() + 5,
            stdout_limit=16 * 1024,
            stderr_limit=16 * 1024,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or result.stderr).strip().splitlines()[0][:200]


def toolchain_evidence() -> dict[str, Any]:
    lock_path = wp_api_lint.DEFAULT_PHP_TOOLS_ROOT / "composer.lock"
    content = lock_path.read_bytes()
    lock = json.loads(content)
    package_names = {
        "phpstan/phpstan",
        "squizlabs/php_codesniffer",
        "wp-coding-standards/wpcs",
    }
    packages = {
        item["name"]: item["version"]
        for item in lock.get("packages", [])
        if item.get("name") in package_names
    }
    commit_sha = os.environ.get("REVIEWED_COMMIT_SHA") \
        or os.environ.get("GITHUB_SHA") or "local-unrecorded"
    php = _command_version(["php", "--version"])
    composer = _command_version(["composer", "--version", "--no-ansi"])
    missing = [name for name in package_names if name not in packages]
    if php is None:
        missing.append("php")
    if composer is None:
        missing.append("composer")
    if os.environ.get("GITHUB_ACTIONS") == "true" and commit_sha == "local-unrecorded":
        missing.append("reviewed_commit_sha")
    return {
        "status": "pass" if not missing else "fail",
        "missing": sorted(missing),
        "commit_sha": commit_sha,
        "composer_lock_sha256": hashlib.sha256(content).hexdigest(),
        "php": php,
        "composer": composer,
        "packages": packages,
    }
