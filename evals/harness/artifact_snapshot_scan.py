"""Immutable byte-view checks for descriptor-captured WordPress artifacts."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


TEXT_SUFFIXES = {".php", ".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".scss", ".md", ".txt", ".html"}
IGNORED = {".git", "node_modules", "vendor", ".wp-env", "coverage", "dist", "build"}
BANNED = (r"\brm\s+-rf\b", r"\bchmod\s+777\b", r"\bdrop\s+table\b", r"\bdelete\s+from\b", r"\bwp\s+db\s+reset\b", r"\bwp\s+site\s+empty\b")
SECRETISH = re.compile(r"(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*['\"][^'\"]{12,}")


@dataclass(frozen=True)
class SnapshotEntry:
    path: PurePosixPath
    content: bytes

    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class ArtifactSnapshotView:
    entries: tuple[SnapshotEntry, ...]

    def files(self, suffixes: set[str], ignored: set[str] = IGNORED) -> tuple[SnapshotEntry, ...]:
        return tuple(entry for entry in self.entries if entry.path.suffix.lower() in suffixes and not any(part in ignored for part in entry.path.parts))

    def aggregate(self, suffixes: set[str] = TEXT_SUFFIXES) -> str:
        return "\n".join(entry.text() for entry in self.files(suffixes))


@dataclass(frozen=True)
class SnapshotCheck:
    id: str
    status: str
    detail: str


def from_snapshot(snapshot, subpath: Path | None = None) -> ArtifactSnapshotView:
    prefix = tuple((subpath or Path()).parts)
    entries = []
    for path, content, _info in snapshot:
        if prefix and tuple(path.parts[: len(prefix)]) != prefix:
            continue
        relative = PurePosixPath(*path.parts[len(prefix) :])
        if relative.parts:
            entries.append(SnapshotEntry(relative, content))
    return ArtifactSnapshotView(tuple(entries))


def _check(check_id: str, passed: bool, detail: str) -> SnapshotCheck:
    return SnapshotCheck(check_id, "pass" if passed else "fail", detail)


def _general(view: ArtifactSnapshotView) -> list[SnapshotCheck]:
    text = view.aggregate()
    unsafe = [pattern for pattern in BANNED if re.search(pattern, text.lower())]
    secret_files = [entry.path.as_posix() for entry in view.files(TEXT_SUFFIXES) if SECRETISH.search(entry.text())]
    return [
        _check("artifact_path", True, f"authenticated snapshot contains {len(view.entries)} file(s)"),
        _check("unsafe_commands", not unsafe, "no banned destructive command patterns found" if not unsafe else f"unsafe destructive patterns found: {', '.join(unsafe)}"),
        _check("hardcoded_secrets", not secret_files, "no long secret-like assignments found" if not secret_files else f"secret-like assignments found in: {', '.join(secret_files)}"),
    ]


def _short_array(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped and not stripped.startswith(("*", "//", "#")) and (stripped == "[" or stripped.startswith(("[ ", "['", '["')) or "=> [" in stripped or "= [" in stripped or stripped.startswith("return [")))


def _plugin_shape(view: ArtifactSnapshotView) -> list[SnapshotCheck]:
    php = view.files({".php"})
    headers = [entry for entry in php if "Plugin Name:" in entry.text()[:8192]]
    issues = []
    for entry in php:
        text = entry.text()
        if "Plugin Name:" in text[:8192] and "@package" not in text[:8192]:
            issues.append(f"{entry.path} missing file-level @package tag")
        lines = [str(index) for index, line in enumerate(text.splitlines(), 1) if _short_array(line)]
        if lines:
            issues.append(f"short array syntax found at {entry.path}:{','.join(lines[:8])}")
    return [
        _check("plugin_header", bool(headers), f"plugin header found in {headers[0].path}" if headers else "no PHP file contains a WordPress plugin header with Plugin Name"),
        _check("php_wpcs_shape_heuristics", not issues, "PHP files satisfy cheap WPCS shape checks" if not issues else "; ".join(issues)),
    ]


def _plugin_security(view: ArtifactSnapshotView) -> SnapshotCheck:
    text = view.aggregate().lower(); issues = []
    if "register_rest_route" in text and "permission_callback" not in text: issues.append("register_rest_route without permission_callback")
    handler = "wp_ajax_" in text or "admin_post_" in text
    if handler and "current_user_can" not in text: issues.append("AJAX/admin-post handler without current_user_can")
    if handler and not any(term in text for term in ("check_ajax_referer", "check_admin_referer", "wp_verify_nonce")): issues.append("AJAX/admin-post handler without nonce verification")
    if "$wpdb->" in text and any(term in text for term in ("$_get", "$_post", "$_request")) and "$wpdb->prepare" not in text: issues.append("$wpdb query touches request input without $wpdb->prepare")
    return _check("plugin_security_heuristics", not issues, "admin, REST, AJAX, and SQL heuristics passed" if not issues else "; ".join(issues))


def _declares_minimum(text: str, minimum: tuple[int, ...]) -> bool:
    match = re.search(r"(?im)^\s*\*?\s*Requires at least:\s*([0-9.]+)\s*$", text)
    if not match: return False
    declared = tuple(int(part) for part in match.group(1).split("."))
    width = max(len(declared), len(minimum))
    return declared + (0,) * (width - len(declared)) >= minimum + (0,) * (width - len(minimum))


def _guarded(text: str, function: str) -> bool:
    return bool(re.search(rf"function_exists\s*\(\s*['\"]{re.escape(function)}['\"]\s*\)", text, re.I))


def _plugin_ai(view: ArtifactSnapshotView) -> SnapshotCheck:
    text = view.aggregate(); lower = text.lower(); php = "\n".join(entry.text() for entry in view.files({".php"})).lower(); issues = []
    if "wp_register_ability" in lower:
        if "wp_abilities_api_init" not in lower: issues.append("wp_register_ability() without wp_abilities_api_init registration hook")
        missing = [key for key in ("label", "description", "category", "input_schema", "output_schema", "execute_callback", "permission_callback") if key not in lower]
        if missing: issues.append(f"wp_register_ability() missing args: {', '.join(missing)}")
        if not _declares_minimum(text, (6, 9)) and not _guarded(text, "wp_register_ability"): issues.append("Abilities API used without Requires at least: 6.9 or function_exists guard")
    if "wp_ai_client_prompt" in lower:
        if not _declares_minimum(text, (7, 0)) and not _guarded(text, "wp_ai_client_prompt"): issues.append("wp_ai_client_prompt() used without Requires at least: 7.0 or function_exists guard")
        if "is_wp_error" not in lower: issues.append("wp_ai_client_prompt() result lacks is_wp_error() handling")
        if not any(term in lower for term in ("current_user_can", "permission_callback", "wp_ai_client_prevent_prompt")): issues.append("AI Client call lacks capability or prompt-prevention boundary")
    if any(term in php for term in ("wordpress/mcp-adapter", "mcp_adapter_init", "mcpadapter::instance")):
        if "mcp_adapter_init" not in php and "mcpadapter::instance" not in php: issues.append("MCP Adapter referenced without initialization")
        if "wp_register_ability" not in php and "core/" not in php: issues.append("MCP Adapter referenced without named abilities to expose")
    return _check("plugin_ai_surface_heuristics", not issues, "Abilities, MCP Adapter, and AI Client heuristics passed" if not issues else "; ".join(issues))


def _block(view: ArtifactSnapshotView) -> list[SnapshotCheck]:
    blocks = [entry for entry in view.files({".json"}) if entry.path.name == "block.json"]; errors = []
    for entry in blocks:
        try: data = json.loads(entry.text())
        except json.JSONDecodeError as exc: errors.append(f"{entry.path} is invalid JSON: {exc}"); continue
        if not isinstance(data, dict): errors.append(f"{entry.path} must contain a JSON object"); continue
        missing = [key for key in ("name", "title", "category") if not data.get(key)]
        if missing: errors.append(f"{entry.path} missing keys: {', '.join(missing)}")
    metadata = _check("block_metadata", bool(blocks) and not errors, f"{len(blocks)} block.json file(s) parsed with required keys" if blocks and not errors else "; ".join(errors) or "no block.json file found")
    scripts = False
    package = next((entry for entry in view.entries if entry.path == PurePosixPath("package.json")), None)
    if package is not None:
        try: scripts = bool(json.loads(package.text()).get("scripts"))
        except (json.JSONDecodeError, AttributeError): pass
    registered = "register_block_type" in view.aggregate() or scripts
    return [metadata, _check("block_registration", registered, "server registration or build scripts present" if registered else "no register_block_type call or package scripts found")]


def _theme(view: ArtifactSnapshotView) -> SnapshotCheck:
    style = next((entry for entry in view.entries if entry.path == PurePosixPath("style.css")), None)
    theme = next((entry for entry in view.entries if entry.path == PurePosixPath("theme.json")), None)
    valid_json = False
    if theme:
        try: valid_json = isinstance(json.loads(theme.text()), dict)
        except json.JSONDecodeError: return _check("theme_metadata", False, "theme.json is invalid JSON")
    passed = bool(style and "Theme Name:" in style.text()[:8192]) or valid_json
    return _check("theme_metadata", passed, "style.css theme header or valid theme.json present" if passed else "missing style.css Theme Name header and theme.json")


def _blueprint(view: ArtifactSnapshotView) -> SnapshotCheck:
    files = sorted(view.files({".json"}), key=lambda entry: (entry.path.name not in {"blueprint.json", "playground-blueprint.json"}, entry.path.as_posix()))
    if not files: return _check("blueprint_json", False, "no Blueprint JSON file found")
    try: data = json.loads(files[0].text())
    except json.JSONDecodeError as exc: return _check("blueprint_json", False, f"{files[0].path} is invalid JSON: {exc}")
    steps = data.get("steps") if isinstance(data, dict) else None
    return _check("blueprint_json", isinstance(steps, list) and bool(steps), f"{files[0].path} contains {len(steps)} step(s)" if isinstance(steps, list) and steps else f"{files[0].path} must contain a non-empty steps array")


def structural_checks(artifact_type: str, view: ArtifactSnapshotView) -> list[SnapshotCheck]:
    checks = _general(view)
    if artifact_type == "plugin": checks += _plugin_shape(view) + [_plugin_security(view), _plugin_ai(view)]
    elif artifact_type == "block": checks += _block(view)
    elif artifact_type == "theme": checks.append(_theme(view))
    elif artifact_type == "blueprint": checks.append(_blueprint(view))
    return checks
