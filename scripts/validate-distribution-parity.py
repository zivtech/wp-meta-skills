#!/usr/bin/env python3
"""Validate every published wp-meta-skills host representation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

try:
    import yaml
    from yaml.constructor import ConstructorError
except ImportError:  # Manifest modes intentionally need only the stdlib.
    yaml = None
    ConstructorError = ValueError


SKILL_TO_AGENT = {
    "wordpress-planner": "wordpress-planner",
    "wordpress-planner.content-model": "wordpress-content-model-planner",
    "wordpress-planner.plugin": "wordpress-plugin-planner",
    "wordpress-planner.block": "wordpress-block-planner",
    "wordpress-planner.theme": "wordpress-theme-planner",
    "wordpress-planner.migration": "wordpress-migration-planner",
    "wordpress-blueprint-executor": "wordpress-blueprint-executor",
    "wordpress-plugin-executor": "wordpress-plugin-executor",
    "wordpress-block-executor": "wordpress-block-executor",
    "wordpress-theme-executor": "wordpress-theme-executor",
    "wordpress-critic": "wordpress-critic",
    "wordpress-security-critic": "wordpress-security-critic",
    "wordpress-performance-critic": "wordpress-performance-critic",
    "wordpress-theme-critic": "wordpress-theme-critic",
}
EXECUTOR_SKILLS = frozenset(
    {
        "wordpress-blueprint-executor",
        "wordpress-plugin-executor",
        "wordpress-block-executor",
        "wordpress-theme-executor",
    }
)
EXECUTOR_AGENTS = frozenset(SKILL_TO_AGENT[name] for name in EXECUTOR_SKILLS)
SKILL_FIELDS = frozenset({"name", "type", "model", "description"})
CODEX_AGENT_FIELDS = frozenset({"name", "description", "developer_instructions"})
SKILL_SECTIONS = (
    "When to Use",
    "Protocol",
    "Hard Gates",
    "Exact API And Verification Contract",
    "Calibration",
    "Failure Modes",
    "Output Contract",
    "Provenance",
)
SHARED_SECTIONS = {
    "Protocol": "Protocol",
    "Hard Gates": "Hard_Gates",
    "Exact API And Verification Contract": "Exact_API_Contract",
    "Output Contract": "Output_Format",
}
BASE_AGENT_TAGS = frozenset(
    {
        "Role",
        "Protocol",
        "Hard_Gates",
        "Exact_API_Contract",
        "Calibration",
        "Failure_Modes",
        "Output_Format",
    }
)
GROUP_FOR_TYPE = {"planner": "Planning", "executor": "Execution", "critic": "Review"}
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
MANIFEST_RECORD_RE = re.compile(r"^([0-9a-f]{64})  ([^/\r\n][^\r\n]*)$")
MAX_MANIFEST_BYTES = 1024 * 1024


if yaml is not None:

    class UniqueKeyLoader(yaml.SafeLoader):
        """Safe YAML loader that rejects repeated mapping keys."""

else:

    class UniqueKeyLoader:  # type: ignore[no-redef]
        """Placeholder used only when parity mode lacks PyYAML."""


def _unique_mapping(
    loader: yaml.Loader,
    node: yaml.Node,
    deep: bool = False,
) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


if yaml is not None:
    UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        _unique_mapping,
    )


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n")


def _read_text(path: Path) -> str:
    try:
        return _normalize_newlines(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"read failed: {exc.__class__.__name__}") from exc


def _parse_markdown(path: Path) -> tuple[dict[str, Any], str]:
    if yaml is None:
        raise ValueError("PyYAML is required for parity validation")
    text = _read_text(path)
    if not text.startswith("---\n"):
        raise ValueError("frontmatter parse failed: missing opening fence")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("frontmatter parse failed: missing closing fence")
    try:
        fields = yaml.load(text[4:end], Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise ValueError("frontmatter parse failed: invalid YAML") from exc
    if not isinstance(fields, dict):
        raise ValueError("frontmatter parse failed: expected mapping")
    return fields, text[end + 5 :]


def _check_string_fields(
    path: Path,
    fields: dict[str, Any],
    expected: frozenset[str],
) -> list[str]:
    issues: list[str] = []
    if set(fields) != expected:
        issues.append(f"{path}: field allowlist mismatch")
    for key in expected & set(fields):
        if not isinstance(fields[key], str) or not fields[key].strip():
            issues.append(f"{path}: field {key} must be a nonblank string")
    return issues


def _skill_inventory(root: Path, surface: str) -> dict[str, Path]:
    base = root / surface / "skills"
    return {path.parent.name: path for path in sorted(base.glob("*/SKILL.md"))}


def _agent_inventory(root: Path, surface: str, suffix: str) -> dict[str, Path]:
    base = root / surface / "agents"
    return {path.stem: path for path in sorted(base.glob(f"*{suffix}"))}


def _inventory_issue(label: str, actual: set[str], expected: set[str]) -> list[str]:
    issues: list[str] = []
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        issues.append(f"{label}: inventory missing {', '.join(missing)}")
    if extra:
        issues.append(f"{label}: inventory extra {', '.join(extra)}")
    return issues


def _normalized_model(value: str, expected_prefix: str) -> str | None:
    if not isinstance(value, str) or not value.startswith(expected_prefix):
        return None
    family = value.removeprefix(expected_prefix)
    return family if family and family.isascii() else None


def _parse_json_strict(path: Path) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key {key}")
            result[key] = value
        return result

    try:
        value = json.loads(_read_text(path), object_pairs_hook=pairs)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("JSON parse failed") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON parse failed: expected object")
    return value


def _validate_skills_sh(
    root: Path,
    skill_fields: dict[str, dict[str, Any]],
) -> list[str]:
    path = root / "skills.sh.json"
    try:
        data = _parse_json_strict(path)
    except ValueError as exc:
        return [f"skills.sh.json: {exc}"]
    if set(data) != {"$schema", "notGrouped", "groupings"}:
        return ["skills.sh.json: field allowlist mismatch"]
    groups = data.get("groupings")
    if not isinstance(groups, list) or len(groups) != 3:
        return ["skills.sh.json: group inventory mismatch"]
    seen: list[str] = []
    issues: list[str] = []
    for group in groups:
        if not isinstance(group, dict) or set(group) != {"title", "description", "skills"}:
            issues.append("skills.sh.json: group field allowlist mismatch")
            continue
        title, skills = group.get("title"), group.get("skills")
        if not isinstance(title, str) or not isinstance(skills, list):
            issues.append("skills.sh.json: group shape mismatch")
            continue
        for name in skills:
            if not isinstance(name, str):
                issues.append("skills.sh.json: group contains non-string skill")
                continue
            seen.append(name)
            skill_type = skill_fields.get(name, {}).get("type")
            if GROUP_FOR_TYPE.get(skill_type) != title:
                issues.append(f"skills.sh.json: group mismatch for {name}")
    if len(seen) != len(set(seen)):
        issues.append("skills.sh.json: group duplicate skill")
    issues.extend(_inventory_issue("skills.sh.json group", set(seen), set(SKILL_TO_AGENT)))
    return issues


def _skill_sections(body: str, path: Path) -> tuple[dict[str, str], list[str]]:
    headings = re.findall(r"(?m)^## (.+)$", body)
    issues: list[str] = []
    if tuple(headings) != SKILL_SECTIONS:
        issues.append(f"{path}: unclassified skill section or section order mismatch")
    sections: dict[str, str] = {}
    for heading in SKILL_SECTIONS:
        match = re.search(
            rf"(?ms)^## {re.escape(heading)}\n(.*?)(?=^## |\Z)",
            body,
        )
        if match:
            raw = match.group(1)
            suffix = "\n" if heading == "Provenance" else "\n\n"
            if not raw.startswith("\n") or not raw.endswith(suffix):
                issues.append(f"{path}: {heading} section wrapper mismatch")
                continue
            sections[heading] = raw[1 : -len(suffix)]
    return sections, issues


def _agent_sections(
    body: str,
    path: Path,
    agent: str,
) -> tuple[dict[str, str], list[str]]:
    issues: list[str] = []
    if not body.startswith("<Agent_Prompt>\n") or not body.endswith("\n</Agent_Prompt>"):
        return {}, [f"{path}: agent prompt wrapper mismatch"]
    opens = re.findall(r"(?m)^  <([A-Za-z_]+)>$", body)
    closes = re.findall(r"(?m)^  </([A-Za-z_]+)>$", body)
    allowed = set(BASE_AGENT_TAGS)
    if agent == "wordpress-planner":
        allowed.add("Coverage")
    if agent in EXECUTOR_AGENTS:
        allowed.add("Domain_Generation")
    if len(opens) != len(set(opens)) or opens != closes or set(opens) != allowed:
        issues.append(f"{path}: unclassified agent section or wrapper mismatch")
    sections: dict[str, str] = {}
    for tag in opens:
        match = re.search(
            rf"(?ms)^  <{re.escape(tag)}>\n(.*?)^  </{re.escape(tag)}>$",
            body,
        )
        if match:
            sections[tag] = match.group(1)
    return sections, issues


def _strip_inline_code(value: str) -> str:
    normalized = INLINE_CODE_RE.sub(lambda match: match.group(1), value)
    if "`" in normalized:
        raise ValueError("unbalanced or multi-backtick inline code")
    return normalized


def _unwrap_record(line: str, prefix: str, label: str) -> str:
    if not line.startswith(prefix):
        raise ValueError(f"{label} wrapper mismatch")
    record = line[len(prefix) :]
    if not record or record[:1].isspace() or record != record.rstrip():
        raise ValueError(f"{label} whitespace mismatch")
    return _strip_inline_code(record)


def _protocol_records(value: str, skill_side: bool) -> tuple[str, ...]:
    lines = tuple(value.split("\n"))
    if any(not line for line in lines):
        raise ValueError("Protocol contains an empty record")
    records = tuple(
        _unwrap_record(
            line,
            ("" if index == 0 else "    ") if skill_side else "    ",
            "Protocol",
        )
        for index, line in enumerate(lines)
    )
    if len(records) != 10:
        raise ValueError("Protocol must contain ten records")
    for index, record in enumerate(records):
        if not record.startswith(f"Phase {index} - "):
            raise ValueError("Protocol phase order mismatch")
    return records


def _gate_records(value: str, skill_side: bool) -> tuple[str, ...]:
    records: list[str] = []
    lines = value.split("\n")
    if any(not line for line in lines):
        raise ValueError("Hard Gates contains an empty record")
    for index, line in enumerate(lines):
        prefix = ("" if index == 0 else "    ") if skill_side else "    "
        records.append(_unwrap_record(line, f"{prefix}- ", "Hard Gates"))
    if not records:
        raise ValueError("Hard Gates is empty")
    return tuple(records)


def _api_records(value: str, skill_side: bool) -> tuple[str, ...]:
    lines = tuple(value.split("\n"))
    if any(not line for line in lines):
        raise ValueError("Exact API contract contains an empty record")
    prefix = "" if skill_side else "    "
    records = tuple(_unwrap_record(line, prefix, "Exact API contract") for line in lines)
    if len(records) != 1:
        raise ValueError("Exact API contract must contain one paragraph")
    return records


def _output_records(value: str, skill_side: bool) -> tuple[str, ...]:
    records: list[str] = []
    lines = value.split("\n")
    heading_indexes: list[int] = []
    for index, line in enumerate(lines):
        if skill_side and line.startswith("- "):
            candidate = _unwrap_record(line, "- ", "Output contract")
        elif not skill_side and line.startswith("    "):
            candidate = _unwrap_record(line, "    ", "Output contract")
        else:
            continue
        if candidate.startswith("## ") or (
            candidate.startswith("**") and candidate.endswith("**")
        ):
            records.append(candidate)
            heading_indexes.append(index)
    if not records:
        raise ValueError("Output contract contains no headings")
    if any(not lines[index] for index in range(heading_indexes[0], heading_indexes[-1] + 1)):
        raise ValueError("Output contract contains inner blank whitespace")
    return tuple(records)


def _project(value: str, section: str, skill_side: bool) -> tuple[str, ...]:
    if value.endswith("\n"):
        value = value[:-1]
    if section == "Protocol":
        return _protocol_records(value, skill_side)
    if section == "Hard Gates":
        return _gate_records(value, skill_side)
    if section == "Exact API And Verification Contract":
        return _api_records(value, skill_side)
    return _output_records(value, skill_side)


def _compare_shared(
    skill: str,
    skill_path: Path,
    agent_path: Path,
    skill_sections: dict[str, str],
    agent_sections: dict[str, str],
) -> list[str]:
    issues: list[str] = []
    for skill_section, agent_tag in SHARED_SECTIONS.items():
        try:
            left = _project(skill_sections[skill_section], skill_section, True)
            right = _project(agent_sections[agent_tag], skill_section, False)
        except (KeyError, ValueError) as exc:
            issues.append(f"{skill_path}: {skill_section} projection failed: {exc}")
            continue
        if left != right:
            issues.append(
                f"{skill_path}: {skill_section} differs from {agent_path} for {skill}"
            )
    return issues


def _claude_agent_body(body: str, path: Path) -> tuple[str | None, list[str]]:
    if not body.startswith("\n<Agent_Prompt>") or body.startswith("\n\n"):
        return None, [f"{path}: separator must be exactly one newline"]
    value = body[1:]
    if value.endswith("\n"):
        value = value[:-1]
    return value, []


def _validate_skill_pair(
    name: str,
    claude_path: Path,
    agents_path: Path,
) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    issues: list[str] = []
    try:
        claude_fields, claude_body = _parse_markdown(claude_path)
    except ValueError as exc:
        return None, None, [f"{claude_path}: parse failed: {exc}"]
    try:
        agents_fields, agents_body = _parse_markdown(agents_path)
    except ValueError as exc:
        return None, None, [f"{agents_path}: parse failed: {exc}"]
    issues.extend(_check_string_fields(claude_path, claude_fields, SKILL_FIELDS))
    issues.extend(_check_string_fields(agents_path, agents_fields, SKILL_FIELDS))
    for field in ("name", "type", "description"):
        if claude_fields.get(field) != agents_fields.get(field):
            issues.append(f"{agents_path}: field {field} differs from {claude_path}")
    left_model = _normalized_model(claude_fields.get("model"), "claude-")
    right_model = _normalized_model(agents_fields.get("model"), "Codex-")
    if left_model is None or left_model != right_model:
        issues.append(f"{agents_path}: field model differs from {claude_path}")
    if claude_fields.get("name") != name:
        issues.append(f"{claude_path}: field name does not match inventory")
    if claude_body != agents_body:
        issues.append(f"{agents_path}: body differs from {claude_path}")
    return claude_fields, claude_body, issues


def _validate_agent_pair(
    name: str,
    claude_path: Path,
    codex_path: Path,
) -> tuple[str | None, list[str]]:
    issues: list[str] = []
    try:
        claude_fields, raw_body = _parse_markdown(claude_path)
    except ValueError as exc:
        return None, [f"{claude_path}: parse failed: {exc}"]
    try:
        codex_fields = tomllib.loads(_read_text(codex_path))
    except (ValueError, tomllib.TOMLDecodeError) as exc:
        return None, [f"{codex_path}: parse failed: {exc}"]
    expected = frozenset({"name", "description", "model"})
    if name not in EXECUTOR_AGENTS:
        expected = expected | {"disallowedTools"}
    issues.extend(_check_string_fields(claude_path, claude_fields, expected))
    issues.extend(_check_string_fields(codex_path, codex_fields, CODEX_AGENT_FIELDS))
    for field in ("name", "description"):
        if claude_fields.get(field) != codex_fields.get(field):
            issues.append(f"{codex_path}: field {field} differs from {claude_path}")
    if claude_fields.get("name") != name:
        issues.append(f"{claude_path}: field name does not match inventory")
    body, body_issues = _claude_agent_body(raw_body, claude_path)
    issues.extend(body_issues)
    codex_body = codex_fields.get("developer_instructions")
    if isinstance(codex_body, str) and codex_body.endswith("\n"):
        codex_body = codex_body[:-1]
    if body is not None and body != codex_body:
        issues.append(f"{codex_path}: developer_instructions body differs from {claude_path}")
    return body, issues


def expected_manifest_paths() -> tuple[str, ...]:
    paths = ["skills.sh.json"]
    for skill in SKILL_TO_AGENT:
        paths.extend(
            (
                f".agents/skills/{skill}/SKILL.md",
                f".claude/skills/{skill}/SKILL.md",
            )
        )
    for agent in SKILL_TO_AGENT.values():
        paths.extend(
            (
                f".claude/agents/{agent}.md",
                f".codex/agents/{agent}.toml",
            )
        )
    result = tuple(sorted(paths))
    if len(result) != 57 or len(set(result)) != 57:
        raise RuntimeError("manifest policy must contain exactly 57 unique paths")
    return result


def _filesystem_manifest_paths(root: Path) -> set[str]:
    paths = {"skills.sh.json"} if (root / "skills.sh.json").exists() else set()
    patterns = (
        ".agents/skills/*/SKILL.md",
        ".claude/skills/*/SKILL.md",
        ".claude/agents/*.md",
        ".codex/agents/*.toml",
    )
    for pattern in patterns:
        paths.update(path.relative_to(root).as_posix() for path in root.glob(pattern))
    return paths


def _distribution_parent_issues(root: Path) -> list[str]:
    issues: list[str] = []
    for relative in (
        ".agents",
        ".agents/skills",
        ".claude",
        ".claude/agents",
        ".claude/skills",
        ".codex",
        ".codex/agents",
    ):
        path = root / relative
        try:
            metadata = path.lstat()
        except OSError as exc:
            issues.append(f"{relative}: distribution parent unavailable: {exc}")
            continue
        if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            issues.append(f"{relative}: distribution parent is not a real directory")
    return issues


def _filesystem_manifest_issues(root: Path) -> list[str]:
    expected = set(expected_manifest_paths())
    actual = _filesystem_manifest_paths(root)
    issues = _distribution_parent_issues(root)
    if expected - actual:
        issues.append(f"distribution inventory missing {', '.join(sorted(expected - actual))}")
    if actual - expected:
        issues.append(f"distribution inventory extra {', '.join(sorted(actual - expected))}")
    return issues


def _distribution_file_issues(root: Path) -> list[str]:
    issues: list[str] = []
    for relative in expected_manifest_paths():
        try:
            _read_regular(root, relative)
        except (OSError, ValueError) as exc:
            issues.append(f"{relative}: distributed file is unavailable or unsafe: {exc}")
    return issues


def _read_regular(root: Path, path: Path | str, limit: int | None = None) -> bytes:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ValueError("secure no-follow file traversal is unavailable")
    candidate = Path(path)
    try:
        relative = candidate.relative_to(root) if candidate.is_absolute() else candidate
    except ValueError as exc:
        raise ValueError("path is outside the distribution root") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("path is not a safe relative distribution path")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    descriptors = [os.open(root, directory_flags)]
    try:
        for component in relative.parts[:-1]:
            descriptors.append(os.open(component, directory_flags, dir_fd=descriptors[-1]))
        descriptor = os.open(relative.parts[-1], file_flags, dir_fd=descriptors[-1])
        descriptors.append(descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("not a regular file")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            size += len(chunk)
            if limit is not None and size > limit:
                raise ValueError("file exceeds size limit")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _hash_regular(root: Path, path: Path | str) -> str:
    return hashlib.sha256(_read_regular(root, path)).hexdigest()


def _manifest_records(encoded: bytes) -> tuple[dict[str, str], list[str]]:
    try:
        text = encoded.decode("utf-8")
    except UnicodeDecodeError:
        return {}, ["MANIFEST.sha256: invalid UTF-8"]
    if not text.endswith("\n"):
        return {}, ["MANIFEST.sha256: missing terminal newline"]
    records: dict[str, str] = {}
    issues: list[str] = []
    for number, line in enumerate(text[:-1].split("\n"), 1):
        match = MANIFEST_RECORD_RE.fullmatch(line)
        if not match:
            issues.append(f"MANIFEST.sha256:{number}: malformed checksum record")
            continue
        digest, relative = match.groups()
        if relative in records:
            issues.append(f"MANIFEST.sha256:{number}: duplicate path {relative}")
            continue
        records[relative] = digest
    return records, issues


def verify_manifest(root: Path, manifest: Path | None = None) -> list[str]:
    root = root.resolve()
    path = manifest or root / "MANIFEST.sha256"
    try:
        encoded = _read_regular(root, path, MAX_MANIFEST_BYTES)
    except (OSError, ValueError) as exc:
        return [f"MANIFEST.sha256: control file is unavailable or unsafe: {exc}"]
    records, issues = _manifest_records(encoded)
    issues.extend(_filesystem_manifest_issues(root))
    expected = set(expected_manifest_paths())
    actual = set(records)
    if expected - actual:
        issues.append(f"MANIFEST.sha256: missing {', '.join(sorted(expected - actual))}")
    if actual - expected:
        issues.append(f"MANIFEST.sha256: extra {', '.join(sorted(actual - expected))}")
    for relative in sorted(expected & actual):
        try:
            digest = _hash_regular(root, relative)
        except (OSError, ValueError) as exc:
            issues.append(f"{relative}: distributed file is unavailable or unsafe: {exc}")
            continue
        if digest != records[relative]:
            issues.append(f"{relative}: checksum mismatch")
    return issues


def _manifest_bytes(root: Path) -> bytes:
    inventory_issues = _filesystem_manifest_issues(root)
    if inventory_issues:
        raise ValueError("; ".join(inventory_issues))
    lines: list[str] = []
    for relative in expected_manifest_paths():
        try:
            digest = _hash_regular(root, relative)
        except (OSError, ValueError) as exc:
            raise ValueError(f"{relative}: distributed file is unavailable or unsafe: {exc}") from exc
        lines.append(f"{digest}  {relative}\n")
    return "".join(lines).encode("utf-8")


def generate_manifest(root: Path, manifest: Path | None = None) -> None:
    root = root.resolve()
    path = manifest or root / "MANIFEST.sha256"
    if path.exists() or path.is_symlink():
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise ValueError(f"MANIFEST.sha256: cannot inspect existing control file: {exc}") from exc
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("MANIFEST.sha256: existing control file is not a regular file")
    encoded = _manifest_bytes(root)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".MANIFEST.sha256.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        candidate_issues = verify_manifest(root, temporary)
        if candidate_issues:
            raise ValueError("; ".join(candidate_issues))
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def validate(root: Path) -> list[str]:
    root = root.resolve()
    expected_skills, expected_agents = set(SKILL_TO_AGENT), set(SKILL_TO_AGENT.values())
    claude_skills = _skill_inventory(root, ".claude")
    agents_skills = _skill_inventory(root, ".agents")
    claude_agents = _agent_inventory(root, ".claude", ".md")
    codex_agents = _agent_inventory(root, ".codex", ".toml")
    issues = _distribution_parent_issues(root)
    issues.extend(_distribution_file_issues(root))
    for label, actual, expected in (
        (".claude/skills", set(claude_skills), expected_skills),
        (".agents/skills", set(agents_skills), expected_skills),
        (".claude/agents", set(claude_agents), expected_agents),
        (".codex/agents", set(codex_agents), expected_agents),
    ):
        issues.extend(_inventory_issue(label, actual, expected))
    skill_fields: dict[str, dict[str, Any]] = {}
    skill_bodies: dict[str, str] = {}
    agent_bodies: dict[str, str] = {}
    for name in sorted(expected_skills & set(claude_skills) & set(agents_skills)):
        fields, body, pair_issues = _validate_skill_pair(
            name, claude_skills[name], agents_skills[name]
        )
        issues.extend(pair_issues)
        if fields is not None and body is not None:
            skill_fields[name] = fields
            skill_bodies[name] = body
    for name in sorted(expected_agents & set(claude_agents) & set(codex_agents)):
        body, pair_issues = _validate_agent_pair(name, claude_agents[name], codex_agents[name])
        issues.extend(pair_issues)
        if body is not None:
            agent_bodies[name] = body
    issues.extend(_validate_skills_sh(root, skill_fields))
    for skill, agent in SKILL_TO_AGENT.items():
        if skill not in skill_bodies or agent not in agent_bodies:
            continue
        skill_sections, skill_issues = _skill_sections(skill_bodies[skill], claude_skills[skill])
        agent_sections, agent_issues = _agent_sections(agent_bodies[agent], claude_agents[agent], agent)
        issues.extend((*skill_issues, *agent_issues))
        if not skill_issues and not agent_issues:
            issues.extend(
                _compare_shared(
                    skill,
                    claude_skills[skill],
                    claude_agents[agent],
                    skill_sections,
                    agent_sections,
                )
            )
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--verify-manifest", action="store_true")
    modes.add_argument("--generate-manifest", action="store_true")
    args = parser.parse_args(argv)
    if args.verify_manifest:
        issues = verify_manifest(args.root)
        if issues:
            print("Manifest verification failed:")
            for issue in issues:
                print(f"  - {issue}")
            return 1
        print("Manifest verification passed (57 distributed files).")
        return 0
    if args.generate_manifest:
        try:
            generate_manifest(args.root)
        except (OSError, ValueError) as exc:
            print(f"Manifest generation failed: {exc}")
            return 1
        print("Generated deterministic manifest (57 distributed files).")
        return 0
    issues = validate(args.root)
    if issues:
        print("Distribution parity validation failed:")
        for issue in issues:
            print(f"  - {issue}")
        return 1
    print("Distribution parity passed: 14 skill pairs, 14 agent pairs, 14 skills.sh entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
