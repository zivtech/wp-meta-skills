#!/usr/bin/env python3
"""Verify the tranche-J tool-invisibility entry criterion for the critic corpus.

A tranche-J fixture claims its defect is a JUDGMENT defect no static tool can see. This
script extracts the PHP from each J fixture's `.md`, runs WPCS (WordPress standard), and
asserts that NO security/performance sniff fires — the sniffs whose firing would mean the
defect is tool-CATCHABLE and the fixture belongs in tranche T instead. General style
warnings (docblocks, yoda, spacing) on a bare snippet are expected and ignored.

It reads each fixture's `.provenance.yaml` sidecar to find tranche J fixtures, so clean
(tranche C) fixtures — which are DESIGNED to trip a linter as bait — are correctly skipped.

Requires the pinned PHPCS/WPCS stack in `evals/harness/php-tools/vendor` (run
`composer install` there first). Records nothing; it is a verification gate, and its output
is the evidence referenced by each J sidecar's `tool_invisibility` block.

Usage:
  python3 evals/harness/verify_critic_tool_invisibility.py            # all suites
  python3 evals/harness/verify_critic_tool_invisibility.py --suite wordpress-security-critic
Exit code 0 iff every tranche-J fixture is tool-invisible.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit(f"PyYAML required: {exc}") from exc

ROOT = Path(__file__).resolve().parents[2]
SUITES_ROOT = ROOT / "evals" / "suites"
PHP_TOOLS = ROOT / "evals" / "harness" / "php-tools"
INSTALLED_PATHS = ",".join([
    "vendor/wp-coding-standards/wpcs",
    "vendor/phpcsstandards/phpcsutils",
    "vendor/phpcsstandards/phpcsextra",
])
CRITIC_SUITES = (
    "wordpress-critic", "wordpress-security-critic",
    "wordpress-performance-critic", "wordpress-theme-critic",
)
# A sniff whose firing means the defect is tool-CATCHABLE (belongs in tranche T).
DISQUALIFYING_PREFIXES = (
    "WordPress.Security.",
    "WordPress.DB.PreparedSQL",
    "WordPress.WP.Capabilities",
    "WordPress.WP.PostsPerPage",
    "WordPress.DB.SlowDBQuery",
)


def php_of(md_path: Path) -> str | None:
    m = re.search(r"```php\n(.*?)\n```", md_path.read_text(encoding="utf-8"), re.S)
    return m.group(1) if m else None


def run_wpcs(code: str) -> tuple[list | None, str]:
    phpcs = PHP_TOOLS / "vendor" / "bin" / "phpcs"
    if not phpcs.exists():
        return None, "phpcs not installed (run composer install in php-tools/)"
    with tempfile.NamedTemporaryFile("w", suffix=".php", delete=False, dir="/tmp") as f:
        f.write(code)
        path = f.name
    try:
        proc = subprocess.run(
            [str(phpcs), "--runtime-set", "installed_paths", INSTALLED_PATHS,
             "--standard=WordPress", "--report=json", "-q", path],
            cwd=PHP_TOOLS, capture_output=True, text=True)
    finally:
        os.unlink(path)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, (proc.stdout + proc.stderr)[:300]
    msgs: list = []
    for fdata in data.get("files", {}).values():
        msgs.extend(fdata.get("messages", []))
    return msgs, ""


def j_fixtures(suites: list[str]) -> list[Path]:
    out: list[Path] = []
    for suite in suites:
        fixtures = SUITES_ROOT / suite / "fixtures"
        for sidecar in sorted(fixtures.glob("*.provenance.yaml")):
            data = yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {}
            if data.get("tranche") == "J" and str(data.get("status", "active")).lower() != "draft":
                out.append(fixtures / f"{sidecar.name[:-len('.provenance.yaml')]}.md")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite", action="append", help="Restrict to a suite; repeatable.")
    args = ap.parse_args()
    suites = args.suite or list(CRITIC_SUITES)
    fixtures = j_fixtures(suites)
    if not fixtures:
        print("no tranche-J fixtures found for", suites)
        return 0
    failed = False
    for md in fixtures:
        code = php_of(md)
        if code is None:
            # No PHP block (e.g. a theme.json/HTML theme fixture). WPCS is not applicable;
            # tool-invisibility for these rests on theme.json schema, asserted in the sidecar.
            print(f"SKIP (no PHP; WPCS N/A)            {md.name}")
            continue
        msgs, err = run_wpcs(code)
        if msgs is None:
            print(f"PHPCS-ERR {md.name}: {err}")
            return 2
        disq = [m for m in msgs if any(m["source"].startswith(p) for p in DISQUALIFYING_PREFIXES)]
        tag = "TOOL-INVISIBLE" if not disq else "!! TOOL-CATCHABLE (mislabeled J)"
        print(f"{tag:34s} {md.name}  (disqualifying sniffs: {len(disq)}, total: {len(msgs)})")
        for m in disq:
            print(f"      line {m['line']}: {m['source']} — {m['message'][:88]}")
        failed = failed or bool(disq)
    print("\nRESULT:", "all tranche-J fixtures tool-invisible"
          if not failed else "MISLABELED fixtures present — fix before scoring")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
