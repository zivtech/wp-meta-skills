#!/usr/bin/env python3
"""A tiny wp-cli stand-in for testing the localwp-agent-tools-value oracles
and cheat scripts with no live WordPress/MySQL anywhere.

This is test-only infrastructure (not shipped as part of the suite's
production runner) — see evals/harness/tests/test_tool_value_oracle_fixture1.py.
It understands exactly the wp-cli invocations the fixture 1 oracle, seed,
cheat, and reference-fix scripts make, and persists state in a JSON file
next to the site (`<site-root>/.fixture-state.json`) so a real subprocess
call from a bash cheat script (e.g. cheats/deactivate.sh) and an in-process
oracle call observe the same state.

Usage mirrors real wp-cli closely enough for this fixture's needs:
    tool_value_fake_wp.py --path <site-root> plugin is-active <name>
    tool_value_fake_wp.py --path <site-root> plugin deactivate <name>
    tool_value_fake_wp.py --path <site-root> plugin list --format=json
    tool_value_fake_wp.py --path <site-root> post create --post_type=T \
        --post_status=S --post_title="..." --meta_input='{"k":"v"}' --porcelain
    tool_value_fake_wp.py --path <site-root> post delete <id> --force
    tool_value_fake_wp.py --path <site-root> config path
    tool_value_fake_wp.py --path <site-root> config get <NAME> --raw
    tool_value_fake_wp.py --path <site-root> config set <NAME> <VALUE> --raw
    tool_value_fake_wp.py --path <site-root> user create <login> <email> \
        --role=<role> --user_pass=<pass> --porcelain
    tool_value_fake_wp.py --path <site-root> user delete <id> --yes

`config path`/`get`/`set` resolve wp-config.php the way real WP-CLI does —
ABSPATH first, then one directory up (`tool_value_oracle_lib.find_wp_config`)
— which is exactly the parent-dir placement fixture
`wpconfig-in-parent-dir-tools-misreport` exercises, and exactly what the MCP
tool's own naive `path.join(wpPath, 'wp-config.php')` does NOT do.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

import tool_value_oracle_lib as lib  # noqa: E402

STATE_FILENAME = ".fixture-state.json"
DEFAULT_STATE = {
    "plugins": {"acme-events": "active"},
    "next_post_id": 1000,
    "posts": [],
    "users": [],
    "next_user_id": 2,
    "options": {"home": "http://acme.local", "siteurl": "http://acme.local"},
}


def _state_path(site_root: Path) -> Path:
    return site_root / STATE_FILENAME


def load_state(site_root: Path) -> dict:
    path = _state_path(site_root)
    if path.is_file():
        return json.loads(path.read_text())
    return json.loads(json.dumps(DEFAULT_STATE))


def save_state(site_root: Path, state: dict) -> None:
    _state_path(site_root).write_text(json.dumps(state, indent=2))


def _split_options(tokens: list[str]) -> tuple[list[str], dict[str, str], set[str]]:
    positionals: list[str] = []
    options: dict[str, str] = {}
    flags: set[str] = set()
    for token in tokens:
        if token.startswith("--"):
            body = token[2:]
            if "=" in body:
                key, _, value = body.partition("=")
                options[key] = value
            else:
                flags.add(body)
        else:
            positionals.append(token)
    return positionals, options, flags


def main(argv: list[str]) -> int:
    # Accept both wp-cli argument shapes for --path: "--path=X" (one token,
    # the shape src/tools/wpcli.ts appends) and "--path X" (two tokens).
    if not argv:
        print("tool_value_fake_wp: expected --path[=]<site-root> ...", file=sys.stderr)
        return 1
    if argv[0].startswith("--path="):
        site_root = Path(argv[0][len("--path="):])
        rest = argv[1:]
    elif argv[0] == "--path" and len(argv) > 1:
        site_root = Path(argv[1])
        rest = argv[2:]
    else:
        print("tool_value_fake_wp: expected --path[=]<site-root> ...", file=sys.stderr)
        return 1
    if not rest:
        print("tool_value_fake_wp: missing command", file=sys.stderr)
        return 1

    state = load_state(site_root)
    command, subcommand, *tail = (rest + ["", ""])[:2] + rest[2:]
    positionals, options, flags = _split_options(tail)

    if command == "plugin" and subcommand == "is-active":
        name = positionals[0] if positionals else ""
        return 0 if state["plugins"].get(name) == "active" else 1

    if command == "plugin" and subcommand == "deactivate":
        if "all" in flags:
            for existing in state["plugins"]:
                state["plugins"][existing] = "inactive"
            save_state(site_root, state)
            print("All plugins deactivated.")
            return 0
        name = positionals[0] if positionals else ""
        state["plugins"][name] = "inactive"
        save_state(site_root, state)
        print(f"Plugin '{name}' deactivated.")
        return 0

    if command == "plugin" and subcommand == "list":
        rows = [{"name": name, "status": status} for name, status in sorted(state["plugins"].items())]
        print(json.dumps(rows))
        return 0

    if command == "post" and subcommand == "create":
        post_id = state["next_post_id"]
        state["next_post_id"] += 1
        meta = json.loads(options.get("meta_input", "{}"))
        state["posts"].append({
            "id": post_id,
            "post_type": options.get("post_type", "post"),
            "post_status": options.get("post_status", "publish"),
            "title": options.get("post_title", ""),
            "slug": options.get("post_name", ""),
            "meta": meta,
        })
        save_state(site_root, state)
        if "porcelain" in flags:
            print(post_id)
        else:
            print(f"Created post {post_id}.")
        return 0

    if command == "post" and subcommand == "delete":
        post_id = int(positionals[0]) if positionals else None
        state["posts"] = [p for p in state["posts"] if p["id"] != post_id]
        save_state(site_root, state)
        print(f"Deleted post {post_id}.")
        return 0

    if command == "option" and subcommand == "update":
        name = positionals[0] if len(positionals) > 0 else ""
        value = positionals[1] if len(positionals) > 1 else ""
        state.setdefault("options", {})[name] = value
        save_state(site_root, state)
        return 0

    if command == "option" and subcommand == "get":
        name = positionals[0] if positionals else ""
        options = state.get("options", {})
        if name not in options:
            print(f"Error: Could not get '{name}' option.", file=sys.stderr)
            return 1
        print(options[name])
        return 0

    if command == "core" and subcommand == "is-installed":
        return 0

    if command == "config" and subcommand in ("path", "get", "set"):
        return _handle_config(site_root, subcommand, positionals, options, flags)

    if command == "user" and subcommand == "create":
        user_id = state["next_user_id"]
        state["next_user_id"] += 1
        state["users"].append({
            "id": user_id,
            "login": positionals[0] if positionals else "",
            "email": positionals[1] if len(positionals) > 1 else "",
            "role": options.get("role", "subscriber"),
            "password": options.get("user_pass", ""),
        })
        save_state(site_root, state)
        if "porcelain" in flags:
            print(user_id)
        else:
            print(f"Created user {user_id}.")
        return 0

    if command == "user" and subcommand == "delete":
        user_id = int(positionals[0]) if positionals else None
        state["users"] = [u for u in state["users"] if u["id"] != user_id]
        save_state(site_root, state)
        print(f"Deleted user {user_id}.")
        return 0

    print(f"tool_value_fake_wp: unsupported command: {command} {subcommand}", file=sys.stderr)
    return 1


def _wp_path_from_site_root(site_root: Path) -> Path:
    """This fake's --path is always the WordPress root (design's app/public
    equivalent); find_wp_config walks up from there exactly as real WP-CLI
    does."""
    return site_root


def _handle_config(
    site_root: Path, subcommand: str, positionals: list[str], options: dict[str, str], flags: set[str],
) -> int:
    config_path = lib.find_wp_config(_wp_path_from_site_root(site_root))
    if config_path is None:
        print("Error: wp-config.php not found.", file=sys.stderr)
        return 1

    if subcommand == "path":
        print(str(config_path))
        return 0

    source = config_path.read_text()
    constants = lib.parse_define_constants(source)

    if subcommand == "get":
        name = positionals[0] if positionals else ""
        if name not in constants:
            print(f"Error: The '{name}' constant is not defined.", file=sys.stderr)
            return 1
        print(constants[name])
        return 0

    # subcommand == "set"
    name = positionals[0] if len(positionals) > 0 else ""
    value = positionals[1] if len(positionals) > 1 else ""
    literal_value = value if "raw" in flags else f"'{value}'"
    pattern = re.compile(r"define\(\s*['\"]" + re.escape(name) + r"['\"]\s*,\s*[^)]+?\s*\)\s*;")
    replacement = f"define( '{name}', {literal_value} );"
    if pattern.search(source):
        updated = pattern.sub(replacement, source, count=1)
    else:
        marker = "/* That's all, stop editing! Happy publishing. */"
        updated = source.replace(marker, f"{replacement}\n\n{marker}", 1) if marker in source else source + f"\n{replacement}\n"
    config_path.write_text(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
