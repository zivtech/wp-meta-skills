#!/usr/bin/env python3
"""Probe a WordPress environment and emit a machine-readable capability manifest.

The probe answers one question before any WordPress planning or review happens:
what can this agent actually run here? It reports; it never remediates, never
installs, and never modifies a WordPress site.

Design contract:

* All probing logic lives here, not in a prompt. The agent runs this script and
  reads the manifest. It never parses `wp --info` with its own eyes.
* Ground truth is `<prefix> --info`, not a marker file. A marker picks the
  invocation prefix; the prefix is only believed once it answers.
* `BLOCKED` and `UNKNOWN` never satisfy a capability. Absence of a failure is
  not a pass.
* The script exits 0 and emits a schema-valid manifest even when the
  environment is completely empty. A probe that dies on a bare machine is
  useless precisely when it is most needed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROBE_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0.0"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "capability-manifest.schema.json"
DEFAULT_OUT = "capability-manifest.json"
DEFAULT_TIMEOUT_SEC = 20
PLUGIN_CHECK_TIMEOUT_SEC = 60
# Nine 20s help probes plus a 60s plugin check is a ~6 minute worst case per
# environment; the budget bounds the whole run so a wall of hanging commands
# cannot stall the caller indefinitely.
DEFAULT_BUDGET_SEC = 300
EXCERPT_LIMIT = 2000

# --- Version truth, verified August 2026 -------------------------------------
# Each constant below carries its own delete condition. A caveat that cannot
# expire becomes stale guidance, which is the exact failure this probe exists
# to prevent.

# Delete this set once `ability` and `block` ship in a stable WP-CLI phar.
# developer.wordpress.org/cli/commands/ is generated from trunk and documents
# both; neither is in the 2.12.0 phar.
TRUNK_ONLY_WP_CLI_COMMANDS = frozenset({"ability", "block"})

# Delete this assertion once a stable WP-CLI 3.x release announcement exists on
# make.wordpress.org/cli. Command packages requiring `wp-cli/wp-cli ^3.0` were
# tagged 2026-08-04 with no corresponding core release announcement.
WP_CLI_3X_IS_UNVERIFIED = True

# Delete this floor once php-stubs/wordpress-stubs ships stubs for the running
# core version. The package floors at 6.6, so PHPStan emits false "unknown
# function" errors on WP 7.0 APIs including the Abilities API and AI Client.
PHPSTAN_WP_STUBS_FLOOR = "6.6"

# Delete this pairing once WPCS drops the PHPCS 3.13.5 floor.
WPCS_REQUIRED_PHPCS = "3.13.5"

# Delete entries as each is revived upstream. All three still rank well in
# search results, which is why they are worth flagging on sight.
DEPRECATED_TOOLING = frozenset(
    {
        "wordpress-mcp",  # Automattic/wordpress-mcp archived 2026-01-19
        "wp-feature-api",  # superseded by the Abilities API
        "wp-now",  # deprecated 2026-06-08 for @wp-playground/cli
    }
)

# Delete this once wordpress/mcp-adapter tags 1.0.0.
MCP_ADAPTER_PRERELEASE_CEILING = 1

# --- Safety ------------------------------------------------------------------
# The probe is read-only, so it declares exactly what it may run and refuses
# everything else at the single choke point below. A denylist over a
# ~400-command WP-CLI surface fails open the moment a command is missing from
# it (`wp db export`, `wp site delete`, and eleven more destructive commands
# passed the old list); the allowlist fails closed and fits on one screen.

# Exact WP-CLI subcommand paths the probe issues. "" is `<prefix> --info`,
# a global-flags-only invocation with no subcommand.
READ_ONLY_WP_SUBCOMMANDS = frozenset(
    {
        "",
        "cli version",
        "core version",
        "core is-installed",
        "config get MULTISITE",
        "option get siteurl",
        "option get home",
        "plugin list",
        "theme list",
        "ability list",
        "plugin check",
    }
)

# `wp help <anything>` renders documentation and never touches the site.
HELP_WP_SUBCOMMAND = "help"

# `wp eval` is the one gated exception: the highest-privilege command in the
# surface and also the only reliable way to get structured PHP/WP facts, so it
# is permitted only behind --allow-eval (default off).
EVAL_EXCEPTION_COMMANDS = frozenset({"eval"})

# Host tools the probe may invoke directly, keyed by executable basename, with
# the exact argument vectors permitted for each.
HOST_TOOL_ALLOWLIST: dict[str, frozenset[tuple[str, ...]]] = {
    "php": frozenset({("--version",)}),
    "node": frozenset({("--version",)}),
    "composer": frozenset({("--version",)}),
    "phpcs": frozenset({("--version",), ("-i",)}),
    "phpstan": frozenset({("--version",)}),
    "npx": frozenset(
        {
            ("--no-install", "@wordpress/env", "--version"),
            ("--no-install", "@wp-playground/cli", "--version"),
        }
    ),
}

# Shared by the value pattern below and by the argv guard in ProbeRunner.run:
# a command whose argv names one of these keys gets its whole stdout excerpt
# redacted, because output like `wp config get DB_PASSWORD` is the bare value
# with no key on the line for the pattern to anchor on.
SECRET_KEY_NAMES = (
    "DB_PASSWORD", "DB_USER", "DB_NAME", "DB_HOST",
    "AUTH_KEY", "SECURE_AUTH_KEY", "LOGGED_IN_KEY", "NONCE_KEY",
    "AUTH_SALT", "SECURE_AUTH_SALT", "LOGGED_IN_SALT", "NONCE_SALT",
    "WP_API_PASSWORD", "WORDPRESS_DB_PASSWORD", "WORDPRESS_DB_USER", "WORDPRESS_DB_NAME",
)
SECRET_ARGV_TOKENS = frozenset(SECRET_KEY_NAMES)
# Matched anywhere in a line, not just at its start: a credential printed
# mid-line must not escape redaction. Only the value is replaced, so the key
# stays visible and the manifest still says which secret was withheld. `|` is
# a separator because `wp config list` renders `| DB_PASSWORD | hunter2 |`.
SECRET_KEY_PATTERN = re.compile(
    r"(?i)\b(" + "|".join(SECRET_KEY_NAMES) + r")\b"
    r"['\"]?\s*[:=,|]\s*"
    r"(?P<value>'[^']*'|\"[^\"]*\"|[^\s,;|)]+)"
)
# A URL userinfo component is a credential wherever it appears: a siteurl
# carrying basic-auth, or a mysql:// DSN in ddev/wp-env stderr on a DB failure.
URL_USERINFO_PATTERN = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)(?:[^/\s@:]+(?::[^/\s@]*)?)@")
# `mysql -u root -phunter2` in DB-failure stderr. The short form only redacts
# on lines that name a mysql-family tool, so `-p...` tokens in other tools'
# output stay legible; `--password=` is unambiguous and redacts anywhere.
MYSQL_PASSWORD_FLAG_PATTERN = re.compile(r"(?:^|(?<=\s))-p[^\s]+")
MYSQL_CUE = re.compile(r"(?i)\b(?:mysql|mariadb|mysqladmin|mysqldump)\b")
PASSWORD_EQ_PATTERN = re.compile(r"(?i)--password=[^\s]+")
# WordPress application passwords are 24 characters rendered in six space
# separated groups. Matching that shape alone corrupts ordinary prose (any six
# four-character words in a row), so redaction requires a password cue on the
# line, or the value standing alone as the whole line (`--porcelain` output).
APPLICATION_PASSWORD_PATTERN = re.compile(r"\b[A-Za-z0-9]{4}(?: [A-Za-z0-9]{4}){5}\b")
APPLICATION_PASSWORD_CUE = re.compile(r"(?i)\b(?:app(?:lication)?[-_ ]?pass(?:word)?s?|password)\b")
HOME_PATH_PATTERN = re.compile(
    r"(?:/Users|/home)/[^/\s:'\"]+|(?i:[A-Z]:[\\/]Users[\\/][^\\/\s:'\"]+)"
)
# `wp --info` prints the kernel build string on its OS: line, which is
# host-identifying (it put a developer's orbstack kernel ID into the golden
# fixture). Keep the OS family token, drop the rest.
WP_INFO_OS_LINE_PATTERN = re.compile(r"(?im)^(OS:[ \t]+)(\S+)[ \t]+\S.*$")
REDACTED = "[REDACTED]"

# Leaf keys that describe the probe's own reasoning rather than a probed fact.
# Fact fields require an evidence entry; these do not.
NON_FACT_KEYS = frozenset(
    {
        "status",
        "reason",
        "notes",
        "severity",
        "code",
        "detail",
        "remediation_hint",
        "affects",
        "api_source",  # names the probe's own method, like reason/notes
    }
)
TRACEABLE_SECTIONS = ("wp_cli", "wordpress", "abilities", "mcp", "verification_tools")


class CommandRefused(RuntimeError):
    """A probe tried to run a command outside the read-only allowlist."""


def _redact(text: str | None) -> str | None:
    """Strip credentials, salts, application passwords, home paths and
    host-identifying kernel strings. Runs before excerpt truncation, so a
    secret can never be split past a pattern by the 2000-char cut."""
    if text is None:
        return None
    lines = []
    for line in text.split("\n"):
        if APPLICATION_PASSWORD_CUE.search(line) or APPLICATION_PASSWORD_PATTERN.fullmatch(
            line.strip()
        ):
            line = APPLICATION_PASSWORD_PATTERN.sub(REDACTED, line)
        if MYSQL_CUE.search(line):
            line = MYSQL_PASSWORD_FLAG_PATTERN.sub(REDACTED, line)
        lines.append(line)
    scrubbed = "\n".join(lines)
    scrubbed = SECRET_KEY_PATTERN.sub(
        lambda match: match.group(0).replace(match.group("value"), REDACTED), scrubbed
    )
    scrubbed = URL_USERINFO_PATTERN.sub(r"\1" + REDACTED + "@", scrubbed)
    scrubbed = PASSWORD_EQ_PATTERN.sub("--password=" + REDACTED, scrubbed)
    scrubbed = WP_INFO_OS_LINE_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)} {REDACTED}", scrubbed
    )
    scrubbed = HOME_PATH_PATTERN.sub("~", scrubbed)
    return scrubbed


def _redact_argv(argv: list[str]) -> list[str]:
    return [str(_redact(token)) for token in argv]


def _excerpt(text: str | None) -> str | None:
    scrubbed = _redact(text)
    if scrubbed is None:
        return None
    scrubbed = scrubbed.strip()
    if not scrubbed:
        return ""
    return scrubbed[:EXCERPT_LIMIT]


def _wp_argv_split(argv: list[str]) -> tuple[bool, str]:
    """Return (argv reaches WP-CLI, subcommand path after the prefix)."""
    words: list[str] = []
    seen_wp = False
    for token in argv:
        base = Path(token).name
        if not seen_wp:
            if base == "wp" or base.startswith("wp."):
                seen_wp = True
            continue
        if token.startswith("-"):
            # Global flags precede the subcommand; command flags end it.
            if words:
                break
            continue
        if token.startswith("@") and not words:
            continue  # `wp @alias db drop` must still resolve to `db drop`
        words.append(token)
    return seen_wp, " ".join(words)


def _refusal(
    argv: list[str],
    *,
    allow_eval: bool = False,
    eval_exception: bool = False,
) -> str | None:
    """Return why `argv` is refused, or None when it is on the allowlist."""
    is_wp, path = _wp_argv_split(argv)
    if is_wp:
        root = path.split(" ", 1)[0] if path else ""
        if root in EVAL_EXCEPTION_COMMANDS:
            if eval_exception and allow_eval:
                return None
            return f"wp {root} requires --allow-eval"
        if path in READ_ONLY_WP_SUBCOMMANDS or root == HELP_WP_SUBCOMMAND:
            return None
        return f"wp {path} is not on the read-only allowlist"
    if not argv:
        return "empty argv"
    name = Path(argv[0]).name
    permitted = HOST_TOOL_ALLOWLIST.get(name)
    if permitted is not None and tuple(argv[1:]) in permitted:
        return None
    return f"{' '.join([name, *argv[1:]])} is not on the read-only allowlist"


def _kill_process_tree(proc: subprocess.Popen[str]) -> None:
    """Kill a timed-out child and, on POSIX, its whole process group.

    For ddev/lando/wp-env/npx the real work is a grandchild (often a `docker
    exec`) holding the pipes; killing only the direct child leaves it running
    and the pipes open.
    """
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.communicate(timeout=5)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass


class ProbeRunner:
    """Single choke point for every command the probe runs."""

    def __init__(
        self,
        cwd: Path,
        allow_eval: bool,
        budget_seconds: float | None = DEFAULT_BUDGET_SEC,
    ) -> None:
        self.cwd = cwd
        self.allow_eval = allow_eval
        self.evidence: list[dict[str, Any]] = []
        self._deadline = None if budget_seconds is None else time.monotonic() + budget_seconds

    def run(
        self,
        claim: str,
        argv: list[str],
        *,
        timeout: int = DEFAULT_TIMEOUT_SEC,
        eval_exception: bool = False,
    ) -> dict[str, Any]:
        """Run one allowlisted read-only command and record evidence for `claim`."""
        refusal = _refusal(argv, allow_eval=self.allow_eval, eval_exception=eval_exception)
        if refusal is not None:
            raise CommandRefused(refusal)

        started = time.monotonic()
        outcome: dict[str, Any] = {
            "argv": argv,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "ok": False,
            "error": None,
        }
        remaining = None if self._deadline is None else self._deadline - started
        if remaining is not None and remaining <= 0:
            outcome["error"] = "global_budget_exhausted"
        else:
            outcome.update(self._execute(argv, timeout if remaining is None else min(timeout, remaining)))

        duration_ms = int((time.monotonic() - started) * 1000)
        # Output of a command whose argv names a secret key is the bare value:
        # nothing on the line for SECRET_KEY_PATTERN to anchor on, so the whole
        # excerpt is withheld.
        secret_requested = any(token in SECRET_ARGV_TOKENS for token in argv)
        self.evidence.append(
            {
                "claim": claim,
                "argv": _redact_argv(argv),
                "exit_code": outcome["exit_code"],
                "stdout_excerpt": (
                    REDACTED if secret_requested and outcome["stdout"] else _excerpt(outcome["stdout"])
                ),
                "stderr_excerpt": _excerpt(outcome["stderr"] or outcome["error"] or ""),
                "duration_ms": duration_ms,
            }
        )
        return outcome

    def _execute(self, argv: list[str], timeout: float) -> dict[str, Any]:
        """One subprocess, defused: stdin is closed so a prompting command (an
        ssh host-key check, `wp db cli`) cannot read the probe's own stdin;
        ``errors="replace"`` keeps non-UTF-8 output from raising a
        UnicodeDecodeError no handler here catches; a new POSIX session lets a
        timeout kill the whole process group, not just the direct child.
        """
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(self.cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                start_new_session=os.name == "posix",
            )
        except FileNotFoundError:
            return {"error": "executable_not_found"}
        except PermissionError:
            return {"error": "permission_denied"}
        except OSError as exc:  # pragma: no cover - platform dependent
            return {"error": f"os_error:{exc.__class__.__name__}"}
        try:
            stdout, stderr = proc.communicate(timeout=max(1.0, timeout))
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            return {"error": "timeout"}
        return {
            "exit_code": proc.returncode,
            "stdout": stdout or "",
            "stderr": stderr or "",
            "ok": proc.returncode == 0,
        }

    def note_derived(self, claim: str, argv: list[str], value: Any) -> None:
        """Record a fact derived from an already-captured command's output, so
        every fact leaf traces to a claim of its own."""
        self.evidence.append(
            {
                "claim": claim,
                "argv": _redact_argv(argv),
                "exit_code": 0,
                "stdout_excerpt": _excerpt(str(value)),
                "stderr_excerpt": "",
                "duration_ms": 0,
            }
        )

    def note_filesystem(self, claim: str, kind: str, target: str, present: bool) -> None:
        self.evidence.append(
            {
                "claim": claim,
                "argv": ["<filesystem>", kind, str(_redact(target))],
                "exit_code": 0 if present else 1,
                "stdout_excerpt": "present" if present else "absent",
                "stderr_excerpt": "",
                "duration_ms": 0,
            }
        )


# --- Environment detection ---------------------------------------------------

MARKERS: tuple[tuple[int, str, str], ...] = (
    (1, ".ddev/config.yaml", "ddev"),
    (2, ".lando.yml", "lando"),
    (3, ".wp-env.json", "wp-env"),
    (3, ".wp-env.override.json", "wp-env"),
    (4, ".wp-cli.yml", "remote-alias"),
    (4, "wp-cli.local.yml", "remote-alias"),
    (6, "app/public/wp-config.php", "localwp"),
    (7, "wp-config.php", "generic-local"),
)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _wp_env_runtime(root: Path) -> str:
    """Return the configured wp-env runtime.

    If the Playground runtime is configured rather than Docker, `wp-env run`
    does not exist, which means no WP-CLI at all. This is the trap most likely
    to produce a confidently wrong plan. The override file wins outright: an
    override declaring `{"runtime": "docker"}` over a playground base is
    docker, so the loop returns on the first file that declares a runtime
    rather than on the first playground hit.
    """
    for name in (".wp-env.override.json", ".wp-env.json"):
        payload = _read_json(root / name)
        if not payload:
            continue
        runtime = payload.get("runtime")
        env_section = payload.get("env")
        if runtime is None and isinstance(env_section, dict):
            runtime = env_section.get("runtime")
        if isinstance(runtime, str) and runtime.strip():
            return "playground" if runtime.strip().lower() == "playground" else "docker"
        if payload.get("playground"):
            return "playground"
    return "docker"


def _remote_alias(root: Path) -> str | None:
    """Return the first `@alias` in a WP-CLI config that carries an ssh target."""
    for name in (".wp-cli.yml", "wp-cli.local.yml"):
        path = root / name
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        alias: str | None = None
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not line.startswith((" ", "\t")) and line.lstrip().startswith("@"):
                alias = line.split(":", 1)[0].strip()
                continue
            if alias and "ssh:" in line:
                return alias
    return None


def _is_localwp(root: Path) -> bool:
    if not (root / "app" / "public" / "wp-config.php").exists():
        return False
    return "local sites" in str(root).lower() or (root / "conf").is_dir()


def _studio_marker(root: Path) -> str | None:
    """Return the Studio marker that actually matched, not a presumed one."""
    if (root / ".studio").exists():
        return ".studio"
    if (root / "wp-config.php").exists() and (root / ".wp-studio.json").exists():
        return ".wp-studio.json"
    return None


def detect_candidates(runner: ProbeRunner, root: Path) -> list[tuple[int, str, str]]:
    """Return every matching marker, ordered by priority. Ambiguity is signal."""
    found: list[tuple[int, str, str]] = []
    for priority, marker, kind in MARKERS:
        present = (root / marker).exists()
        runner.note_filesystem("environment.marker_file", "exists", marker, present)
        if not present:
            continue
        if kind == "remote-alias" and _remote_alias(root) is None:
            continue
        if kind == "localwp" and not _is_localwp(root):
            continue
        found.append((priority, marker, kind))
    studio_marker = _studio_marker(root)
    runner.note_filesystem(
        "environment.marker_file", "exists", studio_marker or ".studio", studio_marker is not None
    )
    if studio_marker:
        found.append((5, studio_marker, "studio"))
    found.sort(key=lambda item: item[0])
    return found


def invocation_prefix_for(kind: str, root: Path) -> list[str] | None:
    if kind == "ddev":
        return ["ddev", "wp"]
    if kind == "lando":
        return ["lando", "wp"]
    if kind == "wp-env":
        return ["wp-env", "run", "cli", "wp"]
    if kind == "remote-alias":
        alias = _remote_alias(root)
        return ["wp", alias] if alias else None
    if kind == "studio":
        return ["studio", "wp"]
    if kind == "localwp":
        return ["wp", f"--path={root / 'app' / 'public'}"]
    if kind == "generic-local":
        return ["wp", f"--path={root}"]
    return None


# --- Minimal stdlib JSON Schema validation -----------------------------------
# The repo deliberately depends on PyYAML alone, so the manifest is validated by
# a small subset validator rather than by pulling in `jsonschema`.


def _resolve_ref(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return schema
    node: Any = root
    for part in ref[2:].split("/"):
        node = node.get(part, {}) if isinstance(node, dict) else {}
    merged = dict(node) if isinstance(node, dict) else {}
    for key, value in schema.items():
        if key != "$ref":
            merged[key] = value
    return merged


_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
}


def _type_ok(value: Any, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    expected = _TYPE_MAP.get(name)
    return isinstance(value, expected) if expected else True


def validate_against_schema(
    instance: Any,
    schema: dict[str, Any],
    root: dict[str, Any] | None = None,
    path: str = "$",
) -> list[str]:
    """Validate the subset of JSON Schema draft 2020-12 that this manifest uses."""
    root = root if root is not None else schema
    schema = _resolve_ref(schema, root)
    errors: list[str] = []

    declared = schema.get("type")
    if declared is not None:
        names = declared if isinstance(declared, list) else [declared]
        if not any(_type_ok(instance, name) for name in names):
            return [f"{path}: expected type {'|'.join(names)}, got {type(instance).__name__}"]

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: {instance!r} is not const {schema['const']!r}")
    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for index, subschema in enumerate(all_of):
            if isinstance(subschema, dict):
                errors.extend(
                    validate_against_schema(instance, subschema, root, f"{path}(allOf[{index}])")
                )
    if_schema = schema.get("if")
    if isinstance(if_schema, dict):
        branch = "then" if not validate_against_schema(instance, if_schema, root, path) else "else"
        branch_schema = schema.get(branch)
        if isinstance(branch_schema, dict):
            errors.extend(
                validate_against_schema(instance, branch_schema, root, f"{path}({branch})")
            )
    if isinstance(instance, str):
        pattern = schema.get("pattern")
        if pattern and not re.search(pattern, instance):
            errors.append(f"{path}: {instance!r} does not match {pattern}")
        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and len(instance) > max_length:
            errors.append(f"{path}: longer than maxLength {max_length}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and instance < minimum:
            errors.append(f"{path}: below minimum {minimum}")

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required property {key!r}")
        names_schema = schema.get("propertyNames")
        if isinstance(names_schema, dict):
            for key in instance:
                errors.extend(
                    validate_against_schema(key, names_schema, root, f"{path}.{key}(propertyName)")
                )
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            child = f"{path}.{key}"
            if key in properties:
                errors.extend(validate_against_schema(value, properties[key], root, child))
            elif isinstance(additional, dict):
                errors.extend(validate_against_schema(value, additional, root, child))
            elif additional is False:
                errors.append(f"{path}: unexpected property {key!r}")
    if isinstance(instance, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for index, value in enumerate(instance):
                errors.extend(
                    validate_against_schema(value, items, root, f"{path}[{index}]")
                )
    return errors


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# --- Evidence tracing --------------------------------------------------------


def _walk_leaves(node: Any, prefix: str):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk_leaves(value, f"{prefix}.{key}" if prefix else key)
    else:
        yield prefix, node


def evidence_gaps(manifest: dict[str, Any]) -> list[str]:
    """Return claim paths that assert a fact no evidence entry supports.

    Two rules, both from the spec:
      1. Every non-null fact field in a traceable section traces to at least one
         evidence entry via its claim path.
      2. A section reported AVAILABLE must carry evidence. Absence of a failure
         is not a pass.
    """
    claims = {entry.get("claim", "") for entry in manifest.get("evidence", [])}

    def covered(claim_path: str) -> bool:
        """A fact leaf needs a claim of its own, or a dotted ancestor claim.

        A bare section-root claim ("wp_cli") must not bless deep fact leaves:
        that is exactly how is_stable_release once passed with no probe behind
        it. Dotted claims ("verification_tools.phpcs") still cover the leaves
        beneath them, because the entry's excerpt is where those values came
        from.
        """
        return any(
            claim
            and (claim_path == claim or ("." in claim and claim_path.startswith(claim + ".")))
            for claim in claims
        )

    def section_covered(section_path: str) -> bool:
        """A section is evidenced when any claim names it or something beneath it."""
        return any(
            claim and (claim == section_path or claim.startswith(section_path + "."))
            for claim in claims
        )

    gaps: list[str] = []
    for section in TRACEABLE_SECTIONS:
        payload = manifest.get(section)
        if not isinstance(payload, dict):
            continue
        for claim_path, value in _walk_leaves(payload, section):
            leaf = claim_path.rsplit(".", 1)[-1]
            if leaf in NON_FACT_KEYS or value is None or value == [] or value == {}:
                continue
            if not covered(claim_path):
                gaps.append(claim_path)
        if payload.get("status") == "AVAILABLE" and not section_covered(section):
            gaps.append(f"{section}:AVAILABLE-without-evidence")
        for name, child in payload.items():
            if isinstance(child, dict) and child.get("status") == "AVAILABLE":
                if not section_covered(f"{section}.{name}"):
                    gaps.append(f"{section}.{name}:AVAILABLE-without-evidence")
    return sorted(set(gaps))


# --- Parsing helpers ---------------------------------------------------------

VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
# Group 4 is the prerelease suffix: `2.13.0-alpha-6d4736d`, `1.0.0-beta.2`.
VERSION_TOKEN_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?(-[0-9A-Za-z][0-9A-Za-z.\-]*)?")
# Labeled `wp --info` lines. The container's answers live here; the host's
# interpreter is a different runtime entirely for ddev/lando/wp-env.
WP_INFO_PHP_VERSION_RE = re.compile(r"(?im)^PHP version:[ \t]*(\S+)[ \t]*$")
WP_INFO_WP_CLI_VERSION_RE = re.compile(r"(?im)^WP-CLI version:[ \t]*(\S+)[ \t]*$")


def parse_version(text: str | None) -> tuple[int, ...] | None:
    if not text:
        return None
    match = VERSION_RE.search(text)
    if not match:
        return None
    return tuple(int(part) for part in match.groups(default="0"))


def _version_string(text: str | None) -> str | None:
    if not text:
        return None
    match = VERSION_RE.search(text)
    return match.group(0) if match else None


def _version_token(text: str | None) -> str | None:
    """Return the first version token including any prerelease suffix."""
    if not text:
        return None
    match = VERSION_TOKEN_RE.search(text)
    return match.group(0) if match else None


def _is_prerelease_token(token: str) -> bool:
    """A version string is a prerelease iff it carries a suffix. This is a
    probe of the string itself, not a comparison against a frozen constant:
    exact equality with a known-stable version misreports every release that
    ships after the constant was written."""
    match = VERSION_TOKEN_RE.fullmatch(token)
    return bool(match and match.group(4))


def _json_payload(stdout: str) -> Any:
    stripped = (stdout or "").strip()
    if not stripped:
        return None
    start = min((index for index in (stripped.find("["), stripped.find("{")) if index >= 0), default=-1)
    if start < 0:
        return None
    try:
        return json.loads(stripped[start:])
    except ValueError:
        return None


# --- The probe ---------------------------------------------------------------


def _blank_manifest(argv: list[str], allow_eval: bool, cwd: Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "probe_version": PROBE_VERSION,
        "probe_argv": _redact_argv(argv),
        "allow_eval": allow_eval,
        "environment": {
            "status": "UNKNOWN",
            "kind": "UNKNOWN",
            "invocation_prefix": None,
            "marker_file": None,
            "other_markers_present": [],
            "wp_env_runtime": None,
            "remote_alias": None,
            "cwd": str(_redact(str(cwd))),
            "host": {"os": None, "php": None, "node": None, "composer": None},
        },
        "wp_cli": {
            "status": "UNKNOWN",
            "version": None,
            "reason": None,
            "is_stable_release": None,
            "commands": {},
            "notes": [],
        },
        "wordpress": {
            "status": "UNKNOWN",
            "reason": None,
            "core_version": None,
            "php_version": None,
            "is_multisite": None,
            "is_installed": None,
            "siteurl": None,
            "home": None,
            "active_plugins": [],
            "active_themes": [],
            "notes": [],
        },
        "abilities": {
            "status": "UNKNOWN",
            "reason": None,
            "api_present": None,
            "api_source": None,
            "registered_count": None,
            "registered": [],
            "publicly_exposed_count": None,
            "notes": [],
        },
        "mcp": {
            "status": "UNKNOWN",
            "reason": None,
            "adapter": {"present": False, "version": None, "prerelease": None},
            "transports": [],
            "servers": [],
            "tools": [],
            "deprecated_detected": [],
            "notes": [],
        },
        "verification_tools": {},
        "capabilities": {
            "can_run_wp_cli": False,
            "can_read_site_state": False,
            "can_run_static_analysis": False,
            "can_run_plugin_check": False,
            "can_provision_ephemeral_site": False,
            "can_reach_mcp_abilities": False,
            "can_register_abilities": False,
        },
        "blockers": [],
        "evidence": [],
    }


def _add_blocker(
    manifest: dict[str, Any],
    code: str,
    severity: str,
    affects: list[str],
    detail: str,
    remediation_hint: str | None = None,
) -> None:
    manifest["blockers"].append(
        {
            "code": code,
            "severity": severity,
            "affects": affects,
            "detail": detail,
            "remediation_hint": remediation_hint,
        }
    )


def _probe_host(runner: ProbeRunner, manifest: dict[str, Any]) -> None:
    host = manifest["environment"]["host"]
    host["os"] = platform.system().lower() or None
    for key, argv in (
        ("php", ["php", "--version"]),
        ("node", ["node", "--version"]),
        ("composer", ["composer", "--version"]),
    ):
        result = runner.run(f"environment.host.{key}", argv)
        host[key] = _version_string(result["stdout"]) if result["ok"] else None


def _probe_wp_cli(
    runner: ProbeRunner,
    manifest: dict[str, Any],
    prefix: list[str] | None,
) -> dict[str, Any] | None:
    """Probe WP-CLI itself; returns the `--info` outcome for reuse downstream
    (its labeled lines carry the container's PHP version)."""
    wp_cli = manifest["wp_cli"]
    if prefix is None:
        wp_cli["status"] = "UNAVAILABLE"
        wp_cli["reason"] = "no_invocation_prefix_detected"
        return None

    info = runner.run("wp_cli", [*prefix, "--info"])
    if not info["ok"]:
        wp_cli["status"] = "UNAVAILABLE"
        wp_cli["reason"] = "wp_info_failed" if info["error"] is None else info["error"]
        return None

    version_result = runner.run("wp_cli.version", [*prefix, "cli", "version"])
    version_token: str | None = None
    version_argv = [*prefix, "cli", "version"]
    if version_result["ok"]:
        version_token = _version_token(version_result["stdout"])
    if version_token is None:
        # Parse the labeled line, not the whole banner: the first bare version
        # string in `--info` output is usually the kernel's.
        labeled = WP_INFO_WP_CLI_VERSION_RE.search(info["stdout"])
        version_token = _version_token(labeled.group(1)) if labeled else None
        if version_token is not None:
            version_argv = [*prefix, "--info"]
            runner.evidence.append(
                {
                    "claim": "wp_cli.version",
                    "argv": _redact_argv(version_argv),
                    "exit_code": info["exit_code"],
                    "stdout_excerpt": _excerpt(info["stdout"]),
                    "stderr_excerpt": "",
                    "duration_ms": 0,
                }
            )
    version = _version_string(version_token)
    wp_cli["status"] = "AVAILABLE"
    wp_cli["version"] = version
    # Probed from the version string itself: a prerelease suffix means a
    # nightly/alpha build; no suffix means a release. Never an equality check
    # against a frozen "known stable" constant, which misreports every release
    # that ships after the constant was written.
    wp_cli["is_stable_release"] = (
        None if version_token is None else not _is_prerelease_token(version_token)
    )
    if version_token is not None:
        runner.note_derived("wp_cli.is_stable_release", version_argv, version_token)

    parsed = parse_version(version)
    if parsed and parsed[0] >= 3 and WP_CLI_3X_IS_UNVERIFIED:
        wp_cli["notes"].append("wp_cli_3x_unverified")

    for command in ("ability", "block", "doctor", "profile", "plugin", "theme", "option", "post", "core"):
        result = runner.run(f"wp_cli.commands.{command}", [*prefix, "help", command])
        if result["ok"]:
            wp_cli["commands"][command] = {"status": "AVAILABLE", "reason": None}
            continue
        if command in TRUNK_ONLY_WP_CLI_COMMANDS and (parsed is None or parsed[0] < 3):
            reason = "command_documented_but_not_in_stable_phar"
        elif result["error"] is not None:
            reason = result["error"]
        else:
            reason = "package_not_installed"
        wp_cli["commands"][command] = {"status": "UNAVAILABLE", "reason": reason}
    return info


def _probe_wordpress(
    runner: ProbeRunner,
    manifest: dict[str, Any],
    prefix: list[str] | None,
    allow_eval: bool,
    wp_info: dict[str, Any] | None = None,
) -> None:
    wordpress = manifest["wordpress"]
    if manifest["wp_cli"]["status"] != "AVAILABLE" or prefix is None:
        wordpress["status"] = "BLOCKED"
        wordpress["reason"] = "wp_cli_unavailable"
        return

    core = runner.run("wordpress.core_version", [*prefix, "core", "version", "--extra"])
    installed = runner.run("wordpress.is_installed", [*prefix, "core", "is-installed"])
    # Exit 1 with no execution error is WP-CLI's probed "not installed"; a
    # timeout or missing executable is no answer at all, so it stays None
    # rather than conflating "unknown" with "no".
    wordpress["is_installed"] = (
        True if installed["ok"] else False if installed["error"] is None else None
    )
    wordpress["core_version"] = _version_string(core["stdout"]) if core["ok"] else None

    if allow_eval:
        payload_script = (
            'echo json_encode(["php"=>PHP_VERSION,"wp"=>get_bloginfo("version"),'
            '"multisite"=>is_multisite()]);'
        )
        facts_argv = [*prefix, "eval", payload_script]
        facts = runner.run("wordpress.php_version", facts_argv, eval_exception=True)
        payload = _json_payload(facts["stdout"]) if facts["ok"] else None
        if isinstance(payload, dict):
            wordpress["php_version"] = payload.get("php")
            wordpress["core_version"] = payload.get("wp") or wordpress["core_version"]
            wordpress["is_multisite"] = bool(payload.get("multisite"))
            runner.note_derived(
                "wordpress.is_multisite", facts_argv, payload.get("multisite")
            )
            wordpress["notes"].append("facts_from_wp_eval")
    else:
        # The environment's own answer, not the host interpreter's: for
        # ddev/lando/wp-env those are different runtimes, and reporting the
        # host's PHP as WordPress's PHP is a confidently wrong fact.
        labeled = WP_INFO_PHP_VERSION_RE.search((wp_info or {}).get("stdout") or "")
        if labeled:
            wordpress["php_version"] = _version_string(labeled.group(1))
            runner.note_derived(
                "wordpress.php_version", [*prefix, "--info"], labeled.group(0)
            )
        multisite = runner.run(
            "wordpress.is_multisite", [*prefix, "config", "get", "MULTISITE"]
        )
        if multisite["ok"]:
            wordpress["is_multisite"] = multisite["stdout"].strip().lower() in {"1", "true"}
        elif multisite["error"] is None and "not defined" in (multisite["stderr"] or "").lower():
            # `wp config get` exits 1 with "'MULTISITE' is not defined" on a
            # single site; any other failure stays None rather than guessing.
            wordpress["is_multisite"] = False
        wordpress["notes"].append("facts_from_wp_cli_read_probes")

    for field, option in (("siteurl", "siteurl"), ("home", "home")):
        result = runner.run(f"wordpress.{field}", [*prefix, "option", "get", option])
        if result["ok"]:
            wordpress[field] = _redact(result["stdout"].strip()) or None

    plugins = runner.run(
        "wordpress.active_plugins",
        [*prefix, "plugin", "list", "--format=json", "--fields=name,status,version,update"],
    )
    payload = _json_payload(plugins["stdout"]) if plugins["ok"] else None
    if isinstance(payload, list):
        # WP-CLI's field is named `status`; the manifest key is
        # `activation_state` so the free string (active/inactive/must-use/
        # dropin) cannot be confused with the four-value status enum.
        wordpress["active_plugins"] = [
            {
                "name": str(item.get("name", "")),
                "version": item.get("version") or None,
                "activation_state": str(item.get("status", "unknown")),
            }
            for item in payload
            if isinstance(item, dict) and item.get("name")
        ]

    themes = runner.run(
        "wordpress.active_themes",
        [*prefix, "theme", "list", "--format=json", "--fields=name,status,version"],
    )
    payload = _json_payload(themes["stdout"]) if themes["ok"] else None
    if isinstance(payload, list):
        wordpress["active_themes"] = [
            {
                "name": str(item.get("name", "")),
                "version": item.get("version") or None,
                "activation_state": str(item.get("status", "unknown")),
            }
            for item in payload
            if isinstance(item, dict) and item.get("name")
        ]

    if core["ok"] or installed["ok"]:
        wordpress["status"] = "AVAILABLE"
    else:
        wordpress["status"] = "UNKNOWN"
        wordpress["reason"] = "core_probes_inconclusive"


def _probe_abilities(
    runner: ProbeRunner,
    manifest: dict[str, Any],
    prefix: list[str] | None,
    allow_eval: bool,
) -> None:
    abilities = manifest["abilities"]
    if manifest["wp_cli"]["status"] != "AVAILABLE" or prefix is None:
        abilities["status"] = "BLOCKED"
        abilities["reason"] = "wp_cli_unavailable"
        return

    ability_command = manifest["wp_cli"]["commands"].get("ability", {}).get("status")
    if ability_command == "AVAILABLE":
        list_argv = [*prefix, "ability", "list", "--format=json"]
        listed = runner.run("abilities.registered", list_argv)
        payload = _json_payload(listed["stdout"]) if listed["ok"] else None
        if isinstance(payload, list):
            names = [
                str(item.get("name") or item.get("ability") or "")
                for item in payload
                if isinstance(item, dict)
            ]
            abilities["status"] = "AVAILABLE"
            abilities["api_present"] = True
            abilities["api_source"] = "wp-cli-ability-command"
            abilities["registered"] = [name for name in names if name]
            abilities["registered_count"] = len(abilities["registered"])
            abilities["publicly_exposed_count"] = sum(
                1
                for item in payload
                if isinstance(item, dict)
                and str(item.get("mcp_public", item.get("public", ""))).lower() in {"1", "true", "yes"}
            )
            runner.note_derived("abilities.api_present", list_argv, True)
            runner.note_derived(
                "abilities.registered_count", list_argv, abilities["registered_count"]
            )
            runner.note_derived(
                "abilities.publicly_exposed_count", list_argv, abilities["publicly_exposed_count"]
            )
            if abilities["registered_count"] == 0:
                abilities["notes"].append("abilities_api_present_but_surface_empty")
            return

    if allow_eval:
        eval_argv = [*prefix, "eval", 'echo json_encode(function_exists("wp_register_ability"));']
        probe = runner.run("abilities.api_present", eval_argv, eval_exception=True)
        payload = _json_payload(probe["stdout"]) if probe["ok"] else None
        if payload is not None:
            abilities["api_present"] = bool(payload)
            abilities["api_source"] = "eval-function_exists"
            abilities["status"] = "AVAILABLE" if payload else "UNAVAILABLE"
            if payload:
                abilities["notes"].append("abilities_api_present_but_surface_empty")
                abilities["registered_count"] = 0
                abilities["publicly_exposed_count"] = 0
                runner.note_derived("abilities.registered_count", eval_argv, 0)
                runner.note_derived("abilities.publicly_exposed_count", eval_argv, 0)
            return

    abilities["status"] = "UNKNOWN"
    abilities["reason"] = "ability_command_absent_and_eval_disabled"
    core_version = parse_version(manifest["wordpress"].get("core_version"))
    if core_version and core_version[:2] >= (6, 9):
        abilities["notes"].append("abilities_api_inferred_from_core_version")


def _probe_mcp(runner: ProbeRunner, manifest: dict[str, Any]) -> None:
    mcp = manifest["mcp"]
    plugins = manifest["wordpress"].get("active_plugins") or []
    names = {plugin["name"].lower(): plugin for plugin in plugins}
    runner.evidence.append(
        {
            "claim": "mcp.adapter",
            "argv": ["<derived>", "plugin-list-scan", "mcp-adapter"],
            "exit_code": 0,
            "stdout_excerpt": _excerpt(", ".join(sorted(names)) or "no plugin inventory available"),
            "stderr_excerpt": "",
            "duration_ms": 0,
        }
    )
    if manifest["wordpress"]["status"] not in {"AVAILABLE", "UNKNOWN"} or not plugins:
        mcp["status"] = "UNKNOWN" if manifest["wp_cli"]["status"] != "AVAILABLE" else "UNAVAILABLE"
        mcp["reason"] = "plugin_inventory_unavailable" if not plugins else "wordpress_unavailable"
        return

    adapter = next(
        (plugin for name, plugin in names.items() if "mcp-adapter" in name),
        None,
    )
    deprecated = sorted(
        slug for slug in DEPRECATED_TOOLING if any(slug == name or slug in name for name in names)
    )
    if shutil.which("wp-now") is not None and "wp-now" not in deprecated:
        deprecated.append("wp-now")
    mcp["deprecated_detected"] = deprecated
    if deprecated:
        runner.note_derived(
            "mcp.deprecated_detected",
            ["<derived>", "plugin-list-scan"],
            ", ".join(deprecated),
        )
        mcp["notes"].append("deprecated_tooling_detected")

    if adapter is None:
        mcp["status"] = "UNAVAILABLE"
        mcp["reason"] = "mcp_adapter_absent"
        return

    version = adapter.get("version")
    token = _version_token(str(version)) if version else None
    parsed = parse_version(token)
    # None means "no version to judge", never "not a prerelease": asserting
    # prerelease=false from no data is the constants-over-probes failure mode.
    prerelease: bool | None = None
    if token is not None:
        prerelease = _is_prerelease_token(token) or bool(
            parsed and parsed[0] < MCP_ADAPTER_PRERELEASE_CEILING
        )
    mcp["adapter"] = {
        "present": True,
        "version": version,
        "prerelease": prerelease,
    }
    if mcp["adapter"]["prerelease"]:
        mcp["notes"].append("mcp_adapter_prerelease")
    # Exposure is default-deny: an ability needs meta.mcp.public = true, and
    # separately meta.show_in_rest for REST. Presence of the adapter is not
    # reachability, so the status stays UNKNOWN until an exposed tool is seen.
    exposed = manifest["abilities"].get("publicly_exposed_count")
    if exposed:
        mcp["status"] = "AVAILABLE"
    else:
        mcp["status"] = "UNKNOWN"
        mcp["reason"] = "ability_not_publicly_exposed"
        mcp["notes"].append("ability_not_publicly_exposed")


# Anchored on the phrase, not on `split("are")`, which broke on the
# single-standard phrasing ("The only installed coding standard is PEAR") and
# on any standard name containing "are".
PHPCS_STANDARDS_RE = re.compile(r"(?i)installed coding standards?\s+(?:are|is)\s+(.+)")


def _phpcs_standards(stdout: str) -> list[str]:
    match = PHPCS_STANDARDS_RE.search(stdout or "")
    if not match:
        return []
    return [item.strip() for item in re.split(r",\s*|\s+and\s+", match.group(1)) if item.strip()]


def _tool(status: str, **fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "version": None,
        "reason": None,
        "invocation": None,
        "standards": None,
        "runtime": None,
        "wp_stubs_version": None,
        "notes": [],
    }
    payload.update(fields)
    return payload


def _probe_verification_tools(
    runner: ProbeRunner,
    manifest: dict[str, Any],
    root: Path,
    prefix: list[str] | None,
) -> None:
    tools = manifest["verification_tools"]

    phpcs_bin = root / "vendor" / "bin" / "phpcs"
    phpcs_argv = [str(phpcs_bin)] if phpcs_bin.exists() else ["phpcs"]
    phpcs = runner.run("verification_tools.phpcs", [*phpcs_argv, "--version"])
    if phpcs["ok"]:
        standards_result = runner.run("verification_tools.phpcs", [*phpcs_argv, "-i"])
        standards = _phpcs_standards(standards_result["stdout"]) if standards_result["ok"] else []
        tools["phpcs"] = _tool(
            "AVAILABLE",
            version=_version_string(phpcs["stdout"]),
            standards=standards or None,
            invocation=_redact_argv(phpcs_argv),
        )
        wpcs_present = any(standard.startswith("WordPress") for standard in standards)
        runner.evidence.append(
            {
                "claim": "verification_tools.wpcs",
                "argv": [*phpcs_argv, "-i"],
                "exit_code": standards_result["exit_code"],
                "stdout_excerpt": _excerpt(", ".join(standards) or "no standards reported"),
                "stderr_excerpt": "",
                "duration_ms": 0,
            }
        )
        if wpcs_present:
            phpcs_version = parse_version(_version_string(phpcs["stdout"]))
            required = parse_version(WPCS_REQUIRED_PHPCS)
            notes = []
            if phpcs_version and required and phpcs_version < required:
                notes.append("wpcs_phpcs_version_mismatch")
            tools["wpcs"] = _tool("AVAILABLE", notes=notes)
        else:
            tools["wpcs"] = _tool("UNAVAILABLE", reason="wordpress_standard_not_installed")
    else:
        reason = phpcs["error"] or "phpcs_version_failed"
        tools["phpcs"] = _tool("UNAVAILABLE", reason=reason)
        tools["wpcs"] = _tool("BLOCKED", reason="phpcs_unavailable")

    phpstan_bin = root / "vendor" / "bin" / "phpstan"
    phpstan_argv = [str(phpstan_bin)] if phpstan_bin.exists() else ["phpstan"]
    phpstan = runner.run("verification_tools.phpstan", [*phpstan_argv, "--version"])
    if phpstan["ok"]:
        stubs = _wordpress_stubs_version(root)
        notes = []
        core_version = parse_version(manifest["wordpress"].get("core_version"))
        stubs_version = parse_version(stubs) or parse_version(PHPSTAN_WP_STUBS_FLOOR)
        if core_version and stubs_version and core_version[:2] > stubs_version[:2]:
            notes.append("phpstan_stubs_predate_core")
        tools["phpstan"] = _tool(
            "AVAILABLE",
            version=_version_string(phpstan["stdout"]),
            wp_stubs_version=stubs,
            invocation=_redact_argv(phpstan_argv),
            notes=notes,
        )
    else:
        tools["phpstan"] = _tool("UNAVAILABLE", reason=phpstan["error"] or "phpstan_version_failed")

    if prefix is not None and manifest["wp_cli"]["status"] == "AVAILABLE":
        plugin_check = runner.run(
            "verification_tools.plugin_check",
            [*prefix, "plugin", "check", "--help"],
            timeout=PLUGIN_CHECK_TIMEOUT_SEC,
        )
        if plugin_check["ok"]:
            tools["plugin_check"] = _tool(
                "AVAILABLE", invocation=_redact_argv([*prefix, "plugin", "check"])
            )
        else:
            tools["plugin_check"] = _tool(
                "UNAVAILABLE", reason=plugin_check["error"] or "plugin_check_command_absent"
            )
    else:
        tools["plugin_check"] = _tool("BLOCKED", reason="wp_cli_unavailable")

    wp_env = runner.run(
        "verification_tools.wp_env", ["npx", "--no-install", "@wordpress/env", "--version"]
    )
    if wp_env["ok"]:
        runtime = manifest["environment"].get("wp_env_runtime")
        tools["wp_env"] = _tool(
            "AVAILABLE",
            version=_version_string(wp_env["stdout"]),
            runtime=runtime,
            # Present even when wp-env lost the marker race: a plan reaching
            # for `wp-env run` here would find no CLI behind it.
            notes=["wp_env_playground_runtime_has_no_cli"] if runtime == "playground" else [],
        )
    else:
        tools["wp_env"] = _tool("UNAVAILABLE", reason=wp_env["error"] or "wp_env_absent")

    playground = runner.run(
        "verification_tools.playground_cli",
        ["npx", "--no-install", "@wp-playground/cli", "--version"],
    )
    if playground["ok"]:
        # Whether `wp` is reachable inside @wp-playground/cli is unverified as of
        # August 2026. Report the CLI, report UNKNOWN for WP-CLI support, and do
        # not claim either way. Delete this note once upstream documents it.
        tools["playground_cli"] = _tool(
            "AVAILABLE",
            version=_version_string(playground["stdout"]),
            notes=["playground_cli_wp_support_unknown"],
        )
    else:
        tools["playground_cli"] = _tool(
            "UNKNOWN",
            reason=playground["error"] or "playground_cli_absent",
            notes=["playground_cli_wp_support_unknown"],
        )

    tools["phpunit"] = _tool("UNKNOWN", reason="not_probed")


def _wordpress_stubs_version(root: Path) -> str | None:
    lock = root / "composer.lock"
    payload = _read_json(lock)
    if not payload:
        return None
    for package in payload.get("packages", []) + payload.get("packages-dev", []):
        if isinstance(package, dict) and package.get("name") == "php-stubs/wordpress-stubs":
            return _version_string(str(package.get("version", ""))) or None
    return None


def _derive_capabilities(manifest: dict[str, Any]) -> None:
    tools = manifest["verification_tools"]

    def available(section: dict[str, Any] | None) -> bool:
        return bool(section) and section.get("status") == "AVAILABLE"

    capabilities = manifest["capabilities"]
    capabilities["can_run_wp_cli"] = available(manifest["wp_cli"])
    capabilities["can_read_site_state"] = available(manifest["wordpress"]) and bool(
        manifest["wordpress"].get("is_installed")
    )
    capabilities["can_run_static_analysis"] = available(tools.get("phpstan")) or available(
        tools.get("phpcs")
    )
    capabilities["can_run_plugin_check"] = available(tools.get("plugin_check"))
    capabilities["can_provision_ephemeral_site"] = available(tools.get("wp_env")) or available(
        tools.get("playground_cli")
    )
    capabilities["can_reach_mcp_abilities"] = available(manifest["mcp"]) and bool(
        manifest["abilities"].get("publicly_exposed_count")
    )
    capabilities["can_register_abilities"] = available(manifest["abilities"]) and bool(
        manifest["abilities"].get("api_present")
    )


BLOCKER_TEMPLATES: tuple[tuple[str, str, str, str, str | None], ...] = (
    (
        "can_run_wp_cli",
        "wp_cli_unavailable",
        "CRITICAL",
        "No validated WP-CLI invocation prefix; every WP-CLI instruction is unverifiable here.",
        "Start the local environment, or run the probe from the project root (out of scope for the probe - see rec 07).",
    ),
    (
        "can_read_site_state",
        "site_state_unreadable",
        "MAJOR",
        "WordPress is not installed or not reachable, so site state cannot ground a plan.",
        "Install or start the site (out of scope for the probe - see rec 07).",
    ),
    (
        "can_run_static_analysis",
        "static_analysis_unavailable",
        "MAJOR",
        "Neither phpcs nor phpstan answered, so no static verification oracle exists.",
        "composer install (out of scope for the probe - see rec 07).",
    ),
    (
        "can_run_plugin_check",
        "plugin_check_unavailable",
        "MINOR",
        "Plugin Check's WP-CLI command did not answer.",
        "wp plugin install plugin-check (out of scope for the probe - see rec 07).",
    ),
    (
        "can_provision_ephemeral_site",
        "no_ephemeral_runtime",
        "MINOR",
        "Neither @wordpress/env nor @wp-playground/cli answered, so no throwaway site can be provisioned.",
        "npm install @wordpress/env (out of scope for the probe - see rec 07).",
    ),
    (
        "can_reach_mcp_abilities",
        "mcp_adapter_absent",
        "MAJOR",
        "No publicly exposed MCP ability was observed; exposure is default-deny via meta.mcp.public.",
        "composer require wordpress/mcp-adapter (out of scope for the probe - see rec 07).",
    ),
    (
        "can_register_abilities",
        "abilities_api_unconfirmed",
        "MAJOR",
        "The Abilities API was not confirmed present by a probe. Core version alone is an inference, not evidence.",
        "Re-run with --allow-eval, or install wp-cli ability-command (out of scope for the probe - see rec 07).",
    ),
)


def _derive_blockers(manifest: dict[str, Any]) -> None:
    for capability, code, severity, detail, hint in BLOCKER_TEMPLATES:
        if not manifest["capabilities"][capability]:
            _add_blocker(manifest, code, severity, [capability], detail, hint)


def probe(
    root: Path,
    *,
    allow_eval: bool = False,
    allow_remote: bool = False,
    argv: list[str] | None = None,
    budget_seconds: float | None = DEFAULT_BUDGET_SEC,
) -> dict[str, Any]:
    """Run the full probe and return a manifest. Never raises on a bare host."""
    manifest = _blank_manifest(argv or [], allow_eval, root)
    runner = ProbeRunner(root, allow_eval, budget_seconds=budget_seconds)

    candidates = detect_candidates(runner, root)
    environment = manifest["environment"]
    environment["other_markers_present"] = [marker for _, marker, _ in candidates[1:]]

    if any(candidate_kind == "wp-env" for _, _, candidate_kind in candidates):
        # Recorded whenever a wp-env config exists, winning marker or not, so
        # verification_tools.wp_env can carry the playground warning even when
        # ddev or lando is the environment that answers.
        environment["wp_env_runtime"] = _wp_env_runtime(root)

    prefix: list[str] | None = None
    if candidates:
        _, marker, kind = candidates[0]
        environment["marker_file"] = marker
        if kind == "remote-alias":
            environment["remote_alias"] = _remote_alias(root)
        prefix = invocation_prefix_for(kind, root)
    else:
        kind = "UNKNOWN"

    _probe_host(runner, manifest)

    playground_runtime = kind == "wp-env" and environment.get("wp_env_runtime") == "playground"
    if playground_runtime:
        # wp-env with the Playground runtime has no `wp-env run`, which means no
        # WP-CLI at all. Refuse to validate a prefix that cannot exist. Only
        # when wp-env is the winning marker: a losing wp-env config must not
        # block a working ddev or lando CLI.
        manifest["wp_cli"]["status"] = "UNAVAILABLE"
        manifest["wp_cli"]["reason"] = "wp_env_playground_runtime_has_no_cli"
        _add_blocker(
            manifest,
            "wp_env_playground_runtime_has_no_cli",
            "CRITICAL",
            ["can_run_wp_cli"],
            "wp-env is configured with the Playground runtime, which provides no `wp-env run` and therefore no WP-CLI.",
            "Switch the wp-env runtime to docker (out of scope for the probe - see rec 07).",
        )
        environment["status"] = "UNKNOWN"
        environment["kind"] = "UNKNOWN"
        environment["invocation_prefix"] = None
        prefix = None
        wp_info = None
    elif kind == "remote-alias" and prefix is not None and not allow_remote:
        # A checked-in .wp-cli.yml with an ssh alias would make the probe open
        # an outbound SSH connection to a third-party host purely from cloning
        # a repository. Read-only does not extend to dialing out, so remote
        # probing requires an explicit opt-in.
        manifest["wp_cli"]["status"] = "BLOCKED"
        manifest["wp_cli"]["reason"] = "remote_probing_requires_allow_remote"
        _add_blocker(
            manifest,
            "remote_probing_requires_allow_remote",
            "MAJOR",
            ["can_run_wp_cli"],
            f"Marker {marker} carries ssh alias {environment['remote_alias']}; validating it would open an outbound SSH connection.",
            "Re-run with --allow-remote to validate the remote alias over SSH.",
        )
        environment["status"] = "UNKNOWN"
        environment["kind"] = "UNKNOWN"
        environment["invocation_prefix"] = None
        prefix = None
        wp_info = None
    else:
        wp_info = _probe_wp_cli(runner, manifest, prefix)
        if manifest["wp_cli"]["status"] == "AVAILABLE":
            environment["status"] = "AVAILABLE"
            environment["kind"] = kind
            environment["invocation_prefix"] = _redact_argv(prefix) if prefix else prefix
        else:
            # Ground truth is `<prefix> --info`. If it fails, detection is
            # UNKNOWN regardless of which marker matched.
            environment["status"] = "UNKNOWN"
            environment["kind"] = "UNKNOWN"
            environment["invocation_prefix"] = None
            prefix = None
            if candidates:
                _add_blocker(
                    manifest,
                    "marker_matched_but_cli_unreachable",
                    "MAJOR",
                    ["can_run_wp_cli"],
                    f"Marker {marker} matched but the derived prefix did not answer `--info`.",
                    None,
                )

    _probe_wordpress(runner, manifest, prefix, allow_eval, wp_info=wp_info)
    _probe_abilities(runner, manifest, prefix, allow_eval)
    _probe_mcp(runner, manifest)
    _probe_verification_tools(runner, manifest, root, prefix)

    manifest["evidence"] = runner.evidence
    _derive_capabilities(manifest)
    _derive_blockers(manifest)

    gaps = evidence_gaps(manifest)
    if gaps:
        _add_blocker(
            manifest,
            "manifest_self_check_failed",
            "MAJOR",
            [],
            "Fields asserted without evidence: " + ", ".join(gaps),
            "This is a probe bug. Treat the affected fields as UNKNOWN.",
        )
    return manifest


VOLATILE_TOP_LEVEL = ("generated_at",)

# Volatility that live tooling embeds inside evidence excerpts, which a golden
# recorded against a real environment would otherwise never reproduce. Both are
# the same class as duration_ms/generated_at, so they are flattened here for
# golden comparison only - the manifest consumers read keeps its stderr verbatim.
#
#   * wp-env prints a wrapper line to stderr on every `wp-env run`, e.g.
#     `✔ Ran `wp --info` in 'cli'. (in 0s 282ms)`; the elapsed time varies.
#   * npm/npx embed an ISO-8601 timestamp in debug-log paths and messages, e.g.
#     `~/.npm/_logs/2026-08-09T17_32_17_420Z-debug-0.log`.
WP_ENV_RUN_TIMING_RE = re.compile(r"\(in [0-9hms ]+\)")
EMBEDDED_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:_.]+Z")


def normalize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a manifest with volatile fields flattened, for golden comparison.

    Normalises the timestamp, every duration, absolute paths, and the volatile
    timing/timestamp fragments live tooling embeds in stderr, so two probes of
    the same environment produce byte-identical output.
    """
    normalized = json.loads(json.dumps(manifest))

    def scrub(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                key: ("<normalized>" if key == "cwd" else 0 if key == "duration_ms" else scrub(value))
                for key, value in node.items()
            }
        if isinstance(node, list):
            return [scrub(item) for item in node]
        if isinstance(node, str):
            # Absolute paths - and home paths already redacted to `~` at capture
            # time - are location dependent; blank both so the golden does not
            # bake in where it was recorded.
            if node.startswith(("/", "~/", "--path=/", "--path=~/")):
                return "<normalized>"
            scrubbed = WP_ENV_RUN_TIMING_RE.sub("(in <normalized>)", node)
            scrubbed = EMBEDDED_TIMESTAMP_RE.sub("<normalized>", scrubbed)
            return scrubbed
        return node

    # Scrub embedded volatility first, then stamp the top-level sentinels, so the
    # generated_at sentinel is not re-caught by EMBEDDED_TIMESTAMP_RE.
    normalized = scrub(normalized)
    for key in VOLATILE_TOP_LEVEL:
        if key in normalized:
            normalized[key] = "1970-01-01T00:00:00Z"
    normalized["probe_argv"] = [
        "<normalized>" if "/" in token or "\\" in token else token
        for token in normalized.get("probe_argv", [])
    ]
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe a WordPress environment and emit a capability manifest."
    )
    parser.add_argument("--path", default=".", help="Project root to probe.")
    parser.add_argument(
        "--out",
        default=None,
        help=f"Manifest output path (default {DEFAULT_OUT} unless --print is given).",
    )
    parser.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help=(
            "Write the manifest to stdout. Combines with --out: both are honoured; "
            "without --out it suppresses the default file."
        ),
    )
    parser.add_argument(
        "--allow-eval",
        action="store_true",
        help=(
            "Permit `wp eval`, which runs arbitrary PHP in the WordPress context. "
            "Off by default: it is the strongest safety boundary in the WP-CLI surface."
        ),
    )
    parser.add_argument(
        "--budget-seconds",
        type=float,
        default=DEFAULT_BUDGET_SEC,
        help=(
            "Wall-clock budget for all probe commands combined. Once exhausted, "
            "remaining probes are recorded as global_budget_exhausted instead of run."
        ),
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help=(
            "Permit probing a remote-alias environment over SSH. Off by default: "
            "a checked-in .wp-cli.yml must not make a fresh clone dial out to a "
            "third-party host."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]
    args = build_parser().parse_args(raw)
    root = Path(args.path).resolve()
    recorded_argv = [Path(sys.argv[0]).name if sys.argv else "probe_wordpress_environment.py", *raw]

    manifest = probe(
        root,
        allow_eval=args.allow_eval,
        allow_remote=args.allow_remote,
        argv=recorded_argv,
        budget_seconds=args.budget_seconds,
    )

    try:
        errors = validate_against_schema(manifest, load_schema())
    except (OSError, ValueError) as exc:
        errors = [f"schema unavailable: {exc}"]
    if errors:
        _add_blocker(
            manifest,
            "manifest_schema_invalid",
            "MAJOR",
            [],
            "; ".join(errors[:10]),
            "This is a probe bug. Treat every capability as UNKNOWN.",
        )

    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    # --print and --out compose; passing both used to exit 0 having printed
    # nothing and written nothing.
    if args.out is not None or not args.print_only:
        out_path = Path(args.out if args.out is not None else DEFAULT_OUT)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
        sys.stderr.write(f"capability manifest written to {out_path}\n")
    if args.print_only:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
