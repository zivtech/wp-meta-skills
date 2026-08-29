#!/usr/bin/env python3
"""Validate the evidence log.

`docs/wordpress/negative-results.md` is the record of what this project
measured, and its whole value is that a reader can follow any row back to a
committed artifact. A log that decays into prose is worse than no log, because
it reads like evidence while citing nothing.

So the log is itself gated, which is the correct joke to make at our own
expense. Every row must:

- cite an `analysis` path that exists in this repository;
- declare an archive state from a closed vocabulary, and if it claims `in-repo`,
  that path must exist;
- name a `re-run` harness that exists, or say plainly that there is none;
- state what the result does NOT license, not only what it does.

The last one is the check that matters most and is the easiest to lose. A claim
column that only says what a result supports is how a negative-results log turns
back into marketing.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "docs" / "wordpress" / "negative-results.md"
EVIDENCE_INDEX = ROOT / "EVIDENCE.md"

NULL_TABLE_HEADER = "| # | What was tested |"
POSITIVE_TABLE_HEADER = "| # | What was proven |"

ARCHIVE_IN_REPO = "in-repo"
ARCHIVE_MONOREPO = "monorepo-internal"
ARCHIVE_STATES = (ARCHIVE_IN_REPO, ARCHIVE_MONOREPO)

# A row may decline a harness, but only in words that make the absence visible.
NO_RERUN_PHRASES = ("not applicable", "none")

# Every claim cell has to carry an explicit boundary. These are the ways the log
# spells one; a cell with none of them is a claim without negative space.
NEGATIVE_SPACE_MARKERS = ("does **not** license", "does not license")

INLINE_PATH_RE = re.compile(r"`([^`\n]+)`")
ROW_ID_RE = re.compile(r"^[NP][0-9]+$")

MIN_NULL_ROWS = 5
MIN_POSITIVE_ROWS = 3


@dataclass(frozen=True)
class Issue:
    row: str
    message: str

    def render(self) -> str:
        return f"{self.row}: {self.message}"


def _cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _table_rows(text: str, header: str) -> list[list[str]]:
    """Return the data rows of the table whose header line starts with `header`."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith(header):
            continue
        rows: list[list[str]] = []
        for candidate in lines[index + 2:]:
            if not candidate.strip().startswith("|"):
                break
            cells = _cells(candidate)
            if cells:
                rows.append(cells)
        return rows
    return []


def _first_path(cell: str) -> str | None:
    match = INLINE_PATH_RE.search(cell)
    return match.group(1).strip() if match else None


def _safe_repo_path(value: str) -> Path | None:
    """Resolve a repo-relative path, refusing absolute paths and traversal."""
    if value.startswith(("/", "\\")) or "\\" in value or ".." in value.split("/"):
        return None
    candidate = (ROOT / value).resolve()
    try:
        candidate.relative_to(ROOT)
    except ValueError:
        return None
    return candidate


def _check_cited_path(row_id: str, cell: str, label: str) -> list[Issue]:
    raw = _first_path(cell)
    if raw is None:
        return [Issue(row_id, f"{label} cites no backticked path")]
    resolved = _safe_repo_path(raw)
    if resolved is None:
        return [Issue(row_id, f"{label} path `{raw}` escapes the repository")]
    if not resolved.exists():
        return [Issue(
            row_id,
            f"{label} path `{raw}` does not exist. Re-point it or drop the row;"
            " do not soften it into prose.",
        )]
    return []


def _check_claim(row_id: str, cell: str) -> list[Issue]:
    lowered = cell.lower()
    if not any(marker in lowered for marker in NEGATIVE_SPACE_MARKERS):
        return [Issue(
            row_id,
            "claim column states what the result licenses but not what it does"
            " NOT license; every row needs an explicit boundary",
        )]
    return []


def _check_archive(row_id: str, cell: str) -> list[Issue]:
    value = cell.strip()
    if value.startswith("`") and value.endswith("`"):
        path = value.strip("`")
        resolved = _safe_repo_path(path)
        if resolved is None:
            return [Issue(row_id, f"archive path `{path}` escapes the repository")]
        if not resolved.exists():
            return [Issue(row_id, f"archive claims in-repo path `{path}`, which does not exist")]
        return []
    if value == ARCHIVE_MONOREPO:
        return []
    if value == ARCHIVE_IN_REPO:
        return [Issue(row_id, "archive says `in-repo` without naming the path")]
    return [Issue(
        row_id,
        f"archive state `{value}` is not one of {ARCHIVE_STATES} or a backticked in-repo path",
    )]


def _check_rerun(row_id: str, cell: str) -> list[Issue]:
    lowered = cell.lower()
    if any(phrase in lowered for phrase in NO_RERUN_PHRASES):
        return []
    return _check_cited_path(row_id, cell, "re-run harness")


def validate_null_rows(rows: list[list[str]]) -> list[Issue]:
    issues: list[Issue] = []
    if len(rows) < MIN_NULL_ROWS:
        issues.append(Issue(
            "null table",
            f"expected at least {MIN_NULL_ROWS} rows, found {len(rows)};"
            " a shrinking negative-results table is the failure mode this gate exists for",
        ))
    for cells in rows:
        if len(cells) != 8:
            issues.append(Issue(cells[0] if cells else "?", f"expected 8 columns, found {len(cells)}"))
            continue
        row_id = cells[0]
        if not ROW_ID_RE.fullmatch(row_id):
            issues.append(Issue(row_id, "row id must look like N1 or P1"))
        issues.extend(_check_claim(row_id, cells[4]))
        issues.extend(_check_cited_path(row_id, cells[5], "analysis"))
        issues.extend(_check_archive(row_id, cells[6]))
        issues.extend(_check_rerun(row_id, cells[7]))
    return issues


def validate_positive_rows(rows: list[list[str]]) -> list[Issue]:
    issues: list[Issue] = []
    if len(rows) < MIN_POSITIVE_ROWS:
        issues.append(Issue(
            "positive table",
            f"expected at least {MIN_POSITIVE_ROWS} rows, found {len(rows)};"
            " a log carrying only nulls misrepresents the record as badly as one carrying only wins",
        ))
    for cells in rows:
        if len(cells) != 6:
            issues.append(Issue(cells[0] if cells else "?", f"expected 6 columns, found {len(cells)}"))
            continue
        row_id = cells[0]
        if not ROW_ID_RE.fullmatch(row_id):
            issues.append(Issue(row_id, "row id must look like N1 or P1"))
        issues.extend(_check_claim(row_id, cells[3]))
        issues.extend(_check_cited_path(row_id, cells[4], "analysis"))
        issues.extend(_check_archive(row_id, cells[5]))
    return issues


def validate_structure(text: str) -> list[Issue]:
    issues: list[Issue] = []
    for heading in ("## How to read this log", "## What this log does not cover"):
        if heading not in text:
            issues.append(Issue("structure", f"missing required section `{heading}`"))
    return issues


def validate_index() -> list[Issue]:
    """The log has to be reachable from the surface a reader actually opens."""
    if not EVIDENCE_INDEX.is_file():
        return [Issue("EVIDENCE.md", "root evidence index is missing")]
    text = EVIDENCE_INDEX.read_text(encoding="utf-8")
    if "docs/wordpress/negative-results.md" not in text:
        return [Issue("EVIDENCE.md", "root evidence index does not point at the evidence log")]
    return []


def validate_all() -> list[Issue]:
    if not LOG_PATH.is_file():
        return [Issue("evidence log", f"{LOG_PATH.relative_to(ROOT)} is missing")]
    text = LOG_PATH.read_text(encoding="utf-8")
    issues = validate_structure(text)
    issues.extend(validate_null_rows(_table_rows(text, NULL_TABLE_HEADER)))
    issues.extend(validate_positive_rows(_table_rows(text, POSITIVE_TABLE_HEADER)))
    issues.extend(validate_index())
    return issues


def main() -> int:
    issues = validate_all()
    if issues:
        print("Evidence log validation failed:")
        for issue in issues:
            print(f"  - {issue.render()}")
        return 1
    print("Evidence log validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
