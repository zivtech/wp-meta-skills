#!/usr/bin/env python3
"""Validate tracked public evidence, tool inventory, and status controls."""
from __future__ import annotations

import argparse
import fnmatch
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys


PROOF_DOC = "EVIDENCE.md"
HARNESS_DOC = "evals/harness/README.md"
POINTER = "docs/wordpress/project-status-current.md"
HISTORICAL_STATUS = "docs/wordpress/project-status-2026-07-06.md"
CANONICAL_EXTRACTION = (
    "docs/wordpress/standalone-extraction-readiness-2026-06-21.md"
)
REDUNDANT_EXTRACTION = "docs/standalone-extraction-readiness-2026-06-21.md"
STATUS_LINK_DOCS = (
    "README.md", "PUBLICATION-CHECKLIST.md", "CUTOVER.md",
    "PACKAGE-BUILD.md", "PROVENANCE.md",
)
VALIDATION_SECTIONS = (
    ("EVIDENCE.md", "Validation Bundle"),
    ("CONTRIBUTING.md", "Validation"),
    ("SECURITY.md", "Validation Expectations"),
)
ACTIVE_CONTROL_DOCS = (
    "EVIDENCE.md", "PUBLICATION-CHECKLIST.md", "CUTOVER.md",
    "PACKAGE-BUILD.md", "PROVENANCE.md", HARNESS_DOC,
)
STALE_PATTERNS = (
    r"wordpress-skills/docs/standalone", r"evals/results/wordpress-",
    r"repository is still private", r"future skills\.sh",
    r"run_design_smoke", r"run_math_science",
)
CODE_SPAN = re.compile(r"`([^`\n]+)`")
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
COMMAND_PATH = re.compile(
    r"(?<![\w/.-])((?:scripts|evals/harness)/[\w./-]+\.(?:py|js|sh))"
    r"(?![\w.])"
)
DATED_STATUS = re.compile(r"project-status-(\d{4}-\d{2}-\d{2})\.md\Z")


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments], check=False,
        capture_output=True, timeout=15,
    )


def _tracked_files(root: Path, errors: list[str]) -> set[str]:
    top = _git(root, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        errors.append(f"{root}: ROOT is not a Git worktree")
        return set()
    reported = Path(top.stdout.decode().strip()).resolve()
    if reported != root:
        errors.append(f"{root}: ROOT must be the Git worktree top level")
        return set()
    result = _git(root, "ls-files", "-z")
    if result.returncode != 0:
        errors.append("git ls-files failed")
        return set()
    return {
        item.decode("utf-8", "surrogateescape")
        for item in result.stdout.split(b"\0") if item
    }


def _read(root: Path, relative: str, errors: list[str]) -> str:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{relative}: cannot read control document: {exc}")
        return ""


def _section(text: str, name: str) -> str | None:
    heading = f"## {name}"
    lines = text.splitlines()
    try:
        start = lines.index(heading) + 1
    except ValueError:
        return None
    end = next(
        (index for index in range(start, len(lines))
         if lines[index].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _safe_reference(value: str) -> tuple[str | None, str | None]:
    if "\\" in value:
        return None, "backslashes are not allowed"
    stripped = value.rstrip("/")
    path = PurePosixPath(stripped)
    if not stripped or path.is_absolute():
        return None, "absolute or empty path is not allowed"
    if any(part in (".", "..") for part in path.parts):
        return None, "path traversal is not allowed"
    return stripped, None


def _regular_non_symlink(root: Path, relative: str) -> tuple[bool, str]:
    current = root
    for part in PurePosixPath(relative).parts:
        current /= part
        try:
            details = current.lstat()
        except OSError as exc:
            return False, f"missing or unreadable: {exc}"
        if stat.S_ISLNK(details.st_mode):
            return False, "symlink paths are not accepted"
    if not stat.S_ISREG(details.st_mode):
        return False, "path is not a regular file"
    return True, ""


def _require_file(
    root: Path, tracked: set[str], value: str, context: str,
    errors: list[str],
) -> None:
    relative, problem = _safe_reference(value)
    if problem:
        errors.append(f"{context}: {value}: {problem}")
        return
    assert relative is not None
    if relative not in tracked:
        errors.append(f"{context}: {relative}: path is not tracked")
        return
    valid, detail = _regular_non_symlink(root, relative)
    if not valid:
        errors.append(f"{context}: {relative}: {detail}")


def _proof_references(text: str, errors: list[str]) -> list[str]:
    section = _section(text, "Current Proof Surfaces")
    if section is None:
        errors.append(f"{PROOF_DOC}: missing Current Proof Surfaces section")
        return []
    references = []
    for line in section.splitlines():
        if not line.startswith("|") or re.match(r"^\|[-:| ]+\|$", line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0] == "Claim area":
            continue
        references.extend(CODE_SPAN.findall(cells[1]))
    if not references:
        errors.append(f"{PROOF_DOC}: Current Proof Surfaces has no local paths")
    return references


def _validate_proofs(
    root: Path, tracked: set[str], text: str, errors: list[str],
) -> None:
    for reference in _proof_references(text, errors):
        context = f"{PROOF_DOC}: Current Proof Surfaces"
        if reference.startswith("evals/results/"):
            errors.append(f"{context}: ignored result path is forbidden: {reference}")
            continue
        _require_file(root, tracked, reference, context, errors)


def _glob_matches(tracked: set[str], pattern: str) -> list[str]:
    if pattern.endswith("/"):
        return sorted(path for path in tracked if path.startswith(pattern))
    return sorted(path for path in tracked if fnmatch.fnmatchcase(path, pattern))


def _validate_bundled(
    root: Path, tracked: set[str], text: str, errors: list[str],
) -> None:
    section = _section(text, "Bundled Evidence Files")
    context = f"{PROOF_DOC}: Bundled Evidence Files"
    if section is None:
        errors.append(f"{context}: missing section")
        return
    patterns = CODE_SPAN.findall(section)
    if not patterns:
        errors.append(f"{context}: no path or glob entries")
    for pattern in patterns:
        normalized, problem = _safe_reference(pattern)
        if problem:
            errors.append(f"{context}: {pattern}: {problem}")
            continue
        matches = _glob_matches(tracked, pattern)
        if not matches:
            errors.append(f"{context}: {pattern}: matched no tracked files")
        for match in matches:
            _require_file(root, tracked, match, context, errors)


def _validate_inventory(
    root: Path, tracked: set[str], errors: list[str],
) -> None:
    text = _read(root, HARNESS_DOC, errors)
    section = _section(text, "Shipped WordPress Tool Inventory")
    context = f"{HARNESS_DOC}: Shipped WordPress Tool Inventory"
    if section is None:
        errors.append(f"{context}: missing section")
        return
    paths = [
        item for item in CODE_SPAN.findall(section)
        if item.startswith("evals/harness/") and item.endswith((".py", ".js"))
    ]
    if not paths:
        errors.append(f"{context}: no executable inventory entries")
    for path in paths:
        _require_file(root, tracked, path, context, errors)


def _validate_commands(
    root: Path, tracked: set[str], errors: list[str],
) -> None:
    for document, heading in VALIDATION_SECTIONS:
        text = _read(root, document, errors)
        section = _section(text, heading)
        context = f"{document}: {heading}"
        if section is None:
            errors.append(f"{context}: missing section")
            continue
        paths = sorted(set(COMMAND_PATH.findall(section)))
        if not paths:
            errors.append(f"{context}: no validation command paths")
        for path in paths:
            _require_file(root, tracked, path, context, errors)


def _relative_links(text: str) -> list[str]:
    return [
        target for target in MARKDOWN_LINK.findall(text)
        if not re.match(r"(?:https?://|mailto:|#)", target)
    ]


def _validate_pointer(
    root: Path, tracked: set[str], errors: list[str],
) -> None:
    _require_file(root, tracked, POINTER, "current status pointer", errors)
    text = _read(root, POINTER, errors)
    links = _relative_links(text)
    if len(links) != 1:
        errors.append(f"{POINTER}: expected exactly one relative link, found {len(links)}")
        return
    target_name = links[0]
    if "/" in target_name or target_name.startswith("."):
        errors.append(f"{POINTER}: target must be a sibling dated status file")
        return
    match = DATED_STATUS.fullmatch(target_name)
    if not match:
        errors.append(f"{POINTER}: target is not project-status-YYYY-MM-DD.md")
        return
    target = f"docs/wordpress/{target_name}"
    _require_file(root, tracked, target, "current status target", errors)
    declared = re.search(r"Status date:\s*`?(\d{4}-\d{2}-\d{2})`?", text)
    if not declared:
        errors.append(f"{POINTER}: missing declared Status date")
    elif declared.group(1) != match.group(1):
        errors.append(f"{POINTER}: declared date does not match target filename")


def _validate_status_links(root: Path, errors: list[str]) -> None:
    target = "docs/wordpress/project-status-current.md"
    for document in STATUS_LINK_DOCS:
        text = _read(root, document, errors)
        if target not in _relative_links(text):
            errors.append(f"{document}: must link to the stable status pointer {target}")
    old = _read(root, HISTORICAL_STATUS, errors)
    banner = "\n".join(old.splitlines()[:8])
    if "superseded" not in banner.lower() or "project-status-current.md" not in _relative_links(banner):
        errors.append(
            f"{HISTORICAL_STATUS}: supersession banner must link to "
            "project-status-current.md"
        )


def _validate_extraction(
    root: Path, tracked: set[str], errors: list[str],
) -> None:
    _require_file(root, tracked, CANONICAL_EXTRACTION, "canonical extraction document", errors)
    if REDUNDANT_EXTRACTION in tracked or (root / REDUNDANT_EXTRACTION).exists():
        errors.append(f"{REDUNDANT_EXTRACTION}: redundant extraction document must be absent")


def _validate_stale_phrases(root: Path, errors: list[str]) -> None:
    combined = re.compile("|".join(f"(?:{item})" for item in STALE_PATTERNS), re.I)
    for document in ACTIVE_CONTROL_DOCS:
        text = _read(root, document, errors)
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = combined.search(line)
            if match:
                errors.append(
                    f"{document}:{line_number}: stale active-control phrase: "
                    f"{match.group(0)}"
                )


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    root = root.resolve()
    tracked = _tracked_files(root, errors)
    if not tracked:
        return errors
    evidence = _read(root, PROOF_DOC, errors)
    _validate_proofs(root, tracked, evidence, errors)
    _validate_bundled(root, tracked, evidence, errors)
    _validate_inventory(root, tracked, errors)
    _validate_commands(root, tracked, errors)
    _validate_pointer(root, tracked, errors)
    _validate_status_links(root, errors)
    _validate_extraction(root, tracked, errors)
    _validate_stale_phrases(root, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    errors = validate(arguments.root)
    if errors:
        print("Public documentation validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Public documentation validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
