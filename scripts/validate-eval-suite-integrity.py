#!/usr/bin/env python3
"""Validate eval-suite fixture, metadata, rubric, and placeholder integrity."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent.parent
SUITES_ROOT = ROOT / "evals" / "suites"
QUALITY_GAPS = SUITES_ROOT / "QUALITY_GAPS.md"
PLACEHOLDER_MARKERS = (
    "TBD",
    "Placeholder",
    "[Finding",
    "[False positive test]",
    "Full metadata needs to be written",
)


@dataclass(frozen=True)
class Issue:
    suite: str
    kind: str
    path: Path | None
    message: str


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def section_body(text: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\n((?:[ \t]+.*\n)+)", text, re.MULTILINE)
    return match.group(1) if match else ""


def scalar_from_section(text: str, section: str, key: str) -> str | None:
    body = section_body(text, section)
    match = re.search(rf"^[ \t]+{re.escape(key)}:\s*(.+?)\s*$", body, re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip().strip('"').strip("'")


def fallback_eval_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    count_raw = scalar_from_section(text, "fixtures", "count")
    try:
        count: int | None = int(count_raw) if count_raw is not None else None
    except ValueError:
        count = None

    return {
        "fixtures": {
            "directory": scalar_from_section(text, "fixtures", "directory") or "./fixtures",
            "count": count,
            "pattern": scalar_from_section(text, "fixtures", "pattern") or "*.md",
            "metadata_suffix": scalar_from_section(text, "fixtures", "metadata_suffix") or ".metadata.yaml",
        },
        "rubrics": {
            "directory": scalar_from_section(text, "rubrics", "directory") or "./rubrics",
        },
    }


def load_eval_config(path: Path, suite: str) -> tuple[dict[str, Any], list[Issue]]:
    try:
        return load_yaml(path), []
    except Exception as exc:
        issue = Issue(
            suite=suite,
            kind="invalid_eval_yaml",
            path=path,
            message=f"{type(exc).__name__}: {exc}",
        )
        return fallback_eval_config(path), [issue]


def parse_quality_gaps() -> set[tuple[str, str]]:
    if not QUALITY_GAPS.exists():
        return set()

    known: set[tuple[str, str]] = set()
    pattern = re.compile(r"^\s*-\s+suite=(\S+)\s+scope=(\S+)\s+status=quarantined\b")
    for line in QUALITY_GAPS.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            known.add((match.group(1), match.group(2)))
    return known


def rel(path: Path | None) -> str:
    if path is None:
        return "-"
    return str(path.relative_to(ROOT))


def configured_dir(suite_dir: Path, raw: str | None, fallback: str) -> Path:
    value = raw or fallback
    if value.startswith("./"):
        value = value[2:]
    return suite_dir / value


def metadata_stem(path: Path, suffix: str) -> str:
    if path.name.endswith(suffix):
        return path.name[: -len(suffix)]
    return path.stem


def check_placeholders(suite: str, path: Path, kind: str) -> list[Issue]:
    text = path.read_text(encoding="utf-8", errors="replace")
    hits = [marker for marker in PLACEHOLDER_MARKERS if marker in text]
    if not hits:
        return []
    return [
        Issue(
            suite=suite,
            kind=f"placeholder_{kind}",
            path=path,
            message=f"placeholder marker(s): {', '.join(hits)}",
        )
    ]


def check_suite(suite_dir: Path) -> list[Issue]:
    suite = suite_dir.name
    config_path = suite_dir / "eval.yaml"
    config, issues = load_eval_config(config_path, suite)
    fixtures_cfg = config.get("fixtures") or {}
    rubrics_cfg = config.get("rubrics") or {}

    fixture_dir = configured_dir(suite_dir, fixtures_cfg.get("directory"), "fixtures")
    rubric_dir = configured_dir(suite_dir, rubrics_cfg.get("directory"), "rubrics")
    pattern = fixtures_cfg.get("pattern") or "*.md"
    metadata_suffix = fixtures_cfg.get("metadata_suffix") or ".metadata.yaml"
    declared_count = fixtures_cfg.get("count")

    if not fixture_dir.exists():
        issues.append(Issue(suite, "missing_fixture_dir", fixture_dir, "configured fixtures directory does not exist"))
        return issues

    fixture_stems = {path.stem for path in fixture_dir.glob(pattern) if path.is_file()}
    if isinstance(declared_count, int) and declared_count != len(fixture_stems):
        issues.append(
            Issue(
                suite,
                "fixture_count_mismatch",
                config_path,
                f"declares {declared_count} fixture(s), found {len(fixture_stems)}",
            )
        )

    metadata_paths = {
        metadata_stem(path, metadata_suffix): path
        for path in fixture_dir.glob(f"*{metadata_suffix}")
        if path.is_file()
    }
    missing_metadata = sorted(fixture_stems - set(metadata_paths))
    extra_metadata = sorted(set(metadata_paths) - fixture_stems)
    for stem in missing_metadata:
        issues.append(Issue(suite, "missing_metadata", fixture_dir / f"{stem}{metadata_suffix}", "missing metadata for fixture"))
    for stem in extra_metadata:
        issues.append(Issue(suite, "extra_metadata", metadata_paths[stem], "metadata has no matching fixture"))

    if not rubric_dir.exists():
        issues.append(Issue(suite, "missing_rubric_dir", rubric_dir, "configured rubrics directory does not exist"))
        rubric_paths: dict[str, Path] = {}
    else:
        rubric_paths = {
            path.name[: -len(".rubric.yaml")]: path
            for path in rubric_dir.glob("*.rubric.yaml")
            if path.is_file()
        }
        missing_rubrics = sorted(fixture_stems - set(rubric_paths))
        extra_rubrics = sorted(set(rubric_paths) - fixture_stems)
        for stem in missing_rubrics:
            issues.append(Issue(suite, "missing_rubric", rubric_dir / f"{stem}.rubric.yaml", "missing rubric for fixture"))
        for stem in extra_rubrics:
            issues.append(Issue(suite, "extra_rubric", rubric_paths[stem], "rubric has no matching fixture"))

    misplaced_rubrics = sorted(fixture_dir.glob("*.rubric.yaml"))
    for path in misplaced_rubrics:
        issues.append(Issue(suite, "misplaced_rubric", path, "rubric file is in fixtures directory, not configured rubrics directory"))

    for path in metadata_paths.values():
        issues.extend(check_placeholders(suite, path, "metadata"))
    for path in rubric_paths.values():
        issues.extend(check_placeholders(suite, path, "rubric"))

    return issues


def is_known(issue: Issue, known_gaps: set[tuple[str, str]]) -> bool:
    if issue.kind.startswith("placeholder_"):
        return (issue.suite, "placeholder") in known_gaps
    return (issue.suite, issue.kind) in known_gaps


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict-suites",
        default=[],
        action="append",
        help=(
            "Suite names whose unacknowledged issues should fail the command. "
            "May be repeated or comma-separated."
        ),
    )
    parser.add_argument(
        "--allow-known-gaps",
        action="store_true",
        help="Treat quarantined entries in evals/suites/QUALITY_GAPS.md as acknowledged.",
    )
    return parser.parse_args()


def normalize_strict_suites(raw_values: list[str] | None) -> set[str]:
    values = raw_values or []
    return {
        item.strip()
        for value in values
        for item in value.split(",")
        if item.strip()
    }


def main() -> int:
    args = parse_args()
    strict_suites = normalize_strict_suites(args.strict_suites)
    known_gaps = parse_quality_gaps() if args.allow_known_gaps else set()

    all_issues: list[Issue] = []
    for suite_dir in sorted(SUITES_ROOT.iterdir()):
        if not suite_dir.is_dir() or not (suite_dir / "eval.yaml").exists():
            continue
        all_issues.extend(check_suite(suite_dir))

    if not all_issues:
        print("Eval suite integrity validation passed.")
        return 0

    print("Eval suite integrity issues:")
    failing = 0
    for issue in all_issues:
        known = is_known(issue, known_gaps)
        strict = issue.suite in strict_suites
        status = "KNOWN" if known else ("ERROR" if strict else "REPORT")
        print(f"  - [{status}] {issue.suite}: {issue.kind}: {rel(issue.path)}: {issue.message}")
        if strict and not known:
            failing += 1

    if strict_suites and failing:
        print(f"\nStrict validation failed: {failing} unacknowledged issue(s).")
        return 1

    if strict_suites:
        print("\nStrict validation passed for selected suites.")
    else:
        print("\nReport mode complete; pass --strict-suites to fail on selected suites.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
