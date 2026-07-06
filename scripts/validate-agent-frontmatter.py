#!/usr/bin/env python3
"""Validate source agent and skill YAML frontmatter contracts."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
    from yaml.constructor import ConstructorError
except ImportError:
    print("PyYAML is required: python -m pip install pyyaml", file=sys.stderr)
    raise SystemExit(2)


ROOT = Path(__file__).resolve().parent.parent
REQUIRED_AGENT_FIELDS = ("name", "description", "model")
REQUIRED_SKILL_FIELDS = ("name", "description", "model", "type")
EXCLUDED_PARTS = (
    (".git",),
    (".claude", "worktrees"),
)


class UniqueKeyLoader(yaml.SafeLoader):
    """YAML loader that rejects duplicate frontmatter keys."""


def construct_mapping_with_unique_keys(
    loader: yaml.Loader,
    node: yaml.Node,
    deep: bool = False,
):
    seen: set[object] = set()
    for key_node, _ in node.value:
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


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_mapping_with_unique_keys,
)


def is_excluded(path: Path) -> bool:
    parts = path.parts
    for excluded in EXCLUDED_PARTS:
        if len(excluded) == 1 and excluded[0] in parts:
            return True
        for index in range(0, len(parts) - len(excluded) + 1):
            if tuple(parts[index : index + len(excluded)]) == excluded:
                return True
    return False


def parse_frontmatter(path: Path) -> tuple[dict[str, str], list[str]]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, ["missing opening YAML frontmatter fence"]

    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, ["missing closing YAML frontmatter fence"]

    raw = text[4:end]
    try:
        parsed = yaml.load(raw, Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        return {}, [f"invalid YAML frontmatter: {exc}"]

    if not isinstance(parsed, dict):
        return {}, ["frontmatter must be a YAML mapping"]

    fields: dict[str, str] = {}
    errors: list[str] = []
    for key, value in parsed.items():
        if not isinstance(key, str) or not key:
            errors.append("frontmatter contains a non-string or empty key")
            continue
        if value is None:
            fields[key] = ""
        elif isinstance(value, str):
            fields[key] = value
        else:
            errors.append(f"frontmatter field '{key}' must be a string")
    return fields, errors


def agent_paths() -> list[Path]:
    return [
        path
        for path in sorted(ROOT.glob("**/.claude/agents/*.md"))
        if not is_excluded(path.relative_to(ROOT))
    ]


def skill_paths() -> list[Path]:
    return [
        path
        for root in (ROOT / ".agents" / "skills", ROOT / ".claude" / "skills")
        for path in sorted(root.glob("*/SKILL.md"))
        if not is_excluded(path.relative_to(ROOT))
    ]


def validate_file(
    path: Path,
    expected_name: str,
    required_fields: tuple[str, ...],
    label: str,
) -> list[str]:
    rel = path.relative_to(ROOT)
    fields, file_errors = parse_frontmatter(path)
    errors = [f"{rel}: {error}" for error in file_errors]

    for field in required_fields:
        if not fields.get(field):
            errors.append(f"{rel}: missing required frontmatter field '{field}'")

    name = fields.get("name")
    if name and name != expected_name:
        errors.append(f"{rel}: {label} name '{name}' does not match expected '{expected_name}'")
    return errors


def main() -> int:
    errors: list[str] = []
    seen_agent_names: dict[str, Path] = {}
    seen_skill_names: dict[tuple[str, str], Path] = {}

    for path in agent_paths():
        errors.extend(validate_file(path, path.stem, REQUIRED_AGENT_FIELDS, "agent"))
        fields, _ = parse_frontmatter(path)
        name = fields.get("name", "")
        if name:
            if name in seen_agent_names:
                rel = path.relative_to(ROOT)
                first = seen_agent_names[name].relative_to(ROOT)
                errors.append(f"{rel}: duplicate agent name '{name}' also used by {first}")
            seen_agent_names[name] = path

    for path in skill_paths():
        errors.extend(validate_file(path, path.parent.name, REQUIRED_SKILL_FIELDS, "skill"))
        fields, _ = parse_frontmatter(path)
        name = fields.get("name", "")
        if name:
            surface = "/".join(path.relative_to(ROOT).parts[:2])
            key = (surface, name)
            if key in seen_skill_names:
                rel = path.relative_to(ROOT)
                first = seen_skill_names[key].relative_to(ROOT)
                errors.append(f"{rel}: duplicate {surface} skill name '{name}' also used by {first}")
            seen_skill_names[key] = path

    if errors:
        print("Frontmatter validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(
        "Frontmatter validation passed "
        f"({len(seen_agent_names)} agents, {len(seen_skill_names)} skill entries)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
