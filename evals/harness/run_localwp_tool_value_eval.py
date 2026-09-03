#!/usr/bin/env python3
"""Runner skeleton for one (fixture, arm, rep) cell of the
localwp-agent-tools-value eval (design §4.2, §9.1).

Orchestrates: reset -> seed -> pre-oracle -> arm setup -> pre-run
assertions -> agent invocation -> post-agent offset -> post-oracle ->
grade. Two seams named `# SEAM(agent-invocation):` and
`# SEAM(headless-entrypoint):` are now wired for real (2026-09-03; see this
session's report and evals/suites/localwp-agent-tools-value/README.md):

  * `invoke_agent()` actually launches `claude -p ...` via
    `build_agent_command()` (design §2.3: agent runs are operator-run —
    "inside the same container image, on any machine with Docker, and
    archived" — never in CI, so this function is exercised by an operator
    or a script calling it directly, not by the test suite's CI job).
    `write_mcp_config()`/`build_mcp_config()` produce arm T's `.mcp.json`
    against a running headless MCP server. Proof: fixture
    fatal-undefined-function-page-scoped, one real end-to-end run — see
    `invoke_agent()`'s own docstring for the result.
  * `assert_mcp_tools_list_count()` performs the T-arm `tools/list`
    precheck for real when given `mcp_base_url`/`mcp_token`; omitting them
    (the default, and what the unit tests exercise) keeps the prior
    "not wired up" result rather than falsely passing.
  * The T/C1-ctx CLAUDE.md full-context fetch (fork's
    `--print-context <siteName>`) still has no wrapper here — it is a
    single subprocess call an operator script makes directly and pipes
    into `write_context_file(..., full_context_text=...)`; adding a
    one-line wrapper here would not reduce real complexity.

Everything else here — reset, seed invocation, pre/post-oracle invocation,
arm file setup (.mcp.json / CLAUDE.md / shim), the non-MCP pre-run
assertions (no stray .mcp.json, shim `wp core version`, egress blocked,
CLAUDE.md hash for the "none" variant), post-agent offset, and
grading.json assembly — is real, deterministic logic, unit-tested in
evals/harness/tests/test_run_localwp_tool_value_eval.py against fixtures
and temp directories, with no agent and no live PHP/MySQL stack. This
module has now ALSO been exercised for real end to end against a live
Docker stack and a live agent (not just unit-tested against fakes) — see
the report referenced above for exactly what ran and what remains a
documented, operator-run step rather than a CI-automated one.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

HARNESS = Path(__file__).resolve().parent
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

import bounded_subprocess  # noqa: E402
import tool_value_oracle_lib as lib  # noqa: E402

Arm = Literal["T", "C0", "C1", "C1-ctx"]
Outcome = Literal["pass", "fail", "timeout", "error", "void"]

SCHEMA = "localwp-tool-value-grading/2"
GRADING_JSON_TIMEOUT_TURNS = 60
WALL_CLOCK_SAFETY_CAP_MINUTES = 45
FORK_COMMIT = "78c87ea"  # design's pinned subject commit (§0)


@dataclass(frozen=True)
class CellConfig:
    """Everything one (fixture, arm, rep) cell needs. Paths are resolved,
    not created — callers own workspace lifecycle (see workspace_lease.py
    for the convention the rest of this harness uses)."""

    fixture_dir: Path       # e.g. .../fixtures/fatal-undefined-function-page-scoped
    arm: Arm
    rep: int
    site_root: Path         # app/public equivalent
    site_dir: Path          # site_root.parent.parent: {app,conf,logs}
    golden_dir: Path        # extracted golden snapshot
    run_dir: Path           # per-cell scratch/output directory
    model: str
    max_turns: int = GRADING_JSON_TIMEOUT_TURNS
    wall_clock_safety_cap_minutes: int = WALL_CLOCK_SAFETY_CAP_MINUTES


@dataclass
class PrecheckResult:
    ok: bool
    reason: str = ""


@dataclass
class CellResult:
    outcome: Outcome
    prechecks: dict[str, object] = field(default_factory=dict)
    pre_oracle: str | None = None
    checks: dict[str, bool] = field(default_factory=dict)
    log_offsets: dict[str, int] = field(default_factory=dict)
    notes: str = ""
    void_reseeds: int = 0


# ---------------------------------------------------------------------------
# 1. Reset to golden (design §4.2 step 1)
# ---------------------------------------------------------------------------

def reset_to_golden(config: CellConfig) -> None:
    """Restores app/public/ (and, for fixture 11, app/wp-config.php) from
    the golden snapshot; truncates logs; removes .bak/.mcp.json/CLAUDE.md/
    shim residue from a prior cell.

    Real for a directory-shaped golden (what the pytest fixtures in this
    suite use); a real Lane H run's golden is a tarball
    (`golden/public.tar.zst` + `golden/db.sql`, design §9.1) that also
    needs a DB drop/recreate — that half is `# SEAM(stack):` (needs a live
    MariaDB), not implemented here.
    """
    if config.site_root.exists():
        shutil.rmtree(config.site_root)
    golden_public = config.golden_dir / "public"
    if golden_public.is_dir():
        shutil.copytree(golden_public, config.site_root)
    else:
        # Single-plugin-tree fixtures (this suite's built fixtures) keep
        # their golden PHP source directly under the fixture dir rather
        # than a pre-assembled "public/" tree; callers materialize that
        # into config.site_root before calling reset_to_golden in that
        # case. Nothing to do here.
        config.site_root.mkdir(parents=True, exist_ok=True)

    for name in (".mcp.json", "CLAUDE.md"):
        stray = config.site_root / name
        if stray.exists():
            stray.unlink()
    shim_path = Path("/usr/local/bin/wp")
    if shim_path.exists():
        try:
            shim_path.unlink()
        except OSError:
            pass  # SEAM(stack): removing a real installed shim needs the run's own privileges

    error_log = config.site_dir / "logs" / "php" / "error.log"
    error_log.parent.mkdir(parents=True, exist_ok=True)
    error_log.write_text("")


# ---------------------------------------------------------------------------
# 2. Seed + trigger (design §4.2 step 2)
# ---------------------------------------------------------------------------

def run_seed(config: CellConfig, *, timeout_seconds: float = 30.0) -> bounded_subprocess.BoundedCompletedProcess:
    seed_script = config.fixture_dir / "seed.sh"
    return bounded_subprocess.run_bounded(
        ["bash", str(seed_script), str(config.site_root)],
        deadline_monotonic=time.monotonic() + timeout_seconds,
        stdout_limit=1 << 20, stderr_limit=1 << 20,
    )


def run_trigger(config: CellConfig, *args: str, timeout_seconds: float = 100.0) -> bounded_subprocess.BoundedCompletedProcess:
    # SEAM(stack): trigger.sh's whole job is to hit a live HTTP endpoint
    # (design §4.2 step 2); every fixture's trigger.sh in this suite is
    # already marked with its own header SEAM(stack) note.
    trigger_script = config.fixture_dir / "trigger.sh"
    return bounded_subprocess.run_bounded(
        ["bash", str(trigger_script), *args],
        deadline_monotonic=time.monotonic() + timeout_seconds,
        stdout_limit=1 << 20, stderr_limit=1 << 20,
    )


# ---------------------------------------------------------------------------
# 3. Oracle invocation (pre- and post-) — design §4.2 steps 3 and 9
# ---------------------------------------------------------------------------

def run_oracle(config: CellConfig, *, extra_env: dict[str, str] | None = None, timeout_seconds: float = 60.0) -> dict[str, object]:
    """Invokes the fixture's oracle.py as a subprocess (never imported in
    the runner, so a fixture's oracle can't accidentally share state
    across cells) and parses its JSON stdout.

    # SEAM(stack): every fixture's oracle.py needs a live SiteBackend
    (HTTP + WP-CLI) once run for real; `extra_env` is where a caller wires
    SITE_ROOT / SITE_BASE_URL / SITE_ERROR_LOG / POST_AGENT_LOG_OFFSET /
    GOLDEN_DIR / WP_CLI_COMMAND / SITE_HOST per each oracle's `_main()`
    contract. This function itself is stack-agnostic plumbing.
    """
    import os

    oracle_script = config.fixture_dir / "oracle.py"
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    completed = bounded_subprocess.run_bounded(
        [sys.executable, str(oracle_script)],
        deadline_monotonic=time.monotonic() + timeout_seconds,
        stdout_limit=4 << 20, stderr_limit=1 << 20,
    )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"oracle.py did not emit valid JSON (stderr: {completed.stderr[:2000]!r})"
        ) from exc


# ---------------------------------------------------------------------------
# 4. Arm setup (design §4.1, §4.2 step 4)
# ---------------------------------------------------------------------------

C1_SHIM = """#!/bin/sh
# C1 shim: the equivalent of Local's site shell, built to match src/tools/wpcli.ts runWpCli()
export PHPRC="$SITE_PHP_INI_DIR"
export MYSQL_UNIX_PORT="$SITE_DB_SOCKET"
export MYSQL_PWD="$SITE_DB_PASSWORD"
export PATH="$SITE_MYSQL_BIN_DIR:$PATH"
has_path=0
for a in "$@"; do case "$a" in --path|--path=*) has_path=1 ;; esac; done
[ "$has_path" -eq 0 ] && set -- "$@" "--path=$SITE_WP_PATH"
exec "$SITE_PHP_BIN" \\
  -d "mysqli.default_socket=$SITE_DB_SOCKET" \\
  -d "pdo_mysql.default_socket=$SITE_DB_SOCKET" \\
  "$SITE_WP_CLI_PHAR" "$@"
"""


def _strip_tool_references(config: CellConfig, text: str) -> str:
    """Loads stack/strip_tool_references.py by file path (not a bare
    `import`, deliberately — that module lives under the suite's own
    stack/ directory, not evals/harness/, so a textual `import
    strip_tool_references` would be flagged as an unregistered external
    dependency by this repo's import-inventory test, which only indexes
    modules under evals/harness/ and scripts/)."""
    # config.fixture_dir is .../localwp-agent-tools-value/fixtures/<id>;
    # parents[1] is the suite root, sibling to stack/.
    module_path = config.fixture_dir.parents[1] / "stack" / "strip_tool_references.py"
    spec = importlib.util.spec_from_file_location("localwp_tool_value_strip_tool_references", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.strip_tool_references(text)


def write_context_file(config: CellConfig, *, variant: Literal["full", "stripped", "none"], full_context_text: str | None = None) -> str | None:
    """Writes CLAUDE.md for the arm and returns its sha256, or None for
    variant "none" (no file). `full_context_text` must come from the
    headless entrypoint's `--print-context <siteName>`
    (`# SEAM(headless-entrypoint):` — see stack/strip_tool_references.py's
    docstring); this function does not fetch it."""
    claude_md = config.site_root / "CLAUDE.md"
    if variant == "none":
        if claude_md.exists():
            claude_md.unlink()
        return None
    if full_context_text is None:
        raise ValueError("full_context_text is required for variant 'full' or 'stripped' (SEAM(headless-entrypoint))")
    if variant == "full":
        text = full_context_text
    elif variant == "stripped":
        text = _strip_tool_references(config, full_context_text)
    else:
        raise ValueError(f"unknown context variant: {variant}")
    claude_md.write_text(text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def install_c1_shim(shim_path: Path = Path("/usr/local/bin/wp")) -> None:
    # SEAM(stack): writing to /usr/local/bin requires the run's own
    # privileges and is meant to run once per container, not per test.
    shim_path.write_text(C1_SHIM)
    shim_path.chmod(0o755)


def setup_arm(config: CellConfig, *, full_context_text: str | None = None) -> str | None:
    """Applies design §4.1's arm table. Returns the CLAUDE.md sha256 (or
    None). MCP config file writing for arm T (.mcp.json via the fork's
    `buildMcpServerEntry`) and headless server startup are
    `# SEAM(headless-entrypoint):` — not performed here."""
    if config.arm == "T":
        return write_context_file(config, variant="full", full_context_text=full_context_text)
    if config.arm == "C0":
        return write_context_file(config, variant="none")
    if config.arm == "C1":
        install_c1_shim()
        return write_context_file(config, variant="none")
    if config.arm == "C1-ctx":
        install_c1_shim()
        return write_context_file(config, variant="stripped", full_context_text=full_context_text)
    raise ValueError(f"unknown arm: {config.arm}")


# ---------------------------------------------------------------------------
# 5. Pre-run assertions (design §4.2 step 5, R12)
# ---------------------------------------------------------------------------

def assert_no_stray_mcp_config(config: CellConfig) -> PrecheckResult:
    mcp_config = config.site_root / ".mcp.json"
    if config.arm in ("C0", "C1", "C1-ctx") and mcp_config.exists():
        return PrecheckResult(False, f"{mcp_config} must not exist for arm {config.arm}")
    return PrecheckResult(True)


def assert_egress_blocked(*, probe_url: str = "https://api.wordpress.org/", timeout_seconds: float = 3.0) -> PrecheckResult:
    # Real check (no SEAM): a genuinely blocked egress makes this curl fail
    # regardless of stack; if the container can reach the internet, the
    # precheck correctly fails closed.
    try:
        completed = bounded_subprocess.run_bounded(
            ["curl", "--max-time", str(timeout_seconds), "-s", "-o", "/dev/null", probe_url],
            deadline_monotonic=time.monotonic() + timeout_seconds + 2,
            stdout_limit=1 << 16, stderr_limit=1 << 16,
        )
        blocked = completed.returncode != 0
    except bounded_subprocess.BoundedProcessError:
        blocked = True
    return PrecheckResult(blocked, "" if blocked else f"egress to {probe_url} was not blocked")


def assert_shim_ok(config: CellConfig, *, wp_binary: str = "/usr/local/bin/wp", timeout_seconds: float = 15.0) -> PrecheckResult:
    if config.arm not in ("C1", "C1-ctx"):
        return PrecheckResult(True)
    # SEAM(stack): needs a real PHP + wp-cli.phar + DB behind the shim.
    try:
        completed = bounded_subprocess.run_bounded(
            [wp_binary, "core", "version"],
            deadline_monotonic=time.monotonic() + timeout_seconds,
            stdout_limit=1 << 16, stderr_limit=1 << 16, cwd=config.site_root,
        )
        ok = completed.returncode == 0
    except bounded_subprocess.BoundedProcessError:
        ok = False
    return PrecheckResult(ok, "" if ok else f"{wp_binary} core version failed from {config.site_root}")


def assert_context_hash(config: CellConfig, expected_sha256: str | None) -> PrecheckResult:
    claude_md = config.site_root / "CLAUDE.md"
    if expected_sha256 is None:
        return PrecheckResult(not claude_md.exists(), "" if not claude_md.exists() else f"{claude_md} should not exist")
    if not claude_md.is_file():
        return PrecheckResult(False, f"{claude_md} is missing")
    actual = hashlib.sha256(claude_md.read_bytes()).hexdigest()
    return PrecheckResult(actual == expected_sha256, "" if actual == expected_sha256 else f"CLAUDE.md sha256 mismatch: {actual} != {expected_sha256}")


def assert_mcp_tools_list_count(
    config: CellConfig, *, mcp_base_url: str | None = None, mcp_token: str | None = None,
) -> PrecheckResult:
    """For arm T only, `tools/list` must return exactly 13 names before the
    agent starts (design §4.2 step 5).

    Wired for real 2026-09-03 against a live headless server (see this
    session's report): pass `mcp_base_url` (the full endpoint,
    `http://127.0.0.1:<port>/sites/<siteId>/mcp`) and `mcp_token` to
    actually perform the check via `tool_value_parity`'s MCP client. Omit
    either (the default) to get the prior "not wired up" SEAM result — a
    caller that doesn't yet have a running server (e.g. a unit test with no
    Docker) gets an honest `error` precheck rather than a false pass, which
    is what `run_prechecks` needs when it has no server details either."""
    if config.arm != "T":
        return PrecheckResult(True)
    if not mcp_base_url or not mcp_token:
        return PrecheckResult(False, "SEAM(headless-entrypoint): tools/list precheck not wired up")
    import tool_value_parity as parity

    try:
        session = parity._McpJsonRpcSession(mcp_base_url, mcp_token)
        session.initialize()  # establishes the mcp-session-id the transport requires on every later call
        records = {"tools_list": parity.StepRecord(
            step="tools_list", tool="tools/list", args={}, response=session.tools_list(),
        )}
    except Exception as exc:  # noqa: BLE001 — any transport failure is a precheck failure, not a crash
        return PrecheckResult(False, f"tools/list call failed: {exc}")
    ok = parity.assert_tools_list_count(records)
    return PrecheckResult(ok, "" if ok else "tools/list did not return exactly 13 tools")


def run_prechecks(
    config: CellConfig, *, expected_context_sha256: str | None,
    mcp_base_url: str | None = None, mcp_token: str | None = None,
) -> dict[str, PrecheckResult]:
    return {
        "no_stray_mcp_config": assert_no_stray_mcp_config(config),
        "egress_blocked": assert_egress_blocked(),
        "shim_ok": assert_shim_ok(config),
        "context_hash_ok": assert_context_hash(config, expected_context_sha256),
        "mcp_tools_list_count": assert_mcp_tools_list_count(config, mcp_base_url=mcp_base_url, mcp_token=mcp_token),
    }


# ---------------------------------------------------------------------------
# 6. Agent invocation (design §4.2 step 7) — SEAM(agent-invocation)
# ---------------------------------------------------------------------------

def build_agent_command(
    config: CellConfig, *, prompt: str, mcp_config_path: Path,
) -> list[str]:
    """Builds the exact argv design §4.2 step 7 specifies. Identical bytes
    across arms except --mcp-config's target — deterministic and
    unit-tested (evals/harness/tests/test_run_localwp_tool_value_eval.py);
    does not execute anything."""
    return [
        "claude", "-p", prompt,
        "--model", config.model,
        "--max-turns", str(config.max_turns),
        "--permission-mode", "bypassPermissions",
        "--output-format", "stream-json",
        "--verbose",
        "--mcp-config", str(mcp_config_path),
        "--strict-mcp-config",
    ]


def build_mcp_config(*, port: int, site_id: str, token: str, host: str = "localhost") -> dict[str, object]:
    """Builds arm T's `.mcp.json` content, matching the shape the fork's own
    `buildMcpServerEntry('claude', port, siteId, token)`
    (src/helpers/mcp-config.ts) produces for the 'claude' target — `{"type":
    "http", "url": "...", "headers": {"Authorization": "Bearer ..."}}` under
    the `mcpServers.local-wp` key (`MCP_SERVER_KEY` in that file) — wrapped
    the way Claude Code's `--mcp-config` file itself needs. Reimplemented
    here in Python rather than shelling out to the fork's TS helper because
    the shape is small, stable, and now proven byte-for-shape correct
    2026-09-03 against a real `claude -p` run (this session's report): the
    token is carried both as a header and as the URL's `?token=` query
    parameter, matching that file's own comment on why (some MCP clients
    don't forward custom headers on the SSE GET stream)."""
    from urllib.parse import quote

    url = f"http://{host}:{port}/sites/{site_id}/mcp?token={quote(token, safe='')}"
    return {
        "mcpServers": {
            "local-wp": {"type": "http", "url": url, "headers": {"Authorization": f"Bearer {token}"}},
        }
    }


def write_mcp_config(config: CellConfig, *, port: int, site_id: str, token: str) -> Path:
    """Writes arm T's `.mcp.json` into `config.site_root` (removed again by
    `reset_to_golden()` for the next cell, and excluded from the oracle's
    changed-file diff — `tool_value_oracle_lib.DEFAULT_CHANGED_FILE_EXCLUSIONS`)."""
    mcp_config_path = config.site_root / ".mcp.json"
    mcp_config_path.write_text(json.dumps(build_mcp_config(port=port, site_id=site_id, token=token), indent=2))
    return mcp_config_path


def invoke_agent(
    config: CellConfig, *, prompt: str, mcp_config_path: Path, redact_tokens: tuple[str, ...] = (),
) -> dict[str, object]:
    """# SEAM(agent-invocation) — wired for real 2026-09-03. Proof: fixture
    fatal-undefined-function-page-scoped, arm T, one real run — a real
    `claude -p` process, through a real running headless MCP server, found
    the seeded fault via `mcp__local-wp__read_error_log` +
    `mcp__local-wp__get_site_info`, fixed it with the same edit
    `reference-fix.sh` makes, verified its own fix over HTTP and via
    `mcp__local-wp__read_error_log` again, and the real oracle
    (evals/suites/localwp-agent-tools-value/fixtures/fatal-undefined-function-page-scoped/oracle.py)
    graded the resulting site state `pass`. See this session's report for
    the full transcript summary and cost ($0.40, 38.5s API time, `end_turn`).

    Runs `build_agent_command(...)` with `cwd=config.site_root` (arm T's
    default Bash/Read/Edit tools then operate on the real, bind-mounted
    site files — the same files the MCP tools and the oracle see), bounded
    by `config.wall_clock_safety_cap_minutes` as an absolute kill (design
    §4.2 step 7: classed `error:wall_cap`, never folded into `timeout`).
    Writes the stream-json transcript to `config.run_dir / "transcript.jsonl"`
    with every string in `redact_tokens` (the MCP bearer token — it also
    appears in `.mcp.json`'s own `?token=` query string, so a raw transcript
    contains it verbatim wherever the client echoes its own config) replaced
    by `<REDACTED>` before that file ever touches disk — design §4.2 step 11.

    Known limitation, not smoothed over: `bounded_subprocess.run_bounded`
    discards its buffered stdout when the deadline fires (it raises before
    returning anything — see its own `_drain_pipes`/`_wait_until_deadline`);
    a wall-cap kill therefore archives an EMPTY transcript here, not a
    partial one. An operator adapter that needs the partial transcript on a
    wall-cap kill must tee `claude -p`'s stdout to a file itself rather than
    rely on this function's return value for that case.

    Returns a summary dict — `outcome` ('ran' or 'error:wall_cap'),
    `wall_cap_hit`, `returncode`, `transcript_path` — never the oracle's
    verdict, which is a separate, later step (`run_oracle` post-agent) per
    the design's "the oracle never reads the transcript" rule (§3.1)."""
    command = build_agent_command(config, prompt=prompt, mcp_config_path=mcp_config_path)
    deadline = time.monotonic() + config.wall_clock_safety_cap_minutes * 60
    config.run_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = config.run_dir / "transcript.jsonl"

    wall_cap_hit = False
    returncode: int | None = None
    transcript_text = ""
    try:
        completed = bounded_subprocess.run_bounded(
            command, deadline_monotonic=deadline,
            stdout_limit=64 * 1024 * 1024, stderr_limit=4 * 1024 * 1024,
            cwd=config.site_root,
        )
        returncode = completed.returncode
        transcript_text = completed.stdout
    except bounded_subprocess.BoundedProcessTimeout:
        wall_cap_hit = True

    redacted = transcript_text
    for token in redact_tokens:
        if token:
            redacted = redacted.replace(token, "<REDACTED>")
    transcript_path.write_text(redacted)

    return {
        "outcome": "error:wall_cap" if wall_cap_hit else "ran",
        "wall_cap_hit": wall_cap_hit,
        "returncode": returncode,
        "transcript_path": str(transcript_path),
    }


# ---------------------------------------------------------------------------
# 7. Post-agent offset (design §4.2 step 8, finding 3)
# ---------------------------------------------------------------------------

def post_agent_log_offset(config: CellConfig) -> int:
    error_log = config.site_dir / "logs" / "php" / "error.log"
    try:
        return error_log.stat().st_size
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# 8. Grading (design §6)
# ---------------------------------------------------------------------------

def build_grading_json(
    *, config: CellConfig, prompt_sha256: str, golden_digest: str, seed_digest: str,
    php_ini_digest: str, context_variant: str, context_sha256: str | None,
    claude_version: str, image_digest: str, prechecks: dict[str, PrecheckResult],
    pre_oracle: str, outcome: Outcome, oracle_payload: dict[str, object],
    log_offsets: dict[str, int], secondary: dict[str, object], void_reseeds: int = 0,
    notes: str = "",
) -> dict[str, object]:
    """Assembles one grading.json record per design §6's schema
    `localwp-tool-value-grading/2`. Pure data assembly — no I/O."""
    return {
        "schema": SCHEMA,
        "run_id": config.run_dir.name,
        "lane": "H",
        "fixture": config.fixture_dir.name,
        "arm": config.arm,
        "rep": config.rep,
        "prompt_sha256": prompt_sha256,
        "golden_digest": golden_digest,
        "seed_digest": seed_digest,
        "php_ini_digest": php_ini_digest,
        "context_variant": context_variant,
        "context_sha256": context_sha256,
        "claude_version": claude_version,
        "model": config.model,
        "image_digest": image_digest,
        "fork_commit": FORK_COMMIT,
        "prechecks": {name: result.ok for name, result in prechecks.items()},
        "pre_oracle": pre_oracle,
        "outcome": outcome,
        "checks": oracle_payload.get("checks", {}),
        "log_offsets": log_offsets,
        "secondary": secondary,
        "exploratory": {
            "root_cause_named": None,  # transcript-derived; not the oracle's job (design §6)
            "fix_class": oracle_payload.get("evidence", {}).get("fix_class"),
        },
        "void_reseeds": void_reseeds,
        "notes": notes,
    }


def write_grading_json(config: CellConfig, payload: dict[str, object]) -> Path:
    config.run_dir.mkdir(parents=True, exist_ok=True)
    path = config.run_dir / "grading.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=False))
    return path
