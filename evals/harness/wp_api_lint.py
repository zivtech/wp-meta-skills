#!/usr/bin/env python3
"""WordPress API-existence, deprecation, and hook lint (phases 1+2).

Three engines produce deterministic findings in one report:

1. **PHPStan engine** (phase 1): PHPStan level 0 with
   php-stubs/wordpress-stubs and johnbillion/wp-compat —
   `unknown_function` / `unknown_class` / `unknown_method` with `difflib`
   did-you-mean suggestions, and `version_range` for core symbols and hooks
   newer than the declared `Requires at least:` header (guard-aware via real
   scope analysis). The pinned toolchain lives in `evals/harness/php-tools`
   (composer.json + composer.lock committed; `vendor/` fetched, never
   committed).
2. **Native symbol engine** (phase 2): reads the committed MIT-only snapshot
   `evals/harness/data/wp-symbols.json` (built by
   `scripts/build-wp-symbol-db.py`). Always contributes `deprecated_api`
   findings naming the exact successor (e.g. `wp_login()` → `wp_signon()`).
   When the PHPStan toolchain is absent it also takes over
   `unknown_function` / `unknown_class` / `version_range` (regex-tier: no
   method checks, aggregate-text `function_exists()` guards), so the gate
   degrades to reduced coverage with explicit negative space instead of
   going fully `blocked`.
3. **Hooks engine** (phase 2): `unknown_hook` findings for hallucinated hook
   names in add_action/add_filter/etc., with did-you-mean suggestions.
   Hook data is read at analysis time from the Composer vendor tree
   (`vendor/wp-hooks/wordpress-core/hooks/*.json`, GPL-3.0, never committed
   or redistributed — see `docs/wordpress/reuse-ledger.md`), so this engine
   is available exactly when the PHPStan toolchain is installed. Dynamic
   hook names (concatenation/interpolation) and names matching only
   generic dynamic core patterns (e.g. `wp_{$field}`) are advisory;
   specific dynamic patterns (e.g. `save_post_{$post->post_type}`) allow;
   artifact-defined hooks (its own do_action/apply_filters literals), the
   artifact slug prefix, and `--allow-prefix` namespaces allow.

`blocked` is reported only when neither the toolchain nor the committed
snapshot is available — blocked is honest evidence, never a pass.

Standing negative space (checked by tests, stated in every report):

- String callback existence is not validated.
- PHP constant existence is not checked (avoids false positives on
  runtime-defined constants such as ABSPATH).
- Test directories (tests/, test/) are excluded: they reference the
  PHPUnit/wp-phpunit symbol ecosystem, which is outside the core stubs; the
  phpunit runtime gate owns test code.
- Hook arg-count validation, deprecated-hook data, WooCommerce symbols, and
  JS package checks are later phases; REST routes, option names, and
  capabilities are site-defined and out of scope.
"""

from __future__ import annotations

import argparse
import bisect
import difflib
import json
import os
import re
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

SCHEMA = "wp-meta-skills/api-lint"
SCHEMA_VERSION = 1

PHP_SUFFIXES = {".php"}
IGNORED_DIRS = {".git", "node_modules", "vendor", ".wp-env", "coverage", "dist", "build"}
HEADER_BYTES = 8 * 1024
TOOL_STDOUT_LIMIT = 32 * 1024 * 1024
TOOL_STDERR_LIMIT = 2 * 1024 * 1024
MAX_CALL_SITES_PER_FILE = 50_000
MAX_CALL_SITES_TOTAL = 100_000
MAX_FINDINGS_PER_FILE = 5_000
MAX_FINDINGS_TOTAL = 10_000
MAX_TOOL_MESSAGES_PER_FILE = 5_000
MAX_TOOL_MESSAGES_TOTAL = 10_000
ANALYSIS_CHECK_INTERVAL = 256

# Header regexes mirror wp-compat's getRequiresAtLeastHeader(), which mirrors
# WordPress core's get_plugin_data() logic.
REQUIRES_AT_LEAST_RE = re.compile(r"^[ \t/*#@]*Requires at least:(.*)$", re.IGNORECASE | re.MULTILINE)
REQUIRES_PLUGINS_RE = re.compile(r"^[ \t/*#@]*Requires Plugins:(.*)$", re.IGNORECASE | re.MULTILINE)

# Only mapped identifiers become findings; everything else stays advisory
# evidence so the gate fails only on what it actually enforces.
FINDING_CLASSES = {
    "function.notFound": ("unknown_function", "function"),
    "class.notFound": ("unknown_class", "class"),
    "method.notFound": ("unknown_method", "method"),
    "staticMethod.notFound": ("unknown_method", "method"),
    "WPCompat.functionNotAvailable": ("version_range", "function"),
    "WPCompat.methodNotAvailable": ("version_range", "method"),
}
WPCOMPAT_HOOK_IDENTIFIER_PREFIXES = ("WPCompat.filterNotAvailable.", "WPCompat.actionNotAvailable.")
ANALYSIS_ERROR_IDENTIFIERS = {"phpstan.parse", "WPCompat.error"}

UNKNOWN_FUNCTION_RE = re.compile(r"Function ([\w\\]+) not found\.")
UNKNOWN_CLASS_RE = re.compile(r"[Cc]lass ([\w\\]+) not found\.")
UNKNOWN_CLASS_REFERENCED_RE = re.compile(r"unknown class ([\w\\]+)\.")
UNKNOWN_METHOD_RE = re.compile(r"method ([\w\\]+::\w+)\(\)")
WPCOMPAT_SYMBOL_RE = re.compile(r"^([\w\\]+(?:::\w+)?)\(\) is only available since WordPress version ([\d.]+)\.$")
WPCOMPAT_HOOK_RE = re.compile(r"^(Filter|Action) (\S+) is only available since WordPress version ([\d.]+)\.$")

# `Requires Plugins:` slugs extend the third-party prefix allowlist: unknown
# symbols behind a declared plugin dependency degrade to advisory instead of
# torching a legitimate integration (the P3 symbol sets make them exact).
KNOWN_PLUGIN_PREFIXES = {
    "woocommerce": ("wc_", "woocommerce_", "WC_", "WooCommerce"),
}

NEGATIVE_SPACE = [
    "String callback existence is not validated.",
    "PHP constant existence is not checked.",
    "PHP files under tests/ and test/ are excluded: they reference the PHPUnit/wp-phpunit symbol ecosystem, which is outside the core stubs; the phpunit runtime gate owns test code.",
    "Hook arg-count validation, deprecated-hook data, WooCommerce symbols, and JS package existence are later phases.",
    "REST routes, option names, and capabilities are site-defined and out of scope.",
]

DEFAULT_SNAPSHOT_PATH = HARNESS_ROOT / "data" / "wp-symbols.json"

HOOK_CONSUMERS = (
    "add_action",
    "add_filter",
    "remove_action",
    "remove_filter",
    "has_action",
    "has_filter",
    "did_action",
    "doing_action",
    "doing_filter",
)
HOOK_DEFINERS = (
    "do_action",
    "do_action_ref_array",
    "apply_filters",
    "apply_filters_ref_array",
    "do_action_deprecated",
    "apply_filters_deprecated",
)
HOOK_CALL_OPEN_RE = re.compile(r"\b(" + "|".join(HOOK_CONSUMERS + HOOK_DEFINERS) + r")\s*\(")

PHP_KEYWORDS = {
    "if", "elseif", "else", "while", "for", "foreach", "switch", "catch", "match",
    "fn", "function", "isset", "unset", "empty", "list", "array", "echo", "print",
    "exit", "die", "include", "include_once", "require", "require_once", "return",
    "new", "clone", "yield", "static", "declare", "use", "namespace", "throw",
    "global", "and", "or", "xor", "instanceof", "parent", "self", "true", "false",
    "null", "callable", "int", "float", "string", "bool", "void", "iterable",
    "object", "mixed", "never", "readonly", "enum", "trait", "interface", "class",
    "const", "endif", "endwhile", "endfor", "endforeach", "endswitch",
}

CALL_RE = re.compile(r"([A-Za-z_]\w*)\s*\(")
DEF_FUNCTION_RE = re.compile(r"\bfunction\s+&?\s*([A-Za-z_]\w*)\s*\(")
DEF_CLASS_RE = re.compile(r"\b(?:class|interface|trait|enum)\s+([A-Za-z_]\w*)")
NEW_CLASS_RE = re.compile(r"\bnew\s+(\\?[A-Za-z_][\w\\]*)\s*[(;]")
FUNCTION_EXISTS_RE = re.compile(r"function_exists\s*\(\s*['\"]([A-Za-z_]\w*)['\"]\s*\)", re.IGNORECASE)

PIN_PACKAGES = ("phpstan/phpstan", "php-stubs/wordpress-stubs", "johnbillion/wp-compat", "wp-hooks/wordpress-core")


@dataclass(frozen=True)
class Toolchain:
    php: str
    phpstan: Path
    stubs: Path
    wp_compat_neon: Path
    symbols_json: Path
    root: Path


@dataclass(frozen=True)
class SymbolIndex:
    functions: tuple[str, ...]
    classes: tuple[str, ...]

    @classmethod
    def from_symbols_json(cls, symbols_json: Path) -> "SymbolIndex":
        data = json.loads(symbols_json.read_text(encoding="utf-8"))
        symbols = data.get("symbols", {})
        functions = tuple(sorted(name for name in symbols if "::" not in name))
        classes = tuple(sorted({name.split("::", 1)[0] for name in symbols if "::" in name}))
        return cls(functions, classes)

    def suggest(self, symbol: str, kind: str) -> list[str]:
        pool: tuple[str, ...]
        if kind == "function":
            pool = self.functions
        elif kind == "class":
            pool = self.classes
        else:
            return []
        return difflib.get_close_matches(symbol, pool, n=3, cutoff=0.6)


class AnalysisBlocked(RuntimeError):
    """Native analysis exceeded a deadline or reviewed work ceiling."""


@dataclass
class AnalysisBudget:
    deadline_monotonic: float | None
    call_sites: int = 0
    findings: int = 0
    tool_messages: int = 0

    def __post_init__(self) -> None:
        self.call_sites_by_file: dict[str, int] = {}
        self.findings_by_file: dict[str, int] = {}
        self.tool_messages_by_file: dict[str, int] = {}

    def check_deadline(self) -> None:
        if self.deadline_monotonic is None:
            return
        if time.monotonic() >= self.deadline_monotonic:
            raise AnalysisBlocked("native API/hook analysis deadline elapsed")

    def visit_call(self, engine: str, file_name: str) -> None:
        self.call_sites += 1
        file_count = self.call_sites_by_file.get(file_name, 0) + 1
        self.call_sites_by_file[file_name] = file_count
        if file_count > MAX_CALL_SITES_PER_FILE:
            raise AnalysisBlocked(f"{engine} call-site limit exceeded for {file_name}")
        if self.call_sites > MAX_CALL_SITES_TOTAL:
            raise AnalysisBlocked(f"{engine} global call-site limit exceeded")
        if self.call_sites % ANALYSIS_CHECK_INTERVAL == 0:
            self.check_deadline()

    def add_finding(self, engine: str, file_name: str, finding: dict[str, Any]) -> dict[str, Any]:
        self.findings += 1
        file_count = self.findings_by_file.get(file_name, 0) + 1
        self.findings_by_file[file_name] = file_count
        if file_count > MAX_FINDINGS_PER_FILE:
            raise AnalysisBlocked(f"{engine} finding limit exceeded for {file_name}")
        if self.findings > MAX_FINDINGS_TOTAL:
            raise AnalysisBlocked(f"{engine} global finding limit exceeded")
        self.check_deadline()
        return finding

    def visit_tool_message(self, engine: str, file_name: str) -> None:
        self.tool_messages += 1
        file_count = self.tool_messages_by_file.get(file_name, 0) + 1
        self.tool_messages_by_file[file_name] = file_count
        if file_count > MAX_TOOL_MESSAGES_PER_FILE:
            raise AnalysisBlocked(f"{engine} message limit exceeded for {file_name}")
        if self.tool_messages > MAX_TOOL_MESSAGES_TOTAL:
            raise AnalysisBlocked(f"{engine} global message limit exceeded")
        self.check_deadline()


# --------------------------------------------------------------------------
# Phase-2 native engines: MIT snapshot symbols/deprecations + vendor hooks.
# --------------------------------------------------------------------------


def version_gt(left: str, right: str) -> bool:
    """True when `left` > `right`, comparing zero-padded numeric segments."""
    a = tuple(int(part) for part in re.findall(r"\d+", left))
    b = tuple(int(part) for part in re.findall(r"\d+", right))
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def load_native_snapshot(snapshot_path: Path | None = None) -> dict[str, Any] | None:
    path = snapshot_path or DEFAULT_SNAPSHOT_PATH
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        return None
    return data


def load_vendor_hooks(php_tools_root: Path | None = None) -> dict[str, dict[str, Any]] | None:
    """Read hook names from the Composer vendor tree (GPL data, never committed)."""
    root = (php_tools_root or DEFAULT_PHP_TOOLS_ROOT).resolve()
    hooks_dir = root / "vendor" / "wp-hooks" / "wordpress-core" / "hooks"
    actions = hooks_dir / "actions.json"
    filters = hooks_dir / "filters.json"
    if not actions.exists() or not filters.exists():
        return None
    hooks: dict[str, dict[str, Any]] = {}
    for kind, payload_path in (("action", actions), ("filter", filters)):
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        for hook in payload.get("hooks", []):
            name = hook.get("name")
            if not name:
                continue
            hooks[name] = {"type": kind, "dynamic": "{" in name or "$" in name}
    return hooks or None


def strip_strings_and_comments(text: str) -> str:
    """Blank out string/comment contents while preserving line structure."""
    out: list[str] = []
    i = 0
    length = len(text)
    while i < length:
        ch = text[i]
        two = text[i : i + 2]
        if two == "/*":
            end = text.find("*/", i + 2)
            end = length if end == -1 else end + 2
            out.append(_blank(text[i:end]))
            i = end
        elif two == "//" or ch == "#":
            end = text.find("\n", i)
            end = length if end == -1 else end
            out.append(_blank(text[i:end]))
            i = end
        elif ch in ("'", '"'):
            j = i + 1
            while j < length:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == ch:
                    break
                j += 1
            end = min(j + 1, length)
            out.append(ch + _blank(text[i + 1 : end - 1]) + (ch if end > i + 1 else ""))
            i = end
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _blank(segment: str) -> str:
    return "".join("\n" if ch == "\n" else " " for ch in segment)


def _newline_offsets(text: str) -> list[int]:
    return [index for index, character in enumerate(text) if character == "\n"]


def _line_of(newline_offsets: list[int], index: int) -> int:
    return bisect.bisect_left(newline_offsets, index) + 1


def _is_plain_call(stripped: str, start: int) -> bool:
    """True when the identifier at `start` is a plain function-call site.

    Adjacency (no whitespace) is what disqualifies: `$var(`, `->method(`,
    `::method(`, part of a longer identifier, or a namespace-qualified
    `Foo\\bar(`. A fully-qualified global `\\bar(` still counts as plain.
    """
    prev_char = stripped[start - 1] if start else ""
    if prev_char.isalnum() or prev_char in ("_", "$"):
        return False
    if stripped[start - 2 : start] in ("->", "::"):
        return False
    if prev_char == "\\":
        before_backslash = stripped[start - 2] if start >= 2 else ""
        if before_backslash.isalnum() or before_backslash == "_":
            return False  # Namespace\call(): out of native scope
    return True


@dataclass(frozen=True)
class HookCall:
    caller: str
    name: str | None
    dynamic: bool
    start: int


def extract_hook_calls(
    raw: str,
    *,
    budget: AnalysisBudget | None = None,
    file_name: str = "<memory>",
) -> list[HookCall]:
    """Extract first-argument hook names from hook API calls.

    A plain quoted literal followed by `,` or `)` is a static hook name.
    Anything else (variable, concatenation, interpolated string) is dynamic.
    """
    calls: list[HookCall] = []
    for match in HOOK_CALL_OPEN_RE.finditer(raw):
        if budget is not None:
            budget.visit_call("hook", file_name)
        caller = match.group(1)
        i = match.end()
        while i < len(raw) and raw[i] in " \t\n":
            i += 1
        if i >= len(raw):
            continue
        quote = raw[i]
        if quote not in ("'", '"'):
            calls.append(HookCall(caller, None, True, match.start()))
            continue
        j = i + 1
        while j < len(raw):
            if budget is not None and j % 4096 == 0:
                budget.check_deadline()
            if raw[j] == "\\":
                j += 2
                continue
            if raw[j] == quote:
                break
            j += 1
        name = raw[i + 1 : j]
        k = j + 1
        while k < len(raw) and raw[k] in " \t\n":
            k += 1
        terminated = k < len(raw) and raw[k] in ",)"
        dynamic = not terminated or "$" in name
        calls.append(HookCall(caller, name, dynamic, match.start()))
    return calls


def _compile_dynamic_hook_patterns(hooks: dict[str, dict[str, Any]]) -> list[tuple[re.Pattern[str], str, bool]]:
    """Dynamic core hooks become match patterns, banded by prefix specificity.

    A static prefix >= 8 chars (`save_post_`) silently allows a matching
    hook; 4-7 chars (`pre_`, `edit_`) only downgrades an unknown hook to
    advisory; < 4 chars (`wp_`, the fully-dynamic `{$field}`) carries no
    information and is ignored so hallucinated names still fail.
    """
    patterns: list[tuple[re.Pattern[str], str, bool]] = []
    for name, meta in hooks.items():
        if not meta.get("dynamic"):
            continue
        static_prefix = re.split(r"[{$]", name)[0]
        if len(static_prefix) < 4:
            continue
        parts = re.split(r"(\{\$[^}]*\}|\$\w+)", name)
        pattern = re.compile(
            "^"
            + "".join(r"[\w-]+" if part.startswith(("{$", "$")) else re.escape(part) for part in parts if part)
            + "$"
        )
        patterns.append((pattern, name, len(static_prefix) >= 8))
    return patterns


def _make_finding(
    finding_class: str,
    symbol: str,
    symbol_kind: str,
    file: str,
    line: int | None,
    evidence: str,
    *,
    confidence: str = "exact",
    allowlisted: bool = False,
    declared_range: dict[str, Any] | None = None,
    introduced_in: str | None = None,
    deprecated_in: str | None = None,
    replacement: str | None = None,
    suggestions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "class": finding_class,
        "symbol": symbol,
        "symbol_kind": symbol_kind,
        "file": file,
        "line": line,
        "confidence": confidence,
        "allowlisted": allowlisted,
        "declared_range": declared_range,
        "introduced_in": introduced_in,
        "deprecated_in": deprecated_in,
        "replacement": replacement,
        "suggestions": suggestions or [],
        "evidence": evidence,
    }


def _artifact_php_texts(
    path: Path,
    explicit_files: list[Path] | None = None,
    budget: AnalysisBudget | None = None,
) -> dict[Path, str]:
    """Artifact PHP texts, excluding test dirs INSIDE the artifact only.

    Matching any absolute path part would also exclude artifacts that
    themselves live under a tests/ directory (the committed bait fixtures do)
    — the same trap `build_neon` scopes its excludePaths against.
    """
    files = {}
    selected_files = explicit_files if explicit_files is not None else iter_php_files(path)
    for file_path in selected_files:
        if budget is not None:
            budget.check_deadline()
        if explicit_files is None and path.is_dir():
            inner_dirs = file_path.relative_to(path).parts[:-1]
            if any(part in ("tests", "test") for part in inner_dirs):
                continue
        files[file_path] = file_path.read_text(encoding="utf-8", errors="replace")
        if budget is not None:
            budget.check_deadline()
    return files


def _relative_name(file_path: Path, path: Path) -> str:
    try:
        return str(file_path.relative_to(path)) if path.is_dir() else file_path.name
    except ValueError:
        return str(file_path)


@dataclass(frozen=True)
class NativeContext:
    declared: str | None
    declared_range: dict[str, Any]
    include_existence: bool
    guarded: set[str]
    defined_functions: set[str]
    defined_classes: set[str]
    slug_prefixes: set[str]
    known_functions: dict[str, dict[str, Any]]
    known_classes: dict[str, dict[str, Any]]
    builtins: set[str]


def _collect_native_names(
    raw_texts: dict[Path, str],
    stripped_texts: dict[Path, str],
    budget: AnalysisBudget,
) -> tuple[set[str], set[str], set[str]]:
    guarded: set[str] = set()
    defined_functions: set[str] = set()
    defined_classes: set[str] = set()
    for file_path, raw in raw_texts.items():
        budget.check_deadline()
        guarded.update(match.group(1).lower() for match in FUNCTION_EXISTS_RE.finditer(raw))
        stripped = stripped_texts[file_path]
        defined_functions.update(match.group(1).lower() for match in DEF_FUNCTION_RE.finditer(stripped))
        defined_classes.update(match.group(1).lower() for match in DEF_CLASS_RE.finditer(stripped))
        budget.check_deadline()
    return guarded, defined_functions, defined_classes


def _known_function_finding(
    name: str,
    lower: str,
    meta: dict[str, Any],
    rel: str,
    line: int,
    evidence: str,
    context: NativeContext,
) -> dict[str, Any] | None:
    if meta.get("deprecated"):
        return _make_finding(
            "deprecated_api", name, "function", rel, line, evidence,
            deprecated_in=meta["deprecated"], replacement=meta.get("replacement"),
            declared_range=context.declared_range,
        )
    since = meta.get("since")
    if not (context.include_existence and since and context.declared):
        return None
    if lower in context.guarded or not version_gt(since, context.declared):
        return None
    return _make_finding(
        "version_range", name, "function", rel, line, evidence,
        introduced_in=since, declared_range=context.declared_range,
    )


def _native_call_finding(
    match: re.Match[str],
    stripped: str,
    newline_offsets: list[int],
    rel: str,
    context: NativeContext,
    budget: AnalysisBudget,
) -> dict[str, Any] | None:
    budget.visit_call("native API", rel)
    name = match.group(1)
    lower = name.lower()
    before = stripped[max(0, match.start() - 12) : match.start()]
    if not _is_plain_call(stripped, match.start()) or lower in PHP_KEYWORDS:
        return None
    if re.search(r"\bfunction\s*&?\s*$", before) or re.search(r"\bnew\s+$", before):
        return None
    line = _line_of(newline_offsets, match.start())
    evidence = stripped[match.start() : match.start() + 80].split("\n")[0].strip()
    meta = context.known_functions.get(lower)
    if meta is not None:
        return _known_function_finding(name, lower, meta, rel, line, evidence, context)
    if not context.include_existence:
        return None
    if (
        lower in context.builtins
        or lower in context.defined_functions
        or lower in context.guarded
    ):
        return None
    allowlisted = any(lower.startswith(prefix) for prefix in context.slug_prefixes)
    budget.check_deadline()
    return _make_finding(
        "unknown_function", name, "function", rel, line, evidence,
        confidence="advisory" if allowlisted else "exact", allowlisted=allowlisted,
        suggestions=difflib.get_close_matches(lower, context.known_functions, n=3, cutoff=0.6),
    )


def _native_class_finding(
    match: re.Match[str],
    stripped: str,
    newline_offsets: list[int],
    rel: str,
    context: NativeContext,
    budget: AnalysisBudget,
) -> dict[str, Any] | None:
    budget.visit_call("native class", rel)
    raw_name = match.group(1)
    if "\\" in raw_name.lstrip("\\"):
        return None
    name = raw_name.lstrip("\\")
    lower = name.lower()
    if lower in {"static", "self", "parent", "class"} or lower in PHP_KEYWORDS:
        return None
    if (
        lower in context.known_classes
        or lower in context.defined_classes
        or lower in context.builtins
    ):
        return None
    allowlisted = any(lower.startswith(prefix) for prefix in context.slug_prefixes)
    budget.check_deadline()
    return _make_finding(
        "unknown_class", name, "class", rel, _line_of(newline_offsets, match.start()),
        stripped[match.start() : match.start() + 80].split("\n")[0].strip(),
        confidence="advisory" if allowlisted else "exact", allowlisted=allowlisted,
        suggestions=difflib.get_close_matches(lower, context.known_classes, n=3, cutoff=0.6),
    )


def _scan_native_file(
    stripped: str,
    rel: str,
    context: NativeContext,
    budget: AnalysisBudget,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    newline_offsets = _newline_offsets(stripped)
    for match in CALL_RE.finditer(stripped):
        finding = _native_call_finding(match, stripped, newline_offsets, rel, context, budget)
        if finding is not None:
            findings.append(budget.add_finding("native API", rel, finding))
    if context.include_existence:
        for match in NEW_CLASS_RE.finditer(stripped):
            finding = _native_class_finding(match, stripped, newline_offsets, rel, context, budget)
            if finding is not None:
                findings.append(budget.add_finding("native class", rel, finding))
    return findings


def native_php_findings(
    path: Path,
    snapshot: dict[str, Any],
    declared: str | None,
    prefixes: list[str],
    declared_range: dict[str, Any],
    include_existence: bool,
    explicit_files: list[Path] | None = None,
    *,
    deadline_monotonic: float | None = None,
    budget: AnalysisBudget | None = None,
) -> list[dict[str, Any]]:
    """Snapshot-backed findings with bounded call sites, findings, and time."""
    active_budget = budget or AnalysisBudget(deadline_monotonic)
    raw_texts = _artifact_php_texts(path, explicit_files, active_budget)
    stripped_texts = {
        file_path: strip_strings_and_comments(text)
        for file_path, text in raw_texts.items()
    }
    guarded, defined_functions, defined_classes = _collect_native_names(
        raw_texts, stripped_texts, active_budget
    )
    slug_prefixes = {prefix.lower() for prefix in prefixes}
    if path.is_dir():
        slug_prefixes.add(path.name.replace("-", "_").lower() + "_")
    context = NativeContext(
        declared, declared_range, include_existence, guarded, defined_functions,
        defined_classes, slug_prefixes, snapshot["functions"], snapshot["classes"],
        set(snapshot.get("php_builtins", [])),
    )
    findings: list[dict[str, Any]] = []
    for file_path, stripped in stripped_texts.items():
        findings.extend(_scan_native_file(stripped, _relative_name(file_path, path), context, active_budget))
    return findings


def _classify_hook(
    name: str,
    hooks: dict[str, dict[str, Any]],
    defined_hooks: set[str],
    slug_prefixes: set[str],
    dynamic_patterns: list[tuple[re.Pattern[str], str, bool]],
    budget: AnalysisBudget,
) -> tuple[str, str | None]:
    if name in hooks or name in defined_hooks:
        return "allowed", None
    if any(name.lower().startswith(prefix) for prefix in slug_prefixes):
        return "allowed", None
    generic_match: str | None = None
    for index, (pattern, pattern_name, specific) in enumerate(dynamic_patterns, start=1):
        if index % ANALYSIS_CHECK_INTERVAL == 0:
            budget.check_deadline()
        if not pattern.match(name):
            continue
        if specific:
            return "allowed", pattern_name
        generic_match = generic_match or pattern_name
    return ("advisory", generic_match) if generic_match else ("unknown", None)


def _hook_call_finding(
    call: HookCall,
    raw: str,
    newline_offsets: list[int],
    rel: str,
    classify: Any,
    static_hook_names: list[str],
) -> dict[str, Any] | None:
    if call.caller not in HOOK_CONSUMERS:
        return None
    line = _line_of(newline_offsets, call.start)
    evidence = raw[call.start : call.start + 120].split("\n")[0].strip()
    if call.dynamic:
        return _make_finding(
            "unknown_hook", call.name or "<dynamic>", "hook", rel, line,
            f"{evidence} [dynamic hook name: verify the interpolated value]",
            confidence="advisory",
        )
    if not call.name:
        return None
    verdict, matched_pattern = classify(call.name)
    if verdict == "allowed":
        return None
    suffix = f" [matches generic dynamic core hook {matched_pattern}: verify]" if verdict == "advisory" else ""
    return _make_finding(
        "unknown_hook", call.name, "hook", rel, line, evidence + suffix,
        confidence="advisory" if verdict == "advisory" else "exact",
        suggestions=difflib.get_close_matches(call.name, static_hook_names, n=3, cutoff=0.6),
    )


def hook_findings(
    path: Path,
    hooks: dict[str, dict[str, Any]],
    prefixes: list[str],
    explicit_files: list[Path] | None = None,
    *,
    deadline_monotonic: float | None = None,
    budget: AnalysisBudget | None = None,
) -> list[dict[str, Any]]:
    """Bounded `unknown_hook` findings for hook consumers."""
    active_budget = budget or AnalysisBudget(deadline_monotonic)
    raw_texts = _artifact_php_texts(path, explicit_files, active_budget)
    calls_by_file = {
        file_path: extract_hook_calls(raw, budget=active_budget, file_name=_relative_name(file_path, path))
        for file_path, raw in raw_texts.items()
    }
    defined_hooks = {
        call.name for calls in calls_by_file.values() for call in calls
        if call.caller in HOOK_DEFINERS and call.name and not call.dynamic
    }
    slug_prefixes = {prefix.lower() for prefix in prefixes}
    if path.is_dir():
        slug_prefixes.add(path.name.replace("-", "_").lower() + "_")
    patterns = _compile_dynamic_hook_patterns(hooks)
    static_names = [name for name in hooks if "{" not in name and "$" not in name]
    classify = lambda name: _classify_hook(name, hooks, defined_hooks, slug_prefixes, patterns, active_budget)
    findings: list[dict[str, Any]] = []
    for file_path, raw in raw_texts.items():
        rel = _relative_name(file_path, path)
        offsets = _newline_offsets(raw)
        for call in calls_by_file[file_path]:
            finding = _hook_call_finding(call, raw, offsets, rel, classify, static_names)
            if finding is not None:
                findings.append(active_budget.add_finding("hook", rel, finding))
    return findings


def resolve_toolchain(php_tools_root: Path | None = None) -> tuple[Toolchain | None, str | None]:
    root = (php_tools_root or DEFAULT_PHP_TOOLS_ROOT).resolve()
    php = shutil.which("php")
    if not php:
        return None, "php executable not found on PATH"
    vendor = root / "vendor"
    phpstan = vendor / "bin" / "phpstan"
    stubs = vendor / "php-stubs" / "wordpress-stubs" / "wordpress-stubs.php"
    wp_compat_neon = vendor / "johnbillion" / "wp-compat" / "extension.neon"
    symbols_json = vendor / "johnbillion" / "wp-compat" / "symbols.json"
    missing = [str(candidate.relative_to(root)) for candidate in (phpstan, stubs, wp_compat_neon, symbols_json) if not candidate.exists()]
    if missing:
        return None, (
            f"pinned PHP toolchain incomplete under {root} (missing: {', '.join(missing)}); "
            f"run: composer install --working-dir {root}"
        )
    return Toolchain(php, phpstan, stubs, wp_compat_neon, symbols_json, root), None


def toolchain_versions(root: Path) -> dict[str, str | None]:
    versions: dict[str, str | None] = {name: None for name in PIN_PACKAGES}
    lock_path = root / "composer.lock"
    if not lock_path.exists():
        return versions
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return versions
    for package in lock.get("packages", []):
        name = package.get("name")
        if name in versions:
            versions[name] = package.get("version")
    return versions


def iter_php_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in PHP_SUFFIXES else []
    files = [
        child
        for child in path.rglob("*")
        if child.is_file()
        and child.suffix.lower() in PHP_SUFFIXES
        and not any(part in IGNORED_DIRS for part in child.relative_to(path).parts[:-1])
    ]
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
) -> tuple[Path, list[Path] | None]:
    if explicit_files is None:
        return path.resolve(), None
    trusted_root = Path(os.path.abspath(path))
    return trusted_root, _trusted_explicit_files(trusted_root, explicit_files)


def _read_header(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")[:HEADER_BYTES]
    return text.replace("\r", "\n")


def _header_files(path: Path, explicit_files: list[Path] | None = None) -> list[Path]:
    files = explicit_files if explicit_files is not None else iter_php_files(path)
    candidates: list[Path] = []
    for file_path in files:
        header = _read_header(file_path)
        if "Plugin Name:" in header or (explicit_files is not None and "Theme Name:" in header):
            candidates.append(file_path)
    if explicit_files is None and path.is_dir():
        style_css = path / "style.css"
        if style_css.exists() and "Theme Name:" in _read_header(style_css):
            candidates.append(style_css)
    return candidates


def declared_requires_at_least(path: Path, explicit_files: list[Path] | None = None) -> str | None:
    for header_file in _header_files(path, explicit_files):
        match = REQUIRES_AT_LEAST_RE.search(_read_header(header_file))
        if match and match.group(1).strip():
            cleaned = re.sub(r"[^0-9.]", "", match.group(1))
            if cleaned:
                return cleaned
    return None


def declared_plugin_dependencies(path: Path, explicit_files: list[Path] | None = None) -> list[str]:
    slugs: list[str] = []
    for header_file in _header_files(path, explicit_files):
        match = REQUIRES_PLUGINS_RE.search(_read_header(header_file))
        if not match:
            continue
        for slug in match.group(1).split(","):
            cleaned = slug.strip().lower()
            if cleaned and cleaned not in slugs:
                slugs.append(cleaned)
    return slugs


def allowlist_prefixes(
    path: Path,
    extra_prefixes: list[str] | None = None,
    explicit_files: list[Path] | None = None,
) -> list[str]:
    prefixes = list(extra_prefixes or [])
    for slug in declared_plugin_dependencies(path, explicit_files):
        for prefix in KNOWN_PLUGIN_PREFIXES.get(slug, (slug.replace("-", "_") + "_",)):
            if prefix not in prefixes:
                prefixes.append(prefix)
    return prefixes


def _neon_string(value: object) -> str:
    """Encode an exact scalar as a NEON-compatible JSON string."""
    return json.dumps(str(value), ensure_ascii=True)


def build_neon(
    artifact_path: Path,
    toolchain: Toolchain,
    tmp_dir: Path,
    requires_at_least: str | None,
    explicit_files: list[Path] | None = None,
) -> str:
    lines: list[str] = []
    if requires_at_least is not None:
        lines += ["includes:", f"    - {_neon_string(toolchain.wp_compat_neon)}", ""]
    # Excludes are scoped to directories INSIDE the artifact: a bare */tests/*
    # pattern would also exclude artifacts that themselves live under a tests/
    # directory (the committed bait fixtures do).
    phpstan_paths = explicit_files if explicit_files is not None else [artifact_path]
    lines += [
        "parameters:",
        "    level: 0",
        f"    tmpDir: {_neon_string(tmp_dir)}",
        "    paths:",
        *(f"        - {_neon_string(file_path)}" for file_path in phpstan_paths),
    ]
    if explicit_files is None:
        exclude_base = artifact_path if artifact_path.is_dir() else artifact_path.parent
        excluded = ("vendor", "node_modules", "tests", "test")
        lines += [
            "    excludePaths:",
            *(
                f"        - {_neon_string(f'{exclude_base}/{ignored}/*')}"
                for ignored in excluded
            ),
            *(
                f"        - {_neon_string(f'{exclude_base}/*/{ignored}/*')}"
                for ignored in excluded
            ),
        ]
    lines += ["    scanFiles:", f"        - {_neon_string(toolchain.stubs)}"]
    if requires_at_least is not None:
        lines += [
            "    WPCompat:",
            f"        requiresAtLeast: {_neon_string(requires_at_least)}",
        ]
    return "\n".join(lines) + "\n"


def _relative_file(raw_path: str, artifact_path: Path) -> str:
    try:
        return str(Path(raw_path).resolve().relative_to(artifact_path.resolve().parent if artifact_path.is_file() else artifact_path.resolve()))
    except ValueError:
        return raw_path


def _extract_symbol(identifier: str, message: str) -> tuple[str, str | None]:
    if identifier == "function.notFound":
        match = UNKNOWN_FUNCTION_RE.search(message)
        return (match.group(1) if match else "unknown"), None
    if identifier == "class.notFound":
        match = UNKNOWN_CLASS_RE.search(message) or UNKNOWN_CLASS_REFERENCED_RE.search(message)
        return (match.group(1) if match else "unknown"), None
    if identifier in {"method.notFound", "staticMethod.notFound"}:
        match = UNKNOWN_METHOD_RE.search(message)
        return (match.group(1) if match else "unknown"), None
    match = WPCOMPAT_SYMBOL_RE.match(message)
    if match:
        return match.group(1), match.group(2)
    hook_match = WPCOMPAT_HOOK_RE.match(message)
    if hook_match:
        return hook_match.group(2), hook_match.group(3)
    return "unknown", None


def _phpstan_finding(
    identifier: str,
    text: str,
    rel_file: str,
    line: int | None,
    index: SymbolIndex,
    prefixes: list[str],
    declared_range: dict[str, Any],
) -> dict[str, Any] | None:
    mapped = FINDING_CLASSES.get(identifier)
    if mapped is None and identifier.startswith(WPCOMPAT_HOOK_IDENTIFIER_PREFIXES):
        mapped = ("version_range", "hook")
    if mapped is None:
        return None
    finding_class, symbol_kind = mapped
    symbol, introduced_in = _extract_symbol(identifier, text)
    allowlisted = finding_class.startswith("unknown_") and any(
        symbol.startswith(prefix) for prefix in prefixes
    )
    return {
        "class": finding_class, "symbol": symbol, "symbol_kind": symbol_kind,
        "file": rel_file, "line": line,
        "confidence": "advisory" if allowlisted else "exact",
        "allowlisted": allowlisted,
        "declared_range": declared_range if finding_class == "version_range" else None,
        "introduced_in": introduced_in, "deprecated_in": None, "replacement": None,
        "suggestions": index.suggest(symbol, symbol_kind) if finding_class.startswith("unknown_") else [],
        "evidence": text,
    }


def parse_phpstan_output(
    output: dict[str, Any],
    artifact_path: Path,
    index: SymbolIndex,
    declared: str | None,
    snapshot_version: str | None,
    prefixes: list[str],
    budget: AnalysisBudget | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    analysis_errors: list[dict[str, Any]] = []
    advisory: list[dict[str, Any]] = []
    declared_range = {"requires_at_least": declared, "snapshot": snapshot_version}

    for raw_file, file_result in sorted((output.get("files") or {}).items()):
        rel_file = _relative_file(raw_file, artifact_path)
        for message in file_result.get("messages", []):
            if budget is not None:
                budget.visit_tool_message("PHPStan", rel_file)
            identifier = str(message.get("identifier") or "")
            text = str(message.get("message") or "")
            line = message.get("line")
            record = {"file": rel_file, "line": line, "identifier": identifier, "message": text}
            if identifier in ANALYSIS_ERROR_IDENTIFIERS:
                analysis_errors.append(record)
                continue
            finding = _phpstan_finding(
                identifier, text, rel_file, line, index, prefixes, declared_range
            )
            if budget is not None:
                budget.check_deadline()
            if finding is None:
                advisory.append(record)
                continue
            findings.append(finding)

    for error in output.get("errors") or []:
        if budget is not None:
            budget.visit_tool_message("PHPStan", "<global>")
        analysis_errors.append({"file": None, "line": None, "identifier": "phpstan.error", "message": str(error)})

    findings.sort(key=lambda item: (item["file"], item["line"] or 0, item["symbol"]))
    return findings, analysis_errors, advisory


def _finding_sentence(finding: dict[str, Any]) -> str:
    symbol = finding["symbol"]
    location = f"{finding['file']}:{finding['line']}"
    if finding["class"] == "version_range":
        declared = (finding.get("declared_range") or {}).get("requires_at_least")
        label = {"hook": "hook", "method": "method", "function": "function"}.get(finding["symbol_kind"], "symbol")
        return (
            f"{label} {symbol} requires WordPress {finding['introduced_in']} but the artifact declares "
            f"Requires at least: {declared} at {location} (raise the header or wrap in a function_exists() guard)"
        )
    if finding["class"] == "deprecated_api":
        sentence = f"{symbol}() is deprecated since WordPress {finding['deprecated_in']} at {location}"
        if finding.get("replacement"):
            sentence += f" (use {finding['replacement']})"
        return sentence
    kind = finding["class"].removeprefix("unknown_")
    sentence = f"unknown {kind} {symbol} at {location}"
    if finding["suggestions"]:
        sentence += f" (did you mean {finding['suggestions'][0]}?)"
    if finding["allowlisted"]:
        sentence += " [allowlisted prefix: advisory]"
    return sentence


def summarize_report(report: dict[str, Any]) -> str:
    status = report.get("status")
    if status == "blocked":
        return str(report.get("blocked_reason") or "API-existence lint blocked")
    if status == "skip":
        return "no PHP files to scan"
    engines = report.get("engines") or {}
    engine_note = ""
    unavailable = [name for name, state in engines.items() if state != "ran"]
    if unavailable:
        engine_note = f"; reduced coverage — unavailable engine(s): {', '.join(sorted(unavailable))}"
    if status == "pass":
        declared = report.get("declared_requires_at_least")
        range_note = (
            f"version range consistent with Requires at least: {declared}"
            if report.get("version_range_checked")
            else "version range not evaluated (no Requires at least header)"
        )
        advisory_count = sum(1 for finding in report.get("findings", []) if finding.get("confidence") != "exact")
        advisory_note = f"; {advisory_count} advisory finding(s)" if advisory_count else ""
        return f"no unknown core symbols; {range_note}{advisory_note}{engine_note}"
    failing = [finding for finding in report.get("findings", []) if finding.get("confidence") == "exact"]
    sentences = [_finding_sentence(finding) for finding in failing[:3]]
    sentences += [
        f"PHP analysis error at {error['file']}:{error['line']}: {error['message']}" if error.get("file") else f"PHP analysis error: {error['message']}"
        for error in report.get("analysis_errors", [])[:2]
    ]
    remainder = len(failing) - 3
    suffix = f"; +{remainder} more in api-lint.json" if remainder > 0 else ""
    return f"{len(failing)} API finding(s): " + "; ".join(sentences) + suffix + engine_note


@dataclass
class ApiLintState:
    path: Path
    scan_files: list[Path] | None
    toolchain: Toolchain | None
    toolchain_error: str | None
    native_snapshot: dict[str, Any] | None
    vendor_hooks: dict[str, dict[str, Any]] | None
    declared: str | None
    prefixes: list[str]
    snapshot_version: str | None
    declared_range: dict[str, Any]
    report: dict[str, Any]
    findings: list[dict[str, Any]]


def _analysis_limits() -> dict[str, int]:
    return {
        "call_sites_per_file": MAX_CALL_SITES_PER_FILE,
        "call_sites_total": MAX_CALL_SITES_TOTAL,
        "findings_per_file": MAX_FINDINGS_PER_FILE,
        "findings_total": MAX_FINDINGS_TOTAL,
        "tool_messages_per_file": MAX_TOOL_MESSAGES_PER_FILE,
        "tool_messages_total": MAX_TOOL_MESSAGES_TOTAL,
    }


def _analysis_usage(budget: AnalysisBudget) -> dict[str, int]:
    return {
        "call_sites": budget.call_sites,
        "findings": budget.findings,
        "tool_messages": budget.tool_messages,
    }


def _new_api_lint_state(
    path: Path,
    scan_files: list[Path] | None,
    php_tools_root: Path | None,
    snapshot_path: Path | None,
    extra_prefixes: list[str] | None,
) -> ApiLintState:
    toolchain, toolchain_error = resolve_toolchain(php_tools_root)
    snapshot = load_native_snapshot(snapshot_path)
    hooks = load_vendor_hooks(php_tools_root)
    versions = toolchain_versions((php_tools_root or DEFAULT_PHP_TOOLS_ROOT).resolve())
    declared = declared_requires_at_least(path, explicit_files=scan_files)
    prefixes = allowlist_prefixes(path, extra_prefixes, explicit_files=scan_files)
    stubs_version = versions.get("php-stubs/wordpress-stubs")
    snapshot_version = stubs_version.lstrip("v") if stubs_version else None
    declared_range = {
        "requires_at_least": declared,
        "snapshot": snapshot_version or (snapshot or {}).get("wp_version"),
    }
    engines = {
        "phpstan": "ran" if toolchain else f"unavailable ({toolchain_error})",
        "native_symbols": "ran" if snapshot else "unavailable (committed snapshot missing)",
        "hooks": "ran" if hooks else "unavailable (vendor wp-hooks data missing)",
    }
    report = _new_api_report(path, declared, prefixes, engines, versions)
    return ApiLintState(
        path, scan_files, toolchain, toolchain_error, snapshot, hooks, declared,
        prefixes, snapshot_version, declared_range, report, [],
    )


def _new_api_report(
    path: Path,
    declared: str | None,
    prefixes: list[str],
    engines: dict[str, str],
    versions: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema": SCHEMA, "schema_version": SCHEMA_VERSION,
        "artifact_path": str(path), "status": "blocked", "blocked_reason": None,
        "declared_requires_at_least": declared,
        "version_range_checked": declared is not None,
        "allowlisted_prefixes": prefixes, "engines": engines, "findings": [],
        "analysis_errors": [], "advisory": [], "tooling": versions,
        "negative_space": list(NEGATIVE_SPACE), "analysis_limits": _analysis_limits(),
        "analysis_usage": {"call_sites": 0, "findings": 0, "tool_messages": 0},
    }


def _run_native_analyses(state: ApiLintState, budget: AnalysisBudget) -> None:
    negative_space = state.report["negative_space"]
    if state.native_snapshot is not None:
        state.findings.extend(native_php_findings(
            state.path, state.native_snapshot, state.declared, state.prefixes,
            state.declared_range, include_existence=state.toolchain is None,
            explicit_files=state.scan_files, budget=budget,
        ))
        if state.toolchain is None:
            negative_space.append(
                "PHPStan toolchain unavailable: unknown-method detection and real scope "
                "analysis did not run (regex-tier native fallback used)."
            )
    else:
        negative_space.append("Committed symbol snapshot missing: deprecated-API detection did not run.")
    if state.vendor_hooks is not None:
        state.findings.extend(hook_findings(
            state.path, state.vendor_hooks, state.prefixes,
            explicit_files=state.scan_files, budget=budget,
        ))
    else:
        negative_space.append("Vendor wp-hooks data unavailable: unknown-hook detection did not run.")


def _phpstan_command(
    state: ApiLintState, tmp_path: Path, analysis_files: list[Path] | None
) -> list[str]:
    assert state.toolchain is not None
    phpstan_tmp = tmp_path / "phpstan-tmp"
    phpstan_tmp.mkdir()
    neon_path = tmp_path / "phpstan.neon"
    neon_path.write_text(
        build_neon(
            state.path, state.toolchain, phpstan_tmp, state.declared,
            explicit_files=analysis_files,
        ),
        encoding="utf-8",
    )
    return [
        state.toolchain.php, str(state.toolchain.phpstan), "analyse",
        "--error-format=json", "--no-progress", "--memory-limit=1G",
        "-c", str(neon_path),
    ]


def _run_phpstan(
    state: ApiLintState, deadline_monotonic: float,
    analysis_files: list[Path] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    with tempfile.TemporaryDirectory(prefix="wp-api-lint-") as tmp:
        command = _phpstan_command(state, Path(tmp), analysis_files)
        try:
            proc = run_bounded(
                command, deadline_monotonic=deadline_monotonic,
                stdout_limit=TOOL_STDOUT_LIMIT, stderr_limit=TOOL_STDERR_LIMIT,
            )
        except BoundedProcessTimeout as exc:
            return None, f"phpstan blocked: {exc}"
        except BoundedProcessOverflow as exc:
            return None, f"phpstan output blocked: {exc}"
        except (BoundedProcessError, OSError) as exc:
            return None, f"phpstan execution blocked: {exc}"
    if proc.returncode not in (0, 1):
        return None, f"phpstan exited {proc.returncode}: {proc.stderr.strip()[:400]}"
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError:
        return None, f"phpstan produced unparseable output: {proc.stdout.strip()[:200]}"


def _finish_without_phpstan(state: ApiLintState) -> dict[str, Any]:
    state.findings.sort(key=lambda item: (item["file"], item["line"] or 0, item["symbol"]))
    state.report["findings"] = state.findings
    failing = [finding for finding in state.findings if finding.get("confidence") == "exact"]
    state.report["status"] = "fail" if failing else "pass"
    return state.report


def _merge_phpstan(
    state: ApiLintState, output: dict[str, Any], budget: AnalysisBudget
) -> dict[str, Any]:
    assert state.toolchain is not None
    index = SymbolIndex.from_symbols_json(state.toolchain.symbols_json)
    findings, errors, advisory = parse_phpstan_output(
        output, state.path, index, state.declared, state.snapshot_version,
        state.prefixes, budget,
    )
    state.findings.extend(findings)
    state.findings.sort(key=lambda item: (item["file"], item["line"] or 0, item["symbol"]))
    state.report.update({"findings": state.findings, "analysis_errors": errors, "advisory": advisory})
    failing = [finding for finding in state.findings if finding.get("confidence") == "exact"]
    state.report["status"] = "fail" if failing or errors else "pass"
    state.report["blocked_reason"] = None
    return state.report


def _empty_api_report(path: Path, php_tools_root: Path | None) -> dict[str, Any]:
    root = (php_tools_root or DEFAULT_PHP_TOOLS_ROOT).resolve()
    report = _new_api_report(
        path, None, [],
        {"phpstan": "not_run", "native_symbols": "not_run", "hooks": "not_run"},
        toolchain_versions(root),
    )
    report.update({"status": "skip", "blocked_reason": None})
    return report


def _run_aliased_phpstan(
    state, budget, deadline, explicit_alias_names, explicit_alias_members
):
    assert state.scan_files is not None
    scan_files = state.scan_files
    names = explicit_alias_names or php_scanner_aliases.default_alias_names(
        scan_files
    )
    base = state.path if state.path.is_dir() else state.path.parent
    try:
        with php_scanner_aliases.stage_aliases(
            scan_files, names, deadline, explicit_alias_members
        ) as aliases:
            state.report["scanner_aliases"] = php_scanner_aliases.evidence(
                aliases, base
            )
            output, error = _run_phpstan(state, deadline, list(aliases.files))
            if output is not None:
                output = php_scanner_aliases.remap_output_files(output, aliases)
    except (OSError, TimeoutError, ValueError) as exc:
        state.report["blocked_reason"] = f"PHP scanner alias blocked: {exc}"
        return state.report
    if error is not None:
        state.report["blocked_reason"] = error
        return state.report
    try:
        result = _merge_phpstan(state, output, budget)
    except AnalysisBlocked as exc:
        state.report["blocked_reason"] = str(exc)
        return state.report
    state.report["analysis_usage"] = _analysis_usage(budget)
    return result


def _run_direct_phpstan(state, budget, deadline):
    output, error = _run_phpstan(state, deadline, None)
    if error is not None:
        state.report["blocked_reason"] = error
        return state.report
    try:
        result = _merge_phpstan(state, output, budget)
    except AnalysisBlocked as exc:
        state.report["blocked_reason"] = str(exc)
        return state.report
    state.report["analysis_usage"] = _analysis_usage(budget)
    return result


def run_api_lint(
    path: Path,
    timeout_sec: int = 120,
    php_tools_root: Path | None = None,
    extra_allow_prefixes: list[str] | None = None,
    snapshot_path: Path | None = None,
    explicit_files: Iterable[Path | str] | None = None,
    explicit_alias_names: dict[Path, str] | None = None,
    explicit_alias_members: dict[Path, tuple[int, str]] | None = None,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    deadline = deadline_monotonic if deadline_monotonic is not None else time.monotonic() + timeout_sec
    path, scan_files = _prepare_scan_files(path, explicit_files)
    if scan_files is not None and not scan_files:
        return _empty_api_report(path, php_tools_root)
    if scan_files is None and not iter_php_files(path):
        return _empty_api_report(path, php_tools_root)
    state = _new_api_lint_state(path, scan_files, php_tools_root, snapshot_path, extra_allow_prefixes)
    if state.toolchain is None and state.native_snapshot is None:
        state.report["blocked_reason"] = (
            f"{state.toolchain_error}; committed symbol snapshot also missing "
            f"({snapshot_path or DEFAULT_SNAPSHOT_PATH})"
        )
        state.report["version_range_checked"] = False
        return state.report
    budget = AnalysisBudget(deadline)
    try:
        _run_native_analyses(state, budget)
    except AnalysisBlocked as exc:
        state.report["blocked_reason"] = str(exc)
        state.report["analysis_usage"] = _analysis_usage(budget)
        return state.report
    state.report["analysis_usage"] = _analysis_usage(budget)
    if state.toolchain is None:
        return _finish_without_phpstan(state)
    if state.scan_files is None:
        return _run_direct_phpstan(state, budget, deadline)
    return _run_aliased_phpstan(
        state, budget, deadline, explicit_alias_names, explicit_alias_members
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WordPress API-existence and version-range lint (PHPStan-backed, phase 1).")
    parser.add_argument("--path", required=True, help="Generated artifact directory or PHP file.")
    parser.add_argument("--timeout-sec", type=int, default=120)
    parser.add_argument("--php-tools-root", type=Path, help=f"Composer toolchain root (default: {DEFAULT_PHP_TOOLS_ROOT}).")
    parser.add_argument(
        "--allow-prefix",
        action="append",
        help="Extra third-party symbol/hook prefix treated as advisory/allowed instead of failing. May be repeated.",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        help=f"Committed MIT symbol snapshot for the native engine (default: {DEFAULT_SNAPSHOT_PATH}).",
    )
    parser.add_argument("--out", type=Path, help="Optional path to write the api-lint.json report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_api_lint(
        Path(args.path),
        timeout_sec=args.timeout_sec,
        php_tools_root=args.php_tools_root,
        extra_allow_prefixes=args.allow_prefix,
        snapshot_path=args.snapshot,
    )
    serialized = json.dumps(report, indent=2, sort_keys=True)
    print(serialized)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(serialized + "\n", encoding="utf-8")
    if report["status"] == "pass":
        return 0
    if report["status"] == "blocked":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
