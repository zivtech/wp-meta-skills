#!/usr/bin/env python3
"""Deterministic oracle for generated WordPress artifacts.

This is the next layer after `validate_wordpress_executor_packet.py`: it checks
files produced by a WordPress executor, not the executor's markdown packet. The
default `static` profile has no network and no WordPress runtime dependency. The
`runtime` profile makes selected external tools required and reports missing
tooling as `blocked`, not as a pass.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import artifact_staging
import artifact_execution
import artifact_snapshot_scan
import runtime_artifact_pipeline
import wp_api_lint
import wp_security_gate


ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {".php", ".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".scss", ".md", ".txt", ".html"}
PHP_SUFFIXES = {".php"}

BANNED_UNSAFE_PATTERNS = (
    r"\brm\s+-rf\b",
    r"\bchmod\s+777\b",
    r"\bdrop\s+table\b",
    r"\bdelete\s+from\b",
    r"\bwp\s+db\s+reset\b",
    r"\bwp\s+site\s+empty\b",
)

SECRETISH_RE = re.compile(r"(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*['\"][^'\"]{12,}")
PHPCS_IGNORE_PATTERNS = ("*.asset.php", "*/node_modules/*", "*/vendor/*")
@dataclass(frozen=True)
class Check:
    id: str
    status: str
    required: bool
    detail: str
    command: list[str] | None = None

    @property
    def passed(self) -> bool:
        return self.status == "pass"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def iter_files(path: Path, suffixes: set[str]) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in suffixes else []
    ignored = {".git", "node_modules", "vendor", ".wp-env", "coverage", "dist", "build"}
    files: list[Path] = []
    for child in path.rglob("*"):
        if any(part in ignored for part in child.parts):
            continue
        if child.is_file() and child.suffix.lower() in suffixes:
            files.append(child)
    return sorted(files)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def aggregate_text(path: Path) -> str:
    chunks: list[str] = []
    for file_path in iter_files(path, TEXT_SUFFIXES):
        chunks.append(read_text(file_path))
    return "\n".join(chunks)


def pass_check(check_id: str, detail: str, required: bool = True) -> Check:
    return Check(check_id, "pass", required, detail)


def fail_check(check_id: str, detail: str, required: bool = True) -> Check:
    return Check(check_id, "fail", required, detail)


def block_check(check_id: str, detail: str, required: bool = True, command: list[str] | None = None) -> Check:
    return Check(check_id, "blocked", required, detail, command)


def skip_check(check_id: str, detail: str, command: list[str] | None = None) -> Check:
    return Check(check_id, "skip", False, detail, command)


def check_path(path: Path) -> Check:
    if not path.exists():
        return fail_check("artifact_path", f"path does not exist: {path}")
    if not path.is_file() and not path.is_dir():
        return fail_check("artifact_path", f"path is not a file or directory: {path}")
    return pass_check("artifact_path", f"path exists: {repo_relative(path)}")


def check_no_unsafe_text(path: Path) -> Check:
    text = aggregate_text(path)
    lower = text.lower()
    hits = [pattern for pattern in BANNED_UNSAFE_PATTERNS if re.search(pattern, lower)]
    if hits:
        return fail_check("unsafe_commands", f"unsafe destructive patterns found: {', '.join(hits)}")
    return pass_check("unsafe_commands", "no banned destructive command patterns found")


def check_no_hardcoded_secrets(path: Path) -> Check:
    hits: list[str] = []
    for file_path in iter_files(path, TEXT_SUFFIXES):
        if SECRETISH_RE.search(read_text(file_path)):
            hits.append(repo_relative(file_path))
    if hits:
        return fail_check("hardcoded_secrets", f"secret-like assignments found in: {', '.join(hits)}")
    return pass_check("hardcoded_secrets", "no long secret-like assignments found")


def check_plugin_header(path: Path) -> Check:
    php_files = iter_files(path, PHP_SUFFIXES)
    header_files = [file_path for file_path in php_files if "Plugin Name:" in read_text(file_path)[:8192]]
    if not header_files:
        return fail_check("plugin_header", "no PHP file contains a WordPress plugin header with Plugin Name")
    return pass_check("plugin_header", f"plugin header found in {repo_relative(header_files[0])}")


def check_plugin_security_heuristics(path: Path) -> Check:
    text = aggregate_text(path).lower()
    issues: list[str] = []
    if "register_rest_route" in text and "permission_callback" not in text:
        issues.append("register_rest_route without permission_callback")
    ajax_or_post = "wp_ajax_" in text or "admin_post_" in text
    if ajax_or_post and "current_user_can" not in text:
        issues.append("AJAX/admin-post handler without current_user_can")
    if ajax_or_post and not any(term in text for term in ("check_ajax_referer", "check_admin_referer", "wp_verify_nonce")):
        issues.append("AJAX/admin-post handler without nonce verification")
    sql_and_request = "$wpdb->" in text and any(term in text for term in ("$_get", "$_post", "$_request"))
    if sql_and_request and "$wpdb->prepare" not in text:
        issues.append("$wpdb query touches request input without $wpdb->prepare")
    if issues:
        return fail_check("plugin_security_heuristics", "; ".join(issues))
    return pass_check("plugin_security_heuristics", "admin, REST, AJAX, and SQL heuristics passed")


def _looks_like_short_array_literal(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith(("*", "//", "#")):
        return False
    return (
        stripped == "["
        or stripped.startswith(("[ ", "['", '["'))
        or "=> [" in stripped
        or "= [" in stripped
        or stripped.startswith("return [")
    )


def check_php_wpcs_shape_heuristics(path: Path) -> Check:
    issues: list[str] = []
    for php_file in iter_files(path, PHP_SUFFIXES):
        text = read_text(php_file)
        header = text[:8192]
        if "Plugin Name:" in header and "@package" not in header:
            issues.append(f"{repo_relative(php_file)} missing file-level @package tag")
        short_array_lines = [
            f"{repo_relative(php_file)}:{line_no}"
            for line_no, line in enumerate(text.splitlines(), start=1)
            if _looks_like_short_array_literal(line)
        ]
        if short_array_lines:
            issues.append(f"short array syntax found at {', '.join(short_array_lines[:8])}")
    if issues:
        return fail_check("php_wpcs_shape_heuristics", "; ".join(issues))
    return pass_check("php_wpcs_shape_heuristics", "PHP files satisfy cheap WPCS shape checks")


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value))


def _declares_wp_minimum(text: str, minimum: str) -> bool:
    match = re.search(r"(?im)^\s*\*?\s*Requires at least:\s*([0-9.]+)\s*$", text)
    if not match:
        return False
    declared = _version_tuple(match.group(1))
    required = _version_tuple(minimum)
    return declared >= required


def _has_function_exists_guard(text: str, function_name: str) -> bool:
    return bool(
        re.search(
            rf"function_exists\s*\(\s*['\"]{re.escape(function_name)}['\"]\s*\)",
            text,
            re.IGNORECASE,
        )
    )


def check_plugin_ai_surface_heuristics(path: Path) -> Check:
    text = aggregate_text(path)
    code_text = "\n".join(read_text(file_path) for file_path in iter_files(path, PHP_SUFFIXES))
    lower = text.lower()
    code_lower = code_text.lower()
    issues: list[str] = []

    if "wp_register_ability" in lower:
        if "wp_abilities_api_init" not in lower:
            issues.append("wp_register_ability() without wp_abilities_api_init registration hook")
        missing_args = [
            arg
            for arg in (
                "label",
                "description",
                "category",
                "input_schema",
                "output_schema",
                "execute_callback",
                "permission_callback",
            )
            if arg not in lower
        ]
        if missing_args:
            issues.append(f"wp_register_ability() missing args: {', '.join(missing_args)}")
        if not _declares_wp_minimum(text, "6.9") and not _has_function_exists_guard(text, "wp_register_ability"):
            issues.append("Abilities API used without Requires at least: 6.9 or function_exists guard")

    if "wp_ai_client_prompt" in lower:
        if not _declares_wp_minimum(text, "7.0") and not _has_function_exists_guard(text, "wp_ai_client_prompt"):
            issues.append("wp_ai_client_prompt() used without Requires at least: 7.0 or function_exists guard")
        if "is_wp_error" not in lower:
            issues.append("wp_ai_client_prompt() result lacks is_wp_error() handling")
        if not any(term in lower for term in ("current_user_can", "permission_callback", "wp_ai_client_prevent_prompt")):
            issues.append("AI Client call lacks capability or prompt-prevention boundary")

    uses_mcp_adapter = any(term in code_lower for term in ("wordpress/mcp-adapter", "mcp_adapter_init", "mcpadapter::instance"))
    if uses_mcp_adapter:
        if "mcp_adapter_init" not in code_lower and "mcpadapter::instance" not in code_lower:
            issues.append("MCP Adapter referenced without mcp_adapter_init or McpAdapter::instance() initialization")
        if "wp_register_ability" not in code_lower and "core/" not in code_lower:
            issues.append("MCP Adapter referenced without named abilities to expose")

    if issues:
        return fail_check("plugin_ai_surface_heuristics", "; ".join(issues))
    return pass_check("plugin_ai_surface_heuristics", "Abilities, MCP Adapter, and AI Client heuristics passed")


def load_json_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        return None, f"{repo_relative(path)} is invalid JSON: {exc}"
    if not isinstance(data, dict):
        return None, f"{repo_relative(path)} must contain a JSON object"
    return data, None


def check_block_metadata(path: Path) -> Check:
    block_files = [file_path for file_path in iter_files(path, {".json"}) if file_path.name == "block.json"]
    if not block_files:
        return fail_check("block_metadata", "no block.json file found")
    errors: list[str] = []
    for block_file in block_files:
        data, error = load_json_file(block_file)
        if error:
            errors.append(error)
            continue
        missing = [key for key in ("name", "title", "category") if not data.get(key)]
        if missing:
            errors.append(f"{repo_relative(block_file)} missing keys: {', '.join(missing)}")
    if errors:
        return fail_check("block_metadata", "; ".join(errors))
    return pass_check("block_metadata", f"{len(block_files)} block.json file(s) parsed with required keys")


def check_block_registration(path: Path) -> Check:
    text = aggregate_text(path)
    package_json = path / "package.json" if path.is_dir() else None
    package_has_scripts = False
    if package_json and package_json.exists():
        data, _error = load_json_file(package_json)
        package_has_scripts = bool(data and data.get("scripts"))
    if "register_block_type" in text or package_has_scripts:
        return pass_check("block_registration", "server registration or build scripts present")
    return fail_check("block_registration", "no register_block_type call or package scripts found")


def check_theme_metadata(path: Path) -> Check:
    style_css = path / "style.css" if path.is_dir() else None
    theme_json = path / "theme.json" if path.is_dir() else None
    has_style = bool(style_css and style_css.exists() and "Theme Name:" in read_text(style_css)[:8192])
    has_theme_json = False
    if theme_json and theme_json.exists():
        data, error = load_json_file(theme_json)
        if error:
            return fail_check("theme_metadata", error)
        has_theme_json = isinstance(data, dict)
    if has_style or has_theme_json:
        return pass_check("theme_metadata", "style.css theme header or valid theme.json present")
    return fail_check("theme_metadata", "missing style.css Theme Name header and theme.json")


def blueprint_file(path: Path) -> Path | None:
    if path.is_file():
        return path
    candidates = [path / "blueprint.json", path / "playground-blueprint.json"]
    candidates += sorted(path.glob("*.json"))
    return next((candidate for candidate in candidates if candidate.exists()), None)


def check_blueprint_json(path: Path) -> Check:
    candidate = blueprint_file(path)
    if not candidate:
        return fail_check("blueprint_json", "no Blueprint JSON file found")
    data, error = load_json_file(candidate)
    if error:
        return fail_check("blueprint_json", error)
    steps = data.get("steps") if data else None
    if not isinstance(steps, list) or not steps:
        return fail_check("blueprint_json", f"{repo_relative(candidate)} must contain a non-empty steps array")
    return pass_check("blueprint_json", f"{repo_relative(candidate)} contains {len(steps)} step(s)")


def run_command(command: list[str], cwd: Path, timeout_sec: int) -> CommandResult:
    proc = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout_sec)
    return CommandResult(proc.returncode, proc.stdout[-4000:], proc.stderr[-4000:])


def find_executable(path: Path, names: tuple[str, ...], extra_roots: list[Path] | None = None) -> str | None:
    search_roots = [path] if path.is_dir() else [path.parent]
    search_roots.extend(extra_roots or [])
    search_roots.append(ROOT)
    for root in search_roots:
        for name in names:
            local = root / "vendor" / "bin" / name
            if local.exists():
                return str(local)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def command_check(check_id: str, command: list[str], cwd: Path, timeout_sec: int, required: bool = True) -> Check:
    try:
        result = run_command(command, cwd, timeout_sec)
    except FileNotFoundError:
        return block_check(check_id, f"command not found: {command[0]}", required, command)
    except subprocess.TimeoutExpired:
        return fail_check(check_id, f"command timed out after {timeout_sec}s", required)
    detail = f"exit {result.returncode}"
    if result.stdout.strip():
        detail += f"; stdout: {result.stdout.strip()[:500]}"
    if result.stderr.strip():
        detail += f"; stderr: {result.stderr.strip()[:500]}"
    if result.returncode == 0:
        return Check(check_id, "pass", required, detail, command)
    return Check(check_id, "fail", required, detail, command)


def check_php_lint(path: Path, timeout_sec: int, required: bool) -> Check:
    php_files = iter_files(path, PHP_SUFFIXES)
    if not php_files:
        return skip_check("php_lint", "no PHP files found")
    php = shutil.which("php")
    if not php:
        return block_check("php_lint", "php executable not found", required)
    for php_file in php_files:
        result = command_check("php_lint", [php, "-l", str(php_file)], ROOT, timeout_sec, required)
        if result.status != "pass":
            return result
    return pass_check("php_lint", f"php -l passed for {len(php_files)} PHP file(s)", required)


def check_phpcs(path: Path, args: argparse.Namespace, required: bool) -> Check:
    if "wpcs" in set(args.require_tool or []):
        root = Path(args.wp_env_root).resolve() if args.wp_env_root else None
        toolchain, reason = wp_security_gate.resolve_toolchain(root)
        if toolchain is None:
            return block_check("phpcs_wpcs", reason or "pinned WPCS toolchain unavailable", required)
        prefix = [toolchain.php, str(toolchain.phpcs), "--runtime-set",
                  "installed_paths", toolchain.installed_paths]
        standards = command_check("phpcs_wpcs", [*prefix, "-i"], toolchain.root,
                                  args.timeout_sec, required)
        if standards.status != "pass":
            return standards
        if "WordPress" not in standards.detail:
            return block_check("phpcs_wpcs", "pinned WordPress standard was not discovered",
                               required, [*prefix, "-i"])
        command = [*prefix, "--standard=WordPress", "--extensions=php",
                   f"--ignore={','.join(PHPCS_IGNORE_PATTERNS)}", str(path)]
        return command_check("phpcs_wpcs", command, toolchain.root,
                             args.timeout_sec, required)
    extra_roots = [Path(root).resolve() for root in (args.wp_env_root, args.wp_root) if root]
    phpcs = find_executable(path, ("phpcs",), extra_roots)
    if not phpcs:
        return block_check("phpcs_wpcs", "phpcs executable not found", required)
    standards = command_check("phpcs_wpcs", [phpcs, "-i"], ROOT, args.timeout_sec, required)
    if standards.status != "pass":
        return standards
    if "WordPress" not in standards.detail:
        return block_check("phpcs_wpcs", "phpcs is available but WordPress standards are not installed", required, [phpcs, "-i"])
    command = [
        phpcs,
        "--standard=WordPress",
        "--extensions=php",
        f"--ignore={','.join(PHPCS_IGNORE_PATTERNS)}",
        str(path),
    ]
    return command_check("phpcs_wpcs", command, ROOT, args.timeout_sec, required)


def check_plugin_check(path: Path, args: argparse.Namespace, required: bool) -> Check:
    wp = shutil.which("wp")
    wp_env_root = Path(args.wp_env_root).resolve() if args.wp_env_root else None
    if wp:
        command = [wp, "plugin", "check", str(path)]
        cwd = Path(args.wp_root).resolve() if args.wp_root else (path if path.is_dir() else path.parent)
    elif wp_env_root:
        npx = shutil.which("npx")
        if not npx:
            return block_check("plugin_check", "wp executable not found and npx executable not found for wp-env fallback", required)
        plugin_arg = path.name if path.is_dir() else str(path)
        command = [npx, "--yes", "@wordpress/env", "run", "cli", "--", "wp", "plugin", "check", plugin_arg]
        cwd = wp_env_root
    else:
        return block_check("plugin_check", "wp executable not found", required)
    if args.plugin_check_require:
        command.append(f"--require={args.plugin_check_require}")
    elif wp_env_root:
        command.append("--require=./wp-content/plugins/plugin-check/cli.php")

    try:
        result = run_command(command, cwd, args.timeout_sec)
    except FileNotFoundError:
        return block_check("plugin_check", f"command not found: {command[0]}", required, command)
    except subprocess.TimeoutExpired:
        return fail_check("plugin_check", f"command timed out after {args.timeout_sec}s", required)

    detail = f"exit {result.returncode}"
    if result.stdout.strip():
        detail += f"; stdout: {result.stdout.strip()[:500]}"
    if result.stderr.strip():
        detail += f"; stderr: {result.stderr.strip()[:500]}"
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        return Check("plugin_check", "fail", required, detail, command)
    if re.search(r"(?m)(^|\t)ERROR(\t|$)", output):
        return Check("plugin_check", "fail", required, detail, command)
    return Check("plugin_check", "pass", required, detail, command)


def check_api_existence(path: Path, timeout_sec: int = 120) -> tuple[Check, dict[str, Any] | None]:
    """API-existence and version-range lint (PHPStan + wordpress-stubs + wp-compat).

    Required structural gate for PHP-bearing artifacts: missing tooling reports
    `blocked` (honest evidence, fail-closed), never a silent pass.
    """
    if not iter_files(path, PHP_SUFFIXES):
        return skip_check("api_existence", "no PHP files found"), None
    report = wp_api_lint.run_api_lint(path, timeout_sec=timeout_sec)
    detail = wp_api_lint.summarize_report(report)
    if report["status"] == "blocked":
        return block_check("api_existence", detail), report
    if report["status"] == "pass":
        return pass_check("api_existence", detail), report
    return fail_check("api_existence", detail), report


def check_security_gate(path: Path, timeout_sec: int = 120) -> tuple[Check, dict[str, Any] | None]:
    """Static security gate (WPCS security sniffs + suppression differential).

    Required structural gate for PHP-bearing artifacts: missing tooling reports
    `blocked` (fail-closed), never a silent pass. Hard-fails on
    `WordPress.DB.Prepared*`/`EscapeOutput` errors and on security-relevant
    suppressions that reappear without annotations; other sniff hits ride along
    as advisory evidence in the report for the security critic.
    """
    if not iter_files(path, PHP_SUFFIXES):
        return skip_check("security_gate", "no PHP files found"), None
    report = wp_security_gate.run_security_gate(path, timeout_sec=timeout_sec)
    detail = wp_security_gate.summarize_report(report)
    if report["status"] == "blocked":
        return block_check("security_gate", detail), report
    if report["status"] == "skip":
        return skip_check("security_gate", detail), report
    if report["status"] == "pass":
        return pass_check("security_gate", detail), report
    return fail_check("security_gate", detail), report


def check_wp_env(path: Path, args: argparse.Namespace, required: bool) -> Check:
    npx = shutil.which("npx")
    if not npx:
        return block_check("wp_env_smoke", "npx executable not found", required)
    cwd = Path(args.wp_env_root).resolve() if args.wp_env_root else (path if path.is_dir() else path.parent)
    command = [npx, "--yes", "@wordpress/env", "run", "cli", "--", "wp", "core", "version"]
    return command_check("wp_env_smoke", command, cwd, args.timeout_sec, required)


def structural_checks(
    artifact_type: str,
    path: Path | artifact_snapshot_scan.ArtifactSnapshotView,
    timeout_sec: int = 120,
    extras: dict[str, Any] | None = None,
) -> list[Check]:
    if isinstance(path, artifact_snapshot_scan.ArtifactSnapshotView):
        return [Check(item.id, item.status, True, item.detail) for item in artifact_snapshot_scan.structural_checks(artifact_type, path)]
    checks = [check_path(path), check_no_unsafe_text(path), check_no_hardcoded_secrets(path)]
    if artifact_type == "plugin":
        checks += [
            check_plugin_header(path),
            check_php_wpcs_shape_heuristics(path),
            check_plugin_security_heuristics(path),
            check_plugin_ai_surface_heuristics(path),
        ]
    elif artifact_type == "block":
        checks += [check_block_metadata(path), check_block_registration(path)]
    elif artifact_type == "theme":
        checks.append(check_theme_metadata(path))
    elif artifact_type == "blueprint":
        checks.append(check_blueprint_json(path))
    if artifact_type in {"plugin", "block", "theme"} and path.exists():
        api_check, api_report = check_api_existence(path, timeout_sec)
        checks.append(api_check)
        if extras is not None and api_report is not None:
            extras["api_lint"] = api_report
        security_check, security_report = check_security_gate(path, timeout_sec)
        checks.append(security_check)
        if extras is not None and security_report is not None:
            extras["security_gate"] = security_report
    return checks


def trusted_external_checks(artifact_type: str, path: Path, timeout_sec: int, extras: dict[str, Any]) -> list[Check]:
    checks = []
    if artifact_type not in {"plugin", "block", "theme"} or not iter_files(path, PHP_SUFFIXES):
        return checks
    api_check, api_report = check_api_existence(path, timeout_sec)
    checks.append(api_check)
    if api_report is not None:
        extras["api_lint"] = api_report
    security_check, security_report = check_security_gate(path, timeout_sec)
    checks.append(security_check)
    if security_report is not None:
        extras["security_gate"] = security_report
    return checks


def _sandbox_check(staged: artifact_staging.StagedTree, phase: str, timeout_sec: int, receipts=None) -> Check:
    if phase == "npm-build":
        build = runtime_artifact_pipeline.build_block(staged, timeout_sec)
        status, detail, command, output = build.status, build.detail, build.command, build.output
        staging_receipts = build.staging_cleanup_receipts
    else:
        outcome = artifact_execution.run_generated(staged, phase, timeout_sec)
        status, detail, command, output = outcome.status, outcome.detail, outcome.command, outcome.output
        staging_receipts = outcome.staging_cleanup_receipts
    check_id = "npm_build" if phase == "npm-build" else "phpunit"
    rendered = list(command)
    translated = [
        runtime_artifact_pipeline.cleanup_receipt_from_staging("sandbox_output",receipt)
        for receipt in staging_receipts
    ]
    if receipts is not None:
        receipts.extend(translated)
    if any(receipt.state != "removed" or receipt.error for receipt in translated):
        return block_check(check_id, "sandbox output remains retained after import cleanup", True, rendered)
    if output is not None:
        receipt = runtime_artifact_pipeline.cleanup_component("sandbox_output", output)
        if receipts is not None:
            receipts.append(receipt)
        if receipt.state != "removed":
            return block_check(check_id, "sandbox output remains retained after cleanup", True, rendered)
    return Check(check_id, status, True, detail, rendered)


def runtime_checks(artifact_type: str, path: Path, args: argparse.Namespace, staged: artifact_staging.StagedTree | None = None, receipts=None, trusted_handoff: bool = False) -> list[Check]:
    required_tools = set(args.require_tool or [])
    if args.profile == "runtime":
        if artifact_type in {"plugin", "theme"}:
            required_tools.update({"php-lint", "phpcs"})
        if artifact_type == "plugin":
            required_tools.add("plugin-check")
        if artifact_type == "block":
            required_tools.add("npm-build")
    checks: list[Check] = []
    if "php-lint" in required_tools:
        checks.append(check_php_lint(path, args.timeout_sec, True))
    if "phpcs" in required_tools or "wpcs" in required_tools:
        checks.append(check_phpcs(path, args, True))
    if "phpunit" in required_tools:
        checks.append(_sandbox_check(staged,"phpunit",args.timeout_sec,receipts) if staged else block_check("phpunit","staged capability unavailable"))
    if "npm-build" in required_tools:
        checks.append(_sandbox_check(staged,"npm-build",args.timeout_sec,receipts) if staged else block_check("npm_build","staged capability unavailable"))
    if "plugin-check" in required_tools:
        checks.append(block_check("plugin_check", "generated runtime execution is forbidden in the trusted scanner handoff") if trusted_handoff else check_plugin_check(path, args, True))
    if "wp-env" in required_tools:
        checks.append(block_check("wp_env_smoke", "wp-env root is required outside the trusted scanner handoff") if trusted_handoff and not args.wp_env_root else check_wp_env(path, args, True))
    return checks


def summarize(checks: list[Check]) -> str:
    required = [check for check in checks if check.required]
    if any(check.status == "blocked" for check in required):
        return "blocked"
    if any(check.status == "fail" for check in required):
        return "fail"
    return "pass"


def _validate_snapshot(artifact_type, view, external_path, args, staged):
    extras = {}; receipts = []
    checks = structural_checks(artifact_type, view, timeout_sec=getattr(args, "timeout_sec", 120), extras=extras)
    checks.extend(trusted_external_checks(artifact_type, external_path, args.timeout_sec, extras))
    checks.extend(runtime_checks(artifact_type, external_path, args, staged, receipts, trusted_handoff=True))
    status = summarize(checks)
    result = {
        "artifact_type": artifact_type, "artifact_path": repo_relative(external_path),
        "profile": args.profile, "required_tools": sorted(args.require_tool or []),
        "runtime_roots": {"wp_root": args.wp_root, "wp_env_root": args.wp_env_root},
        "status": status, "pass": status == "pass", "checks": [asdict(check) for check in checks],
        "_artifact_retention_receipts": receipts,
        "trusted_scanner_handoff": {
            "status": "used", "generated_execution": False,
            "threat_boundary": "path-required external scanners are trusted; intentional same-UID scanner/co-tenant substitution is out of scope",
        },
    }
    if "api_lint" in extras: result["api_lint"] = extras["api_lint"]
    if "security_gate" in extras: result["security_gate"] = extras["security_gate"]
    return result


def _staged_validation_subpath(held: artifact_staging.HeldStagedTree, subpath: Path | None) -> Path:
    relative = subpath or Path()
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("staged validation subpath is unsafe")
    if relative.parts and dict(held.proof.path_kinds).get(relative.as_posix()) != "directory":
        raise ValueError("staged validation subpath is unavailable")
    return relative


def _scan_failure_result(artifact_type, args, exc):
    check = block_check("trusted_scanner_handoff", f"trusted scanner handoff raised {type(exc).__name__}")
    return {
        "artifact_type": artifact_type, "artifact_path": None, "profile": args.profile,
        "required_tools": sorted(args.require_tool or []),
        "runtime_roots": {"wp_root": args.wp_root, "wp_env_root": args.wp_env_root},
        "status": "blocked", "pass": False, "checks": [asdict(check)],
        "_artifact_retention_receipts": [],
        "trusted_scanner_handoff": {
            "status": "blocked", "generated_execution": False,
            "threat_boundary": "path-required external scanners are trusted; intentional same-UID scanner/co-tenant substitution is out of scope",
        },
    }


def _run_staged_scan(artifact_type, staged, args, subpath):
    manifest = staged.manifest; scan_stage = None
    receipt = runtime_artifact_pipeline.CleanupReceipt("scan_handoff", "not_created", False, False, None, None)
    try:
        with artifact_staging.hold_staged_tree(staged) as held:
            manifest = held.proof.manifest
            relative = _staged_validation_subpath(held, subpath)
            snapshot = artifact_staging.snapshot_held_tree(held)
            view = artifact_snapshot_scan.from_snapshot(snapshot, relative)
            scan_stage = artifact_staging._stage_scan_handoff_snapshot(snapshot)
            try:
                with artifact_staging.hold_staged_tree(scan_stage):
                    result = _validate_snapshot(artifact_type, view, scan_stage.root / relative, args, staged)
            finally:
                receipt = runtime_artifact_pipeline.cleanup_component("scan_handoff", scan_stage)
    except Exception as exc:
        result = _scan_failure_result(artifact_type, args, exc)
    return result, manifest, receipt


def validate_staged_artifact(artifact_type: str, staged: artifact_staging.StagedTree, args: argparse.Namespace, *, source_path: Path | None = None, subpath: Path | None = None, _defer_retention: bool = False) -> dict[str, Any]:
    claimed = source_path.expanduser().absolute() if source_path is not None else None
    attested = Path(staged.source_path) if staged.source_attested and staged.source_path else None
    result, manifest, scan_receipt = _run_staged_scan(artifact_type, staged, args, subpath)
    source = attested or staged.root
    result["scan_handoff"] = {
        "state": scan_receipt.state, "retained": scan_receipt.exists or scan_receipt.live,
        "resource_path": scan_receipt.resource_path,
        "recovery_path": scan_receipt.recovery_path, "error": scan_receipt.error,
        "generated_execution": False,
    }
    if scan_receipt.state != "removed":
        result["status"] = "blocked"; result["pass"] = False
        result["checks"].append(asdict(block_check("scan_handoff_cleanup", "trusted scanner handoff remains retained")))
    requested = set(args.require_tool or []) & {"npm-build", "phpunit"}
    generated_requested = bool(requested) or (args.profile == "runtime" and artifact_type == "block")
    phase_ids = {"npm_build", "phpunit"}
    phase_checks = [Check(**check) for check in result["checks"] if check["id"] in phase_ids]
    generated_status = summarize(phase_checks) if phase_checks else "blocked" if generated_requested else "not_requested"
    result.update(
        {
            "artifact_path": repo_relative(source),
            "source_path": str(attested) if attested is not None else None,
            "source_attested": attested is not None,
            "claimed_source_path": str(claimed) if claimed is not None else None,
            "execution_copy": str(staged.root),
            "execution_retained": True,
            "manifest_sha256": artifact_staging.manifest_sha256(manifest),
            "sandbox_posture": {
                "generated_execution": generated_status,
                "host_fallback": False,
                "static_scan_root": "fd_snapshot_and_trusted_scan_handoff",
            },
        }
    )
    receipts = result.pop("_artifact_retention_receipts", [])
    if _defer_retention:
        result["_artifact_retention_receipts"] = receipts
    else:
        receipts.append(runtime_artifact_pipeline.observe_component("input_copy", staged))
        result["artifact_retention"] = runtime_artifact_pipeline.retention_summary(receipts)
    return result


def _staging_failure(artifact_type: str, source: Path, args: argparse.Namespace, detail: str, receipts=()) -> dict[str, Any]:
    return runtime_artifact_pipeline.staging_failure_result(
        artifact_type=artifact_type,artifact_path=repo_relative(source),source_path=str(source),
        profile=args.profile,required_tools=sorted(args.require_tool or []),
        runtime_roots={"wp_root":args.wp_root,"wp_env_root":args.wp_env_root},
        detail=detail,receipts=receipts,
    )


def validate_artifact(artifact_type: str, path: Path, args: argparse.Namespace) -> dict[str, Any]:
    source = path.expanduser().resolve()
    retain = bool(getattr(args, "debug_retain", False))
    try:
        staged = artifact_staging.stage_tree(source)
    except artifact_staging.StagingCleanupError as exc:
        detail = f"staging failed: {type(exc.primary).__name__}: {exc.primary}"
        receipt=runtime_artifact_pipeline.cleanup_receipt_from_staging("input_copy",exc.receipt)
        return _staging_failure(artifact_type,source,args,detail,[receipt])
    except (OSError, ValueError, RuntimeError) as exc:
        detail = f"staging failed: {type(exc).__name__}: {exc}"
        return _staging_failure(artifact_type, source, args, detail)
    result = None
    cleanup_error = None
    try:
        result = validate_staged_artifact(artifact_type, staged, args, source_path=source, _defer_retention=True)
    finally:
        receipt = (
            runtime_artifact_pipeline.observe_component("input_copy", staged)
            if retain
            else runtime_artifact_pipeline.cleanup_component("input_copy", staged)
        )
    receipts = result.pop("_artifact_retention_receipts", [])
    receipts.append(receipt)
    result["artifact_retention"] = runtime_artifact_pipeline.retention_summary(receipts)
    cleanup_error = receipt.error if receipt.state != "removed" and not retain else None
    if cleanup_error:
        result["status"] = "blocked"
        result["pass"] = False
        result["checks"].append(asdict(block_check("artifact_cleanup", cleanup_error)))
    result["execution_retained"] = result["artifact_retention"]["retained"]
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate generated WordPress artifacts with deterministic checks.")
    parser.add_argument("--artifact-type", choices=("plugin", "block", "theme", "blueprint"), required=True)
    parser.add_argument("--path", required=True, help="Generated artifact directory or Blueprint JSON file.")
    parser.add_argument("--profile", choices=("static", "runtime"), default="static")
    parser.add_argument(
        "--require-tool",
        action="append",
        choices=("php-lint", "phpcs", "wpcs", "phpunit", "npm-build", "plugin-check", "wp-env"),
        help="External tool gate to require in addition to structural checks. May be repeated.",
    )
    parser.add_argument("--wp-root", help="WordPress root to use as cwd for WP-CLI checks.")
    parser.add_argument("--wp-env-root", help="Directory containing the .wp-env.json/package.json to use as cwd for wp-env checks.")
    parser.add_argument("--plugin-check-require", help="Optional Plugin Check cli.php path for runtime checks.")
    parser.add_argument("--timeout-sec", type=int, default=120)
    parser.add_argument("--debug-retain", action="store_true", help="Retain the staged execution copy for explicit debugging.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_artifact(args.artifact_type, Path(args.path), args)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] == "pass":
        return 0
    if result["status"] == "blocked":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
