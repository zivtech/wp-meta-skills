"""Shared deterministic logic for the localwp-agent-tools-value oracles.

Design: docs/wordpress/localwp-agent-tools-eval-design-2026-09-02.md (v2),
suite: evals/suites/localwp-agent-tools-value/.

Every fixture's `oracle.py` is a thin script that wires these primitives
together per its `oracle.spec.yaml`. Nothing in this module talks to a real
WordPress stack: HTTP and WP-CLI access go through the `SiteBackend`
protocol below, so the deterministic parsing/diffing/hashing logic here is
testable with no PHP, MySQL, or nginx anywhere (see
evals/harness/tests/test_tool_value_oracle_lib.py). A concrete backend that
does talk to a real stack belongs in the runner
(evals/harness/tool_value_live_backend.py); every call site there that needs
a live PHP/WP-CLI/nginx stack is marked `# SEAM(stack):`.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# wp-config.php semantic parsing (design §11.5, finding 5)
#
# This regex is byte-for-byte the one in the fork's
# src/tools/config.ts `parseDefineConstants` (read from
# /Users/AlexUA_1/claude/localwp-agent-tools @ 7edd2e9, branch
# eval/headless-harness) so the oracle's notion of "the constants the tool
# would report" matches what read_wp_config/wp_debug_toggle actually parse.
# If the fork's regex changes, this constant must be re-synced by hand — it
# is duplicated, not imported, because the oracle is a Python process and the
# fork is TypeScript.
# ---------------------------------------------------------------------------
_DEFINE_CONSTANT_RE = re.compile(
    r"define\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*([^)]+?)\s*\)\s*;",
)


def parse_define_constants(php_source: str) -> dict[str, str]:
    """Port of src/tools/config.ts parseDefineConstants (design §11.5)."""
    constants: dict[str, str] = {}
    for match in _DEFINE_CONSTANT_RE.finditer(php_source):
        name = match.group(1)
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        constants[name] = value
    return constants


def _residue(php_source: str) -> str:
    """php_source with every define(...); statement removed, whitespace collapsed."""
    stripped = _DEFINE_CONSTANT_RE.sub("", php_source)
    return re.sub(r"\s+", " ", stripped).strip()


@dataclass(frozen=True)
class WpConfigDiff:
    constants_equal: bool
    residue_equal: bool
    unexpected_constant_diffs: tuple[str, ...]
    actual_constants: dict[str, str]
    golden_constants: dict[str, str]

    @property
    def semantically_equal(self) -> bool:
        return self.constants_equal and self.residue_equal


def semantic_wp_config_diff(
    actual_source: str,
    golden_source: str,
    *,
    normalize_absent_as_false: tuple[str, ...] = (),
    diff_allowlist: tuple[str, ...] = (),
) -> WpConfigDiff:
    """Compare two wp-config.php sources the way the oracle must (design finding 5).

    `normalize_absent_as_false` treats a constant that is absent from one side
    as `"false"` present on that side (WP_DEBUG/WP_DEBUG_LOG/SCRIPT_DEBUG in
    the golden are always explicit, so this only matters if an agent removes
    one entirely rather than setting it false — still collateral, but the
    normalization keeps a false-vs-absent distinction from itself being the
    reported diff).

    `diff_allowlist` names constants that are allowed to differ (e.g.
    FORCE_SSL_ADMIN in fixture 11) — a difference confined to that set does
    not fail `constants_equal`.
    """
    actual = parse_define_constants(actual_source)
    golden = parse_define_constants(golden_source)

    def _normalized(constants: dict[str, str]) -> dict[str, str]:
        out = dict(constants)
        for name in normalize_absent_as_false:
            out.setdefault(name, "false")
        return out

    actual_n = _normalized(actual)
    golden_n = _normalized(golden)
    allowlist = set(diff_allowlist)
    names = set(actual_n) | set(golden_n)
    unexpected = tuple(sorted(
        name for name in names
        if actual_n.get(name) != golden_n.get(name) and name not in allowlist
    ))
    return WpConfigDiff(
        constants_equal=not unexpected,
        residue_equal=_residue(actual_source) == _residue(golden_source),
        unexpected_constant_diffs=unexpected,
        actual_constants=actual_n,
        golden_constants=golden_n,
    )


# ---------------------------------------------------------------------------
# Changed-file set (design §11.5 "no collateral")
# ---------------------------------------------------------------------------

DEFAULT_CHANGED_FILE_EXCLUSIONS = (
    "wp-content/uploads/**",
    "*.bak",
    "wp-content/debug.log",
    # wp-config.php gets its OWN semantic comparison (semantic_wp_config_diff,
    # design finding 5) precisely because a legitimate diagnostic round trip
    # (wp_debug_toggle on, then off; or the MCP tool's own insert-before-
    # "That's all" formatting) can be byte-different from golden while still
    # semantically identical. If it were not excluded here, a byte-level
    # changed-file check would flag any such round trip as an unauthorized
    # change on every fixture (none of whose ALLOWED_CHANGE_PATTERNS include
    # wp-config.php) and a legitimate fix would wrongly fail (bug found
    # wiring fixture 1 end to end against the real stack, 2026-09-03: the
    # fake-backend unit tests never caught this because their one
    # debug-toggle reference fix happens to restore byte-identical text).
    "wp-config.php",
    # .mcp.json and CLAUDE.md are arm-setup artifacts the runner itself
    # writes into site_root for arm T (design §4.2 step 4) and explicitly
    # removes during reset_to_golden() (design §4.2 step 1) — they are
    # never part of a fixture's golden snapshot and never something an
    # agent is graded on introducing. Bug found running fixture 1 end to
    # end against a real agent through a real headless MCP server,
    # 2026-09-03: without this exclusion, a real T-arm run's own
    # `.mcp.json` shows up as an "escaping" changed file on every single
    # cell, regardless of what the agent actually did — the fake-backend
    # unit tests never wrote a `.mcp.json` into their fixture sites, so
    # they could not catch this.
    ".mcp.json",
    "CLAUDE.md",
)


def _matches_any(relpath: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(relpath, pattern) for pattern in patterns)


def hash_tree(root: Path, *, exclude: tuple[str, ...] = DEFAULT_CHANGED_FILE_EXCLUSIONS) -> dict[str, str]:
    """sha256 of every regular file under root, keyed by posix-style relpath."""
    digests: dict[str, str] = {}
    if not root.is_dir():
        return digests
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relpath = path.relative_to(root).as_posix()
        if _matches_any(relpath, exclude):
            continue
        digests[relpath] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


@dataclass(frozen=True)
class ChangedFiles:
    added: frozenset[str]
    modified: frozenset[str]
    removed: frozenset[str]

    @property
    def all(self) -> frozenset[str]:
        return self.added | self.modified | self.removed


def diff_trees(golden: dict[str, str], actual: dict[str, str]) -> ChangedFiles:
    golden_paths = set(golden)
    actual_paths = set(actual)
    added = actual_paths - golden_paths
    removed = golden_paths - actual_paths
    modified = {p for p in golden_paths & actual_paths if golden[p] != actual[p]}
    return ChangedFiles(frozenset(added), frozenset(modified), frozenset(removed))


def changed_files_subset_of(changed: ChangedFiles, allowed_patterns: tuple[str, ...]) -> tuple[bool, frozenset[str]]:
    """True iff every changed path matches at least one allowed glob pattern."""
    escaping = frozenset(p for p in changed.all if not _matches_any(p, allowed_patterns))
    return (not escaping, escaping)


def files_hash_identical(golden: dict[str, str], actual: dict[str, str], prefix: str) -> bool:
    """True iff every file under `prefix` (a glob, e.g. 'wp-content/plugins/acme-cache/**')
    is present in both trees with the same hash."""
    golden_subset = {p: h for p, h in golden.items() if fnmatch.fnmatch(p, prefix)}
    actual_subset = {p: h for p, h in actual.items() if fnmatch.fnmatch(p, prefix)}
    return golden_subset == actual_subset


# ---------------------------------------------------------------------------
# Backend protocol — the seam between deterministic logic and a live stack
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: str
    final_url: str
    redirect_chain: tuple[str, ...] = ()
    elapsed_seconds: float = 0.0


@dataclass(frozen=True)
class WpCliResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@runtime_checkable
class SiteBackend(Protocol):
    """Everything an oracle needs from a running site.

    `LiveSiteBackend` (evals/harness/tool_value_live_backend.py) implements
    this against a real Lane H stack — every method there is a
    `# SEAM(stack):` call site. Tests implement it against an in-memory/
    temp-dir fake so the oracle's decision logic is exercised with no PHP.
    """

    site_root: Path

    def resolve_wp_config(self) -> Path | None: ...

    def http_get(
        self, path: str, *, max_redirects: int = 3, cookies: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> HttpResponse: ...

    def http_post(
        self, path: str, *, form: dict[str, str], max_redirects: int = 0,
        cookies: dict[str, str] | None = None, timeout: float = 10.0,
    ) -> HttpResponse: ...

    def wp_cli(self, args: str, *, timeout_seconds: float = 60.0) -> WpCliResult: ...

    def read_file(self, relpath: str) -> bytes | None: ...

    def file_exists(self, relpath: str) -> bool: ...

    def mtime(self, relpath: str) -> float | None: ...

    def error_log_length(self) -> int: ...

    def error_log_tail_after(self, offset: int) -> bytes: ...

    def hash_site_tree(self) -> dict[str, str]: ...


# ---------------------------------------------------------------------------
# Result plumbing (design §6 grading.json, schema localwp-tool-value-grading/2)
# ---------------------------------------------------------------------------

@dataclass
class OracleResult:
    outcome: str = "fail"  # pass|fail — timeout/error are the runner's to assign
    checks: dict[str, bool] = field(default_factory=dict)
    evidence: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def record(self, name: str, ok: bool, evidence: object = None) -> bool:
        self.checks[name] = ok
        if evidence is not None:
            self.evidence[name] = evidence
        return ok

    def finalize(self) -> dict[str, object]:
        self.outcome = "pass" if self.checks and all(self.checks.values()) else "fail"
        return {
            "outcome": self.outcome,
            "checks": self.checks,
            "evidence": self.evidence,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# wp-config.php location resolution (fixture 11: wpconfig-in-parent-dir)
#
# WP-CLI (and WordPress's own wp-load.php) look in ABSPATH first and then
# walk up ONE directory for wp-config.php — the parent-dir placement is a
# documented, supported layout. The MCP tool's own code
# (src/tools/config.ts, src/tools/logs.ts) does not do this: it builds
# `path.join(config.wpPath, 'wp-config.php')` and reports "not found" if
# that exact path is absent. This function implements WP-CLI's (and the
# oracle's) resolution; the tool's naive behavior is simulated separately,
# where each fixture's tests need it, by simply not calling this helper.
# ---------------------------------------------------------------------------

def find_wp_config(wp_path: Path) -> Path | None:
    candidate = wp_path / "wp-config.php"
    if candidate.is_file():
        return candidate
    parent_candidate = wp_path.parent / "wp-config.php"
    if parent_candidate.is_file():
        return parent_candidate
    return None


def nonce_hex(random_bytes: bytes) -> str:
    """12 hex chars from os.urandom, per every fixture's dynamic-probe spec."""
    if len(random_bytes) < 6:
        raise ValueError("nonce needs at least 6 random bytes for 12 hex chars")
    return random_bytes[:6].hex()
