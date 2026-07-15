#!/usr/bin/env python3
"""WordPress security gate — static profile (phase 1).

Runs the WPCS security/DB sniffs over a generated artifact and, critically, runs
the **suppression differential**: phpcs is run twice — normally and with
``--ignore-annotations`` — and any violation that appears only in the second run
was hidden behind a ``// phpcs:ignore`` / ``phpcs:disable`` annotation. That is
the AI-codegen failure mode this gate exists to catch ("SQLi behind a phpcs
suppression to make the linter green").

Status split (decision #6 in
``docs/wordpress/verification-targets-decisions-2026-07-02.md``):

- **fail (hard, enters failing_gates)**: a ``WordPress.DB.Prepared*`` or
  ``WordPress.Security.EscapeOutput`` *error*, or any security-relevant
  suppression that reappears without annotations.
- **advisory (evidence for the critic, not enforced)**: every other
  ``WordPress.Security.*`` / ``WordPress.DB.*`` result. Plugin Check, PHPStan,
  and Semgrep advisory tools are phase P4.
- **blocked**: phpcs or the WordPress standard is absent — honest evidence,
  never a silent pass (mirrors the API-lint gate and the runtime phpcs check).
- **skip**: no PHP files under the artifact (decided at the oracle layer).

The pinned phpcs + WPCS toolchain is expected under ``evals/harness/php-tools``
(the same Composer root as the API-lint gate; ``vendor/`` is fetched, never
committed). Until that root carries WPCS, this gate reports ``blocked``.

Phase-1 negative space (stated in every report):

- No taint or cross-function data-flow analysis (sinks reachable from a request
  through several hops are the critic's job, and a later Psalm/Semgrep phase).
- No authorization / IDOR / capability-correctness reasoning: WPCS is silent on
  ``permission_callback => '__return_true'`` and "is this the *right* cap"; the
  ``wordpress-security-critic`` owns that adjudication.
- Plugin Check, PHPStan, and Semgrep are the P4 advisory layer, not run here.
- Block/theme JavaScript is out of scope for the static PHP profile.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bounded_subprocess import (
    BoundedProcessError,
    BoundedProcessOverflow,
    BoundedProcessTimeout,
    run_bounded,
)
import php_scanner_aliases

HARNESS_ROOT = Path(__file__).resolve().parent
DEFAULT_PHP_TOOLS_ROOT = HARNESS_ROOT / "php-tools"

SCHEMA = "wordpress-security-gate"
SCHEMA_VERSION = 1
PHPCS_STANDARD = "WordPress"

PHP_SUFFIXES = {".php"}
IGNORED_DIRS = {".git", "node_modules", "vendor", ".wp-env", "coverage", "dist", "build", "tests", "test"}
TOOL_STDOUT_LIMIT = 32 * 1024 * 1024
TOOL_STDERR_LIMIT = 2 * 1024 * 1024
MAX_TOOL_MESSAGES_PER_FILE = 5_000
MAX_TOOL_MESSAGES_TOTAL = 10_000

# The security/DB sniffs the static profile runs. Restricting --sniffs to this
# set keeps the gate focused and its JSON small and deterministic.
SECURITY_SNIFFS = (
    "WordPress.Security.EscapeOutput",
    "WordPress.Security.NonceVerification",
    "WordPress.Security.ValidatedSanitizedInput",
    "WordPress.Security.SafeRedirect",
    "WordPress.DB.PreparedSQL",
    "WordPress.DB.PreparedSQLPlaceholders",
    "WordPress.DB.DirectDatabaseQuery",
)

# Hard-fail subset (decision #6): these ERROR sources block certification.
HARD_FAIL_PREFIXES = ("WordPress.DB.PreparedSQL", "WordPress.Security.EscapeOutput")

# A suppressed violation is "security relevant" (and therefore a hard fail when
# it reappears without annotations) when its sniff is one of the security sniffs.
SECURITY_RELEVANT_PREFIXES = ("WordPress.Security.", "WordPress.DB.")
REVIEWED_SAFE_SUPPRESSION_APIS = ("get_block_wrapper_attributes",)

# Sniff-source prefix -> coarse vulnerability class for the critic's convenience.
VULN_CLASS_PREFIXES = (
    ("WordPress.DB.PreparedSQL", "sqli"),
    ("WordPress.DB.DirectDatabaseQuery", "sqli"),
    ("WordPress.Security.EscapeOutput", "xss"),
    ("WordPress.Security.ValidatedSanitizedInput", "input_validation"),
    ("WordPress.Security.NonceVerification", "csrf"),
    ("WordPress.Security.SafeRedirect", "open_redirect"),
)

NEGATIVE_SPACE = [
    "No taint or cross-function data-flow analysis in phase 1.",
    "No authorization/IDOR/capability-correctness reasoning: permission_callback and 'right capability' judgment belong to the security critic.",
    "Plugin Check, PHPStan, and Semgrep advisory tools are phase P4.",
    "Block/theme JavaScript is out of scope for the static PHP profile.",
]


@dataclass(frozen=True)
class Toolchain:
    php: str
    phpcs: Path
    installed_paths: str  # comma-joined absolute WPCS standard roots for phpcs discovery
    root: Path


class SecurityAnalysisBlocked(RuntimeError):
    """Raised when post-tool classification exceeds its reviewed budget."""


@dataclass
class SecurityParseBudget:
    deadline: float
    messages: int = 0
    by_file: dict[str, int] | None = None

    def __post_init__(self) -> None:
        self.by_file = {}

    def check_deadline(self) -> None:
        if time.monotonic() >= self.deadline:
            raise SecurityAnalysisBlocked("phpcs result analysis deadline elapsed")

    def visit_message(self, file_name: str) -> None:
        self.check_deadline()
        assert self.by_file is not None
        count = self.by_file.get(file_name, 0) + 1
        self.messages += 1
        self.by_file[file_name] = count
        if count > MAX_TOOL_MESSAGES_PER_FILE:
            raise SecurityAnalysisBlocked("phpcs message count exceeds the per-file bound")
        if self.messages > MAX_TOOL_MESSAGES_TOTAL:
            raise SecurityAnalysisBlocked("phpcs message count exceeds the aggregate bound")


def resolve_toolchain(php_tools_root: Path | None = None) -> tuple[Toolchain | None, str | None]:
    """Locate php + the pinned phpcs/WPCS toolchain, or return a blocking reason.

    NOTE (most-likely real-PHP tweak point): WPCS 3.x discovers the WordPress
    standard via phpcs ``installed_paths``. Rather than enabling the Composer
    installer plugin (php-tools keeps ``allow-plugins: false``), the gate passes
    the three standard roots to phpcs with ``--runtime-set installed_paths``.
    If a future WPCS layout changes these vendor paths, update them here.
    """
    root = (php_tools_root or DEFAULT_PHP_TOOLS_ROOT).resolve()
    php = shutil.which("php")
    if not php:
        return None, "php executable not found on PATH"
    vendor = root / "vendor"
    phpcs = vendor / "bin" / "phpcs"
    wpcs = vendor / "wp-coding-standards" / "wpcs"
    phpcsutils = vendor / "phpcsstandards" / "phpcsutils"
    phpcsextra = vendor / "phpcsstandards" / "phpcsextra"
    wp_ruleset = wpcs / "WordPress-Extra" / "ruleset.xml"
    missing = [
        str(candidate.relative_to(root))
        for candidate in (phpcs, wpcs, phpcsutils, phpcsextra, wp_ruleset)
        if not candidate.exists()
    ]
    if missing:
        return None, (
            f"pinned phpcs/WPCS toolchain incomplete under {root} (missing: {', '.join(missing)}); "
            f"run: composer install --working-dir {root}"
        )
    installed_paths = ",".join(str(p) for p in (wpcs, phpcsutils, phpcsextra))
    return Toolchain(php, phpcs, installed_paths, root), None


def iter_php_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in PHP_SUFFIXES else []
    files: list[Path] = []
    for child in path.rglob("*"):
        if not child.is_file() or child.suffix.lower() not in PHP_SUFFIXES:
            continue
        # Exclude ignored dirs by parts RELATIVE to the artifact root, so an
        # artifact that itself lives under a directory named `tests` (the
        # committed fixtures do) is still scanned while its own internal
        # tests/vendor/build dirs are not.
        if any(part in IGNORED_DIRS for part in child.relative_to(path).parts):
            continue
        files.append(child)
    return sorted(files)


def _trusted_explicit_files(scan_root: Path, explicit_files: Iterable[Path | str]) -> list[Path]:
    """Validate exact files from a factory-authentic SCAN_HANDOFF.

    This boundary is not for original untrusted artifact paths. It deliberately
    uses lexical normalization rather than ``Path.resolve()``; the handoff has
    already been created and authenticated by the no-follow staging layer.
    """
    root = Path(os.path.abspath(scan_root))
    try:
        root_mode = root.lstat().st_mode
    except OSError as exc:
        raise ValueError(f"trusted scan root is unavailable: {root}") from exc
    if not stat.S_ISDIR(root_mode):
        raise ValueError(f"trusted scan root is not a directory: {root}")

    selected: list[Path] = []
    seen: set[Path] = set()
    for raw_file in explicit_files:
        supplied = Path(raw_file)
        candidate = supplied if supplied.is_absolute() else root / supplied
        canonical = Path(os.path.abspath(candidate))
        try:
            relative = canonical.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"explicit scan file escapes trusted root: {raw_file}") from exc
        relative_text = relative.as_posix()
        if "\\" in relative_text or any(
            ord(character) < 32 or ord(character) == 127
            for character in relative_text
        ):
            raise ValueError("explicit scan filename contains an unsupported character")
        if canonical in seen:
            raise ValueError(f"duplicate explicit scan file: {canonical}")
        try:
            mode = canonical.lstat().st_mode
        except OSError as exc:
            raise ValueError(f"explicit scan file is unavailable: {canonical}") from exc
        if not stat.S_ISREG(mode):
            raise ValueError(f"explicit scan path is not a regular file: {canonical}")
        seen.add(canonical)
        selected.append(canonical)
    return selected


def _prepare_scan_files(
    path: Path,
    explicit_files: Iterable[Path | str] | None,
) -> tuple[Path, list[Path]]:
    if explicit_files is None:
        resolved = path.resolve()
        return resolved, iter_php_files(resolved)
    trusted_root = Path(os.path.abspath(path))
    return trusted_root, _trusted_explicit_files(trusted_root, explicit_files)


def _relative_file(raw_path: str, artifact_path: Path) -> str:
    base = artifact_path.resolve().parent if artifact_path.is_file() else artifact_path.resolve()
    try:
        return str(Path(raw_path).resolve().relative_to(base))
    except ValueError:
        return raw_path


def vuln_class_for(source: str) -> str:
    for prefix, vuln_class in VULN_CLASS_PREFIXES:
        if source.startswith(prefix):
            return vuln_class
    return "other"


def is_enforced(source: str, message_type: str) -> bool:
    return message_type.upper() == "ERROR" and any(source.startswith(prefix) for prefix in HARD_FAIL_PREFIXES)


def is_security_relevant(source: str, allow_prefixes: tuple[str, ...] = ()) -> bool:
    if any(source.startswith(prefix) for prefix in allow_prefixes):
        return False
    return any(source.startswith(prefix) for prefix in SECURITY_RELEVANT_PREFIXES)


def _source_lines(
    raw_path: str,
    artifact_path: Path,
    cache: dict[str, list[str]],
    budget: SecurityParseBudget,
) -> list[str]:
    budget.check_deadline()
    key = os.path.abspath(raw_path)
    if key in cache:
        return cache[key]
    source_path = Path(raw_path)
    if not source_path.is_absolute():
        base = artifact_path.resolve().parent if artifact_path.is_file() else artifact_path.resolve()
        source_path = base / source_path
    try:
        if source_path.stat().st_size > php_scanner_aliases.MAX_ALIAS_FILE_BYTES:
            raise SecurityAnalysisBlocked("phpcs source excerpt file exceeds its byte bound")
        lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    budget.check_deadline()
    cache[key] = lines
    return lines


def _source_excerpt(
    raw_path: str,
    artifact_path: Path,
    line: int | None,
    cache: dict[str, list[str]],
    budget: SecurityParseBudget,
) -> str | None:
    if not line:
        return None
    try:
        return _source_lines(raw_path, artifact_path, cache, budget)[line - 1].strip()
    except IndexError:
        return None


def reviewed_safe_suppression_api(violation: dict[str, Any]) -> str | None:
    """Return a known-safe WordPress helper for a reviewed suppression, if any."""
    if violation["source"] != "WordPress.Security.EscapeOutput.OutputNotEscaped":
        return None
    haystack = " ".join(str(violation.get(key) or "") for key in ("message", "source_excerpt"))
    for api in REVIEWED_SAFE_SUPPRESSION_APIS:
        if api in haystack:
            return api
    return None


def parse_phpcs_output(
    output: dict[str, Any],
    artifact_path: Path,
    budget: SecurityParseBudget | None = None,
    source_cache: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Flatten phpcs `--report=json` into a sorted list of violation records.

    Pure function over recorded JSON — the hermetic unit-test surface.
    """
    budget = budget or SecurityParseBudget(time.monotonic() + 120)
    source_cache = source_cache if source_cache is not None else {}
    violations: list[dict[str, Any]] = []
    for raw_file, file_result in (output.get("files") or {}).items():
        rel_file = _relative_file(raw_file, artifact_path)
        messages = file_result.get("messages", [])
        if not isinstance(messages, list):
            raise SecurityAnalysisBlocked("phpcs messages payload is not a list")
        for message in messages:
            budget.visit_message(rel_file)
            source = str(message.get("source") or "")
            violations.append(
                {
                    "file": rel_file,
                    "line": message.get("line"),
                    "column": message.get("column"),
                    "source": source,
                    "type": str(message.get("type") or "").upper(),
                    "severity": message.get("severity"),
                    "fixable": bool(message.get("fixable")),
                    "message": str(message.get("message") or ""),
                    "source_excerpt": _source_excerpt(
                        str(raw_file), artifact_path, message.get("line"),
                        source_cache, budget,
                    ),
                }
            )
    violations.sort(key=lambda item: (item["file"], item["line"] or 0, item["source"]))
    return violations


def _violation_key(violation: dict[str, Any]) -> tuple[str, Any, str]:
    return (violation["file"], violation["line"], violation["source"])


def diff_suppressions(
    normal: list[dict[str, Any]],
    ignored: list[dict[str, Any]],
    allow_prefixes: tuple[str, ...] = (),
    budget: SecurityParseBudget | None = None,
) -> list[dict[str, Any]]:
    """Violations present only under ``--ignore-annotations`` = suppressed.

    Pure function — the hermetic unit-test surface for the differential.
    """
    normal_keys = {_violation_key(v) for v in normal}
    suppressed: list[dict[str, Any]] = []
    for violation in ignored:
        if budget is not None:
            budget.check_deadline()
        if _violation_key(violation) in normal_keys:
            continue
        reviewed_safe_api = reviewed_safe_suppression_api(violation)
        suppressed.append(
            {
                "file": violation["file"],
                "line": violation["line"],
                "annotation": "phpcs:ignore",
                "suppressed_rules": [violation["source"]],
                "security_relevant": False if reviewed_safe_api else is_security_relevant(violation["source"], allow_prefixes),
                "reappears_without_annotations": True,
                "vuln_class": vuln_class_for(violation["source"]),
                "message": violation["message"],
                "source_excerpt": violation.get("source_excerpt"),
                "reviewed_safe_api": reviewed_safe_api,
            }
        )
    suppressed.sort(key=lambda item: (item["file"], item["line"] or 0, item["suppressed_rules"][0]))
    return suppressed


def classify(
    violations: list[dict[str, Any]],
    suppressed: list[dict[str, Any]],
    budget: SecurityParseBudget | None = None,
) -> tuple[list[dict[str, Any]], str, dict[str, int]]:
    """Apply the hard/advisory status split. Pure function.

    Returns (findings, status, summary).
    """
    findings: list[dict[str, Any]] = []
    errors = warnings = advisory = 0
    for violation in violations:
        if budget is not None:
            budget.check_deadline()
        enforced = is_enforced(violation["source"], violation["type"])
        if violation["type"] == "ERROR":
            errors += 1
        elif violation["type"] == "WARNING":
            warnings += 1
        if not enforced:
            advisory += 1
        findings.append(
            {
                "tool": "phpcs",
                "rule_id": violation["source"],
                "file": violation["file"],
                "line": violation["line"],
                "severity": "error" if violation["type"] == "ERROR" else "warning",
                "vuln_class": vuln_class_for(violation["source"]),
                "enforced": enforced,
                "message": violation["message"],
                "source_excerpt": violation.get("source_excerpt"),
            }
        )
    suppressed_security = sum(1 for entry in suppressed if entry["security_relevant"])
    reviewed_suppressed = sum(1 for entry in suppressed if entry.get("reviewed_safe_api"))
    enforced_fail = any(finding["enforced"] for finding in findings)
    status = "fail" if (enforced_fail or suppressed_security) else "pass"
    summary = {
        "errors": errors,
        "warnings": warnings,
        "advisory": advisory,
        "suppressed_security": suppressed_security,
        "reviewed_suppressed": reviewed_suppressed,
    }
    return findings, status, summary


def summarize_report(report: dict[str, Any]) -> str:
    status = report.get("status")
    if status == "blocked":
        return str(report.get("blocked_reason") or "security gate blocked")
    if status == "skip":
        return "no PHP files to scan"
    suppressed = [entry for entry in report.get("suppressed_annotations", []) if entry.get("security_relevant")]
    enforced = [finding for finding in report.get("findings", []) if finding.get("enforced")]
    if status == "pass":
        advisory = report.get("summary", {}).get("advisory", 0)
        note = f"; {advisory} advisory finding(s) for the critic" if advisory else ""
        return f"no enforced security violations{note}"
    parts: list[str] = []
    for finding in enforced[:3]:
        parts.append(f"{finding['rule_id']} {finding['severity']} at {finding['file']}:{finding['line']}")
    for entry in suppressed[:3]:
        parts.append(
            f"suppressed {entry['suppressed_rules'][0]} reappears without annotations at {entry['file']}:{entry['line']}"
        )
    remainder = (len(enforced) + len(suppressed)) - len(parts)
    suffix = f"; +{remainder} more in security-gate.json" if remainder > 0 else ""
    return f"{len(enforced) + len(suppressed)} enforced finding(s): " + "; ".join(parts) + suffix


def _run_phpcs(
    toolchain: Toolchain,
    file_list: Path,
    basepath: Path,
    ignore_annotations: bool,
    deadline_monotonic: float,
) -> tuple[int | None, dict[str, Any] | None, str, list[str]]:
    command = [
        toolchain.php,
        str(toolchain.phpcs),
        f"--standard={PHPCS_STANDARD}",
        "--sniffs=" + ",".join(SECURITY_SNIFFS),
        "--report=json",
        "--runtime-set",
        "installed_paths",
        toolchain.installed_paths,
        f"--basepath={basepath}",
        f"--file-list={file_list}",
        "-d",
        "memory_limit=512M",
    ]
    if ignore_annotations:
        command.append("--ignore-annotations")
    if deadline_monotonic <= time.monotonic():
        return None, None, "phpcs deadline elapsed before launch", command
    try:
        proc = run_bounded(
            command, deadline_monotonic=deadline_monotonic,
            stdout_limit=TOOL_STDOUT_LIMIT, stderr_limit=TOOL_STDERR_LIMIT,
        )
    except BoundedProcessTimeout as exc:
        return None, None, f"phpcs blocked: {exc}", command
    except BoundedProcessOverflow as exc:
        return None, None, f"phpcs output blocked: {exc}", command
    except (BoundedProcessError, OSError) as exc:
        return None, None, f"phpcs execution blocked: {exc}", command
    if proc.returncode not in (0, 1, 2):
        detail = (proc.stderr or proc.stdout).strip()[:400]
        return proc.returncode, None, f"phpcs exited {proc.returncode}: {detail}", command
    try:
        return proc.returncode, json.loads(proc.stdout), proc.stderr, command
    except json.JSONDecodeError:
        detail = (proc.stderr or proc.stdout).strip()[:400]
        return proc.returncode, None, detail, command


def _new_security_report(path: Path, allow: tuple[str, ...]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "target": str(path),
        "profile": "static",
        "status": "blocked",
        "blocked_reason": None,
        "tools": [],
        "findings": [],
        "suppressed_annotations": [],
        "summary": {"errors": 0, "warnings": 0, "advisory": 0, "suppressed_security": 0, "reviewed_suppressed": 0},
        "allow_suppression_prefixes": list(allow),
        "negative_space": list(NEGATIVE_SPACE),
    }


def _write_phpcs_file_list(file_list: Path, php_files: list[Path]) -> None:
    paths = [str(file_path) for file_path in php_files]
    if any("\n" in path or "\r" in path for path in paths):
        raise ValueError("phpcs file-list path contains a line break")
    file_list.write_text("\n".join(paths) + "\n", encoding="utf-8")


def _tool_record(
    tool_id: str,
    returncode: int | None,
    output: dict[str, Any] | None,
    command: list[str],
) -> dict[str, Any]:
    return {
        "id": tool_id,
        "status": "pass" if output is not None else "blocked",
        "returncode": returncode,
        "command": command,
    }


def _run_phpcs_pair(
    report: dict[str, Any],
    toolchain: Toolchain,
    php_files: list[Path],
    basepath: Path,
    deadline_monotonic: float,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    with tempfile.TemporaryDirectory(prefix="wp-security-gate-") as tmp:
        file_list = Path(tmp) / "phpcs-files.txt"
        try:
            _write_phpcs_file_list(file_list, php_files)
        except (OSError, ValueError) as exc:
            return None, None, f"phpcs file-list blocked: {exc}"
        rc_a, out_a, err_a, command_a = _run_phpcs(
            toolchain, file_list, basepath, False, deadline_monotonic
        )
        report["tools"].append(_tool_record("phpcs-security", rc_a, out_a, command_a))
        if out_a is None:
            return None, None, err_a
        rc_b, out_b, err_b, command_b = _run_phpcs(
            toolchain, file_list, basepath, True, deadline_monotonic
        )
        report["tools"].append(_tool_record("phpcs-suppression-diff", rc_b, out_b, command_b))
        return out_a, out_b, err_b


def _classify_security_report(
    report: dict[str, Any],
    path: Path,
    allow: tuple[str, ...],
    normal_output: dict[str, Any],
    ignored_output: dict[str, Any],
    deadline_monotonic: float,
) -> dict[str, Any]:
    budget = SecurityParseBudget(deadline_monotonic)
    source_cache: dict[str, list[str]] = {}
    violations = parse_phpcs_output(normal_output, path, budget, source_cache)
    ignored_violations = parse_phpcs_output(ignored_output, path, budget, source_cache)
    suppressed = diff_suppressions(violations, ignored_violations, allow, budget)
    findings, status, summary = classify(violations, suppressed, budget)
    report.update({
        "findings": findings, "suppressed_annotations": suppressed,
        "summary": summary, "status": status, "blocked_reason": None,
    })
    report["tools"][0]["status"] = "fail" if any(item["enforced"] for item in findings) else "pass"
    report["tools"][1]["status"] = "fail" if summary["suppressed_security"] else "pass"
    report["analysis_usage"] = {"tool_messages": budget.messages}
    return report


def _run_security_tools(
    report, toolchain, path, php_files, explicit_files,
    explicit_alias_names, explicit_alias_members, deadline,
):
    scan_root = path if path.is_dir() else path.parent
    if explicit_files is None:
        return _run_phpcs_pair(report, toolchain, php_files, scan_root, deadline)
    names = explicit_alias_names or php_scanner_aliases.default_alias_names(php_files)
    with php_scanner_aliases.stage_aliases(
        php_files, names, deadline, explicit_alias_members
    ) as aliases:
        report["scanner_aliases"] = php_scanner_aliases.evidence(aliases, scan_root)
        out_a, out_b, error = _run_phpcs_pair(
            report, toolchain, list(aliases.files), aliases.root, deadline
        )
        if out_a is not None:
            out_a = php_scanner_aliases.remap_output_files(out_a, aliases)
        if out_b is not None:
            out_b = php_scanner_aliases.remap_output_files(out_b, aliases)
        return out_a, out_b, error


def run_security_gate(
    path: Path,
    timeout_sec: int = 120,
    php_tools_root: Path | None = None,
    allow_suppression_prefixes: list[str] | None = None,
    explicit_files: Iterable[Path | str] | None = None,
    explicit_alias_names: dict[Path, str] | None = None,
    explicit_alias_members: dict[Path, tuple[int, str]] | None = None,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    deadline = deadline_monotonic if deadline_monotonic is not None else time.monotonic() + timeout_sec
    path, php_files = _prepare_scan_files(path, explicit_files)
    allow = tuple(allow_suppression_prefixes or ())
    report = _new_security_report(path, allow)
    if not php_files:
        report["status"] = "skip"
        return report

    toolchain, blocked_reason = resolve_toolchain(php_tools_root)
    if toolchain is None:
        report["blocked_reason"] = blocked_reason
        return report

    try:
        out_a, out_b, error = _run_security_tools(
            report, toolchain, path, php_files, explicit_files,
            explicit_alias_names, explicit_alias_members, deadline,
        )
    except (OSError, TimeoutError, ValueError) as exc:
        report["blocked_reason"] = f"PHP scanner alias blocked: {exc}"
        return report
    if out_a is None or out_b is None:
        report["blocked_reason"] = f"phpcs did not produce parseable JSON: {error}"
        return report
    try:
        return _classify_security_report(report, path, allow, out_a, out_b, deadline)
    except SecurityAnalysisBlocked as exc:
        report["blocked_reason"] = str(exc)
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WordPress security gate — static profile (WPCS security sniffs + suppression differential).")
    parser.add_argument("--path", required=True, help="Generated artifact directory or PHP file.")
    parser.add_argument("--timeout-sec", type=int, default=120)
    parser.add_argument("--php-tools-root", type=Path, help=f"Composer toolchain root (default: {DEFAULT_PHP_TOOLS_ROOT}).")
    parser.add_argument(
        "--allow-suppression-prefix",
        action="append",
        help="Sniff-source prefix whose suppression degrades to advisory instead of failing. May be repeated.",
    )
    parser.add_argument("--out", type=Path, help="Optional path to write the security-gate.json report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_security_gate(
        Path(args.path),
        timeout_sec=args.timeout_sec,
        php_tools_root=args.php_tools_root,
        allow_suppression_prefixes=args.allow_suppression_prefix,
    )
    serialized = json.dumps(report, indent=2, sort_keys=True)
    print(serialized)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(serialized + "\n", encoding="utf-8")
    if report["status"] in {"pass", "skip"}:
        return 0
    if report["status"] == "blocked":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
