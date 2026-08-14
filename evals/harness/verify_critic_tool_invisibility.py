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

# --------------------------------------------------------------------------- #
# PHPStan half of the criterion
# --------------------------------------------------------------------------- #
#
# corpus-prereg.md states every J fixture passes WPCS *and PHPStan* clean by
# construction. Only the WPCS half was ever enforced, though the PHPStan stack has been
# pinned in php-tools all along. That gap matters most right now: recommendation 01 turns
# the critic into a tool-runner, so "no static tool sees this" stops being a footnote and
# becomes the thing tranche J's discriminating power rests on.
#
# Run at the most sensitive level and classify by identifier. The polarity is deliberately
# the opposite of the WPCS list above: WPCS names what disqualifies (deny-list), which
# silently misses a newly-added sniff. Here anything NOT known-benign disqualifies, so a
# PHPStan upgrade that starts catching a J defect trips the gate instead of passing quietly.
PHPSTAN_LEVEL = "max"
PHPSTAN_MEMORY_LIMIT = "2G"

# Rules describing the SNIPPET's incompleteness, not the defect under test: fixtures are
# bare excerpts with no autoloader, no plugin bootstrap, no type declarations and no runtime
# constants, so these fire on correct and defective code alike.
#
# Each rule is (identifier prefix, required message substring or None). The message
# discriminator exists because an identifier alone is sometimes too coarse to be safe --
# see `argument.type` below, which is the whole reason this structure is not a plain tuple
# of strings.
PHPSTAN_BENIGN_RULES = (
    ("missingType.", None),          # no return/param/property types in an excerpt
    ("foreach.nonIterable", None),   # e.g. get_posts() typed as array<int|WP_Post>|null
    ("property.nonObject", None),    # int|WP_Post unions the excerpt never narrows
    ("offsetAccess.nonOffsetAccessible", None),
    ("constant.notFound", None),     # WordPress runtime constants absent from the stubs
    # `global $wpdb;` in an excerpt gives $wpdb no type, so calls on it degrade to
    # "on mixed". Verified noise, not detection: annotating `/** @var \wpdb $wpdb */` on
    # sec-like-wildcard-no-esc-like-v1 clears these and surfaces nothing about the
    # missing esc_like.
    ("method.nonObject", None),
    ("encapsedStringPart.nonString", None),
    # NARROWED 2026-08-13. `argument.type` is benign only in its `mixed`-propagation shape,
    # which is what untyped $_POST/$_GET input produces -- all 15 occurrences in the current
    # corpus are "… expects X, mixed given". The SAME identifier also carries
    # "wpdb::prepare() expects literal-string, non-falsy-string given", which is PHPStan's
    # SQL-injection heuristic and a genuine finding. Suppressing the identifier wholesale
    # hid it: measured on a typed variant of sec-like-wildcard-no-esc-like-v1, the
    # literal-string finding was classified benign. The discriminator closes that.
    ("argument.type", "mixed given"),
    # Deliberately NOT allowlisted: class.notFound / function.notFound. They never fire on
    # the current corpus, and "this WordPress function does not exist" is a real defect
    # class (a typo'd hook callback is a silent no-op), so default-deny should surface them.
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


def is_benign(finding: dict, rules: tuple = PHPSTAN_BENIGN_RULES) -> bool:
    """PURE. True iff a finding matches an allowlist rule: identifier prefix, and the
    message substring when that rule carries one."""
    identifier = str(finding.get("identifier", ""))
    message = str(finding.get("message", ""))
    return any(identifier.startswith(prefix) and (needle is None or needle in message)
               for prefix, needle in rules)


def classify_phpstan(findings: list[dict], rules: tuple = PHPSTAN_BENIGN_RULES) -> list[dict]:
    """PURE. Return the findings that disqualify a fixture from tranche J.

    Default-deny: a finding is benign only if it matches an allowlist rule, so an
    unrecognised identifier -- or a recognised identifier carrying an unrecognised message
    shape -- is surfaced for triage rather than assumed harmless.
    """
    return [f for f in findings if not is_benign(f, rules)]


def parse_phpstan_json(payload: str) -> tuple[list[dict] | None, str]:
    """PURE. Flatten PHPStan's `--error-format=json` into a list of findings."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None, payload[:300]
    findings: list[dict] = []
    for path, entry in (data.get("files") or {}).items():
        for message in entry.get("messages", []):
            findings.append({"file": path, "line": message.get("line"),
                             "identifier": message.get("identifier") or "",
                             "message": message.get("message", "")})
    for generic in data.get("errors", []) or []:
        findings.append({"file": "-", "line": None, "identifier": "phpstan.internal",
                         "message": str(generic)})
    return findings, ""


def run_phpstan(code_by_name: dict[str, str]) -> tuple[dict[str, list[dict]] | None, str]:  # pragma: no cover
    """Analyse every J snippet in one PHPStan process; return findings keyed by fixture."""
    phpstan = PHP_TOOLS / "vendor" / "bin" / "phpstan"
    stubs = PHP_TOOLS / "vendor" / "php-stubs" / "wordpress-stubs" / "wordpress-stubs.php"
    if not phpstan.exists():
        return None, "phpstan not installed (run composer install in php-tools/)"
    if not stubs.exists():
        return None, "wordpress-stubs not installed (run composer install in php-tools/)"
    with tempfile.TemporaryDirectory(prefix="wp-critic-phpstan-") as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "src"
        src.mkdir()
        for name, code in code_by_name.items():
            (src / f"{name}.php").write_text(code, encoding="utf-8")
        config = tmp_path / "phpstan.neon"
        config.write_text(
            "parameters:\n"
            f"    level: {PHPSTAN_LEVEL}\n"
            f"    tmpDir: {tmp_path / 'cache'}\n"
            "    paths:\n"
            f"        - {src}\n"
            "    scanFiles:\n"
            f"        - {stubs}\n",
            encoding="utf-8")
        proc = subprocess.run(
            [str(phpstan), "analyse", "-c", str(config), "--no-progress",
             f"--memory-limit={PHPSTAN_MEMORY_LIMIT}", "--error-format=json"],
            cwd=PHP_TOOLS, capture_output=True, text=True)
        findings, err = parse_phpstan_json(proc.stdout)
    if findings is None:
        return None, err or (proc.stderr or "")[:300]
    by_fixture: dict[str, list[dict]] = {name: [] for name in code_by_name}
    for finding in findings:
        name = Path(str(finding["file"])).stem
        by_fixture.setdefault(name, []).append(finding)
    return by_fixture, ""


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
    code_by_name: dict[str, str] = {}
    print("== WPCS ==")
    for md in fixtures:
        code = php_of(md)
        if code is None:
            # No PHP block (e.g. a theme.json/HTML theme fixture). Neither WPCS nor PHPStan
            # is applicable; tool-invisibility for these rests on theme.json schema,
            # asserted in the sidecar.
            print(f"SKIP (no PHP; static PHP tools N/A) {md.name}")
            continue
        code_by_name[md.name[: -len(".md")]] = code
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

    if code_by_name:
        print(f"\n== PHPStan (level {PHPSTAN_LEVEL}, default-deny on unknown identifiers) ==")
        by_fixture, err = run_phpstan(code_by_name)
        if by_fixture is None:
            print(f"PHPSTAN-ERR: {err}")
            return 2
        for name in sorted(code_by_name):
            found = by_fixture.get(name, [])
            disq = classify_phpstan(found)
            tag = "TOOL-INVISIBLE" if not disq else "!! TOOL-CATCHABLE (mislabeled J)"
            print(f"{tag:34s} {name}.md  (disqualifying: {len(disq)}, benign: "
                  f"{len(found) - len(disq)})")
            for f in disq:
                print(f"      line {f['line']}: {f['identifier']} — {f['message'][:88]}")
            failed = failed or bool(disq)

    print("\nRESULT:", "all tranche-J fixtures tool-invisible to WPCS and PHPStan"
          if not failed else "MISLABELED fixtures present — fix before scoring")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
