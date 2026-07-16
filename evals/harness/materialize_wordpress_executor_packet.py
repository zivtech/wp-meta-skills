#!/usr/bin/env python3
"""Materialize WordPress executor packets into generated artifact files.

This is the bridge between the saved packet oracle and the generated artifact
oracle. It intentionally supports a narrow packet syntax:

    ### path/to/file.php
    ```php
    <?php
    // file contents
    ```

For Blueprint packets, it extracts the fenced JSON object from the Generated
Blueprint section and writes it as blueprint.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import validate_wordpress_executor_packet


ROOT = Path(__file__).resolve().parents[2]
APPROVED_LOCK_ROOT = Path(__file__).resolve().parent / "approved-locks"
APPROVED_LOCKS = {
    "block-scripts-32.4.1-smoke": ("block-scripts-32.4.1-smoke.package-lock.json", "package-lock.json", "package.json"),
    "block-interactivity-6.48.1": ("block-interactivity-6.48.1.package-lock.json", "package-lock.json", "package.json"),
    "block-scripts-32.4.1-deprecation": ("block-scripts-32.4.1-deprecation.package-lock.json", "package-lock.json", "package.json"),
    "plugin-phpunit-12.5.31": ("plugin-phpunit-12.5.31.composer.lock", "acme-runtime-tested/composer.lock", "acme-runtime-tested/composer.json"),
}
SECTION_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")
PATH_HEADING_RE = re.compile(r"(?m)^(?:#{3,6}|[-*])\s+`?([A-Za-z0-9_./-]+\.[A-Za-z0-9_+-]+)`?\s*$")
SAFE_SUFFIXES = {
    ".php",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".xml",
    ".css",
    ".scss",
    ".md",
    ".txt",
    ".html",
    ".lock",
}
PACKET_SECTIONS = {
    "plugin": ("Implementation Packets",),
    "block": ("Generated Block Files",),
    "blueprint": ("Generated Blueprint",),
}


@dataclass(frozen=True)
class MaterializedFile:
    path: str
    bytes: int


@dataclass(frozen=True)
class MaterializationIssue:
    status: str
    detail: str


def sections(text: str) -> dict[str, str]:
    matches = list(SECTION_RE.finditer(text))
    out: dict[str, str] = {}
    for idx, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        out[name] = text[start:end].strip()
    return out


def safe_relative_path(raw_path: str) -> Path:
    path = Path(raw_path.strip().strip("`"))
    if path.is_absolute():
        raise ValueError(f"absolute paths are not allowed: {raw_path}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"path traversal or empty path segment is not allowed: {raw_path}")
    if path.suffix.lower() not in SAFE_SUFFIXES:
        raise ValueError(f"unsupported generated file suffix: {raw_path}")
    return path


def first_fence_after(text: str, start: int) -> tuple[str, int] | None:
    cursor = start
    while cursor < len(text) and text[cursor] in " \t\r\n":
        cursor += 1
    if not text.startswith("```", cursor):
        return None
    opener_end = text.find("\n", cursor)
    if opener_end == -1:
        return None
    content_start = opener_end + 1
    close_start = text.find("\n```", content_start)
    if close_start == -1:
        return None
    return text[content_start:close_start], close_start + 4


def extract_file_blocks(section_text: str) -> tuple[list[tuple[Path, str]], list[MaterializationIssue]]:
    blocks: list[tuple[Path, str]] = []
    issues: list[MaterializationIssue] = []
    seen: set[Path] = set()
    for match in PATH_HEADING_RE.finditer(section_text):
        raw_path = match.group(1)
        try:
            rel_path = safe_relative_path(raw_path)
        except ValueError as exc:
            issues.append(MaterializationIssue("fail", str(exc)))
            continue
        if rel_path in seen:
            issues.append(MaterializationIssue("fail", f"duplicate generated file path: {rel_path}"))
            continue
        fence = first_fence_after(section_text, match.end())
        if fence is None:
            issues.append(MaterializationIssue("fail", f"no fenced code block found after {raw_path}"))
            continue
        content, _end = fence
        blocks.append((rel_path, content.rstrip() + "\n"))
        seen.add(rel_path)
    return blocks, issues


def resolve_approved_locks(blocks: list[tuple[Path, str]]) -> tuple[list[tuple[Path, str]], list[MaterializationIssue]]:
    by_path = {str(path): content for path, content in blocks}
    resolved = []
    issues = []
    for path, content in blocks:
        if path.suffix != ".lock" and path.name != "package-lock.json":
            resolved.append((path, content)); continue
        try:
            profile = json.loads(content)
            if profile.get("kind") != "approved-lock-profile":
                resolved.append((path, content)); continue
            if set(profile) != {"kind","version","approved_lock_profile","sha256","manifest_sha256"} or profile["version"] != 1:
                raise ValueError("approved lock profile envelope is not exact version 1")
            profile_id = profile["approved_lock_profile"]
            filename, expected_target, manifest_path = APPROVED_LOCKS[profile_id]
            if str(path) != expected_target:
                raise ValueError("approved lock target does not match registry")
            canonical = (APPROVED_LOCK_ROOT / filename).read_bytes()
            if hashlib.sha256(canonical).hexdigest() != profile["sha256"]:
                raise ValueError("approved lock digest mismatch")
            manifest = by_path.get(manifest_path)
            if manifest is None or hashlib.sha256(manifest.encode()).hexdigest() != profile["manifest_sha256"]:
                raise ValueError("approved lock manifest binding mismatch")
            resolved.append((path, canonical.decode("utf-8")))
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            issues.append(MaterializationIssue("fail", f"invalid approved lock profile for {path}: {exc}"))
    return resolved, issues


def materialize_files(blocks: list[tuple[Path, str]], out_dir: Path) -> list[MaterializedFile]:
    written: list[MaterializedFile] = []
    for rel_path, content in blocks:
        target = out_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(MaterializedFile(str(rel_path), len(content.encode("utf-8"))))
    return written


def materialize_blueprint(text: str, out_dir: Path) -> tuple[list[MaterializedFile], list[MaterializationIssue]]:
    parsed, detail = validate_wordpress_executor_packet.extract_blueprint_json(text)
    if parsed is None:
        return [], [MaterializationIssue("fail", detail)]
    target = out_dir / "blueprint.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(parsed, indent=2, sort_keys=True) + "\n"
    target.write_text(content, encoding="utf-8")
    return [MaterializedFile("blueprint.json", len(content.encode("utf-8")))], []


def materialize_packet(executor: str, packet_text: str, out_dir: Path, overwrite: bool = False) -> dict[str, Any]:
    if executor not in PACKET_SECTIONS:
        raise ValueError(f"unknown executor `{executor}`")
    if out_dir.exists() and any(out_dir.iterdir()) and not overwrite:
        return {
            "executor": executor,
            "out_dir": str(out_dir),
            "status": "fail",
            "pass": False,
            "written": [],
            "issues": [asdict(MaterializationIssue("fail", "output directory exists and is not empty; pass --overwrite to replace it"))],
        }
    if out_dir.exists() and overwrite:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    packet_sections = sections(packet_text)
    if executor == "blueprint":
        written, issues = materialize_blueprint(packet_text, out_dir)
    else:
        section_name = PACKET_SECTIONS[executor][0]
        section_text = packet_sections.get(section_name, "")
        if not section_text:
            issues = [MaterializationIssue("fail", f"missing section: {section_name}")]
            written = []
        else:
            blocks, issues = extract_file_blocks(section_text)
            blocks, lock_issues = resolve_approved_locks(blocks)
            issues.extend(lock_issues)
            written = materialize_files(blocks, out_dir) if not any(issue.status == "fail" for issue in issues) else []

    if not written and not issues:
        issues = [MaterializationIssue("fail", "no materializable generated files found")]
    status = "pass" if written and not any(issue.status == "fail" for issue in issues) else "fail"
    return {
        "executor": executor,
        "out_dir": str(out_dir),
        "status": status,
        "pass": status == "pass",
        "written": [asdict(item) for item in written],
        "issues": [asdict(issue) for issue in issues],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize WordPress executor packets into generated artifacts.")
    parser.add_argument("--executor", choices=sorted(PACKET_SECTIONS), required=True)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output directory.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    packet_text = args.packet.read_text(encoding="utf-8")
    result = materialize_packet(args.executor, packet_text, args.out_dir, args.overwrite)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
