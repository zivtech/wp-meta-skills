#!/usr/bin/env python3
"""Generation isolation for the WordPress candidate pilot (M4 fix).

v1 generation ran in a temp project dir yet was still contaminated, because
`claude -p` discovers config OUTSIDE the working directory. This module enforces
isolation against the three candidate vectors named in the pre-reg, and exposes a
deliberate-pollution smoke check that PROVES the isolation closes the *confirmed*
vector (necessary-not-sufficient).

Vectors addressed:
  (1) user-level ~/.claude/ discovery independent of cwd  -> scratch HOME
  (2) ambient MCP servers from user/project scope         -> --strict-mcp-config empty
  (3) inherited CLAUDE_*/ANTHROPIC_* config redirects      -> env scrub + scratch XDG

Pure helpers (env + command construction, sentinel detection) are unit-tested.
`run_isolated_generation` and the live smoke test are exercised only by the
operator at Step 3, after the GATE 1 test-critic ACCEPT.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

# Scrub ONLY vars that redirect CONFIG discovery. We deliberately do NOT scrub
# auth credentials: the live pilot showed that prefix-scrubbing every
# CLAUDE_*/ANTHROPIC_* var removed the CLI's auth token, so every isolated
# generation failed "Not logged in" and read as a vacuous "clean" run. Isolation
# must block config discovery WITHOUT breaking authentication.
CONFIG_REDIRECT_VARS = ("CLAUDE_CONFIG_DIR",)
# Auth credentials that must survive isolation (never scrubbed).
AUTH_PRESERVE_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")


def write_empty_mcp_config(scratch_dir: Path) -> Path:
    """Write an empty MCP config so --strict-mcp-config loads no ambient servers."""
    scratch_dir.mkdir(parents=True, exist_ok=True)
    path = scratch_dir / "empty.mcp.json"
    path.write_text(json.dumps({"mcpServers": {}}) + "\n", encoding="utf-8")
    return path


def make_scratch(base: Path) -> dict[str, Path]:
    """Create an empty scratch HOME + XDG_CONFIG_HOME + working dir under `base`.

    The `work` dir is the generation `cwd`: empty, never the repo, so `claude -p`
    cannot discover a repo `CLAUDE.md` or `.claude/` tree (the confirmed v1 vector)."""
    home = base / "home"
    xdg = base / "xdg"
    work = base / "work"
    for d in (home, xdg, work):
        d.mkdir(parents=True, exist_ok=True)
    return {"home": home, "xdg": xdg, "work": work}


def isolated_env(scratch_home: Path, scratch_xdg: Path, base_env: dict | None = None) -> dict:
    """Point config discovery at empty scratch dirs and drop config-redirect vars,
    while PRESERVING auth credentials. Does not mutate the caller's environment."""
    env = dict(os.environ if base_env is None else base_env)
    for key in CONFIG_REDIRECT_VARS:
        env.pop(key, None)
    env["HOME"] = str(scratch_home)
    env["XDG_CONFIG_HOME"] = str(scratch_xdg)
    return env


def seed_credentials(scratch_home: Path, real_home: str | None = None) -> str | None:
    """Copy ONLY the auth credentials file (not CLAUDE.md / settings / agents / MCP)
    from the real ~/.claude into the scratch HOME, so OAuth file-based auth survives
    isolation while config discovery stays blocked. No-op if absent (env-var auth)."""
    rh = Path(real_home or os.path.expanduser("~"))
    src = rh / ".claude" / ".credentials.json"
    if src.exists():
        dst_dir = scratch_home / ".claude"
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst_dir / ".credentials.json")
        return str(dst_dir / ".credentials.json")
    return None


def build_generation_command(model: str, empty_mcp_config: Path) -> list[str]:
    """Non-interactive `claude -p` with strict (empty) MCP config and no tools.

    Deliberately does NOT pass `--agent`: that flag triggers repo `.claude/agents`
    discovery, one of the confirmed v1 contamination vectors. The agent prompt is
    injected as message content instead (see `inject_agent_prompt`)."""
    return [
        "claude", "-p",
        "--model", model,
        "--tools", "",
        "--permission-mode", "bypassPermissions",
        "--strict-mcp-config",
        "--mcp-config", str(empty_mcp_config),
    ]


def inject_agent_prompt(agent_prompt_text: str | None, fixture_prompt: str) -> str:
    """Prepend the agent prompt as message content so the model gets ONLY its own
    prompt + the fixture — no repo discovery. Mirrors what `--agent` would supply,
    but without triggering filesystem config discovery."""
    if not agent_prompt_text:
        return fixture_prompt
    return f"{agent_prompt_text.strip()}\n\n---\n\n{fixture_prompt.strip()}"


def isolation_posture(scratch_home: Path, scratch_xdg: Path, empty_mcp_config: Path,
                      scratch_cwd: Path, credentials_seeded: bool = False) -> dict:
    """Recorded into each output's generation metadata."""
    return {
        "scratch_home": str(scratch_home),
        "scratch_xdg_config_home": str(scratch_xdg),
        "scratch_cwd": str(scratch_cwd),          # never the repo (closes cwd-discovery vector)
        "agent_injection": "content",              # not --agent (avoids .claude/agents discovery)
        "strict_mcp_config": True,
        "empty_mcp_config": str(empty_mcp_config),
        "scrubbed_config_vars": list(CONFIG_REDIRECT_VARS),
        "auth_preserved": True,                    # auth credentials NOT scrubbed
        "credentials_seeded": credentials_seeded,  # ~/.claude/.credentials.json copied if present
        "non_interactive": True,
    }


def output_contains_sentinel(output: str, sentinel: str) -> bool:
    """Smoke-test predicate: did the planted sentinel leak into generation output?"""
    return sentinel in (output or "")


# --------------------------------------------------------------------------- #
# Live operations — operator-only (Step 3); not run during build/verify.
# --------------------------------------------------------------------------- #

def run_isolated_generation(prompt, model, base, *, agent_prompt_text=None, timeout_sec=600):  # pragma: no cover
    scratch = make_scratch(base)
    empty = write_empty_mcp_config(scratch["xdg"])
    real_home = os.environ.get("HOME")
    seeded = seed_credentials(scratch["home"], real_home) is not None
    env = isolated_env(scratch["home"], scratch["xdg"])
    cmd = build_generation_command(model, empty)
    full_prompt = inject_agent_prompt(agent_prompt_text, prompt)
    proc = subprocess.run(
        cmd, input=full_prompt, text=True, capture_output=True,
        timeout=timeout_sec, check=False, env=env,
        cwd=str(scratch["work"]),  # scratch cwd, never the repo
    )
    return proc.stdout or "", proc.stderr or "", proc.returncode, isolation_posture(
        scratch["home"], scratch["xdg"], empty, scratch["work"], credentials_seeded=seeded)
