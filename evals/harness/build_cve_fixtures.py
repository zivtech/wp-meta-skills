#!/usr/bin/env python3
"""CVE-diff sourcing pipeline for the critic corpus `researcher` tranche (recommendation 09, §6).

Turns a CVE-pinned plugin (vulnerable version + patched version) into DRAFT tranche-J
fixtures by diffing the two: the hunks removed/changed in the vulnerable version localize
the defect to a file + line range. It is a SOURCING AID, not an autonomous fixture
generator — the honest labor is the human-verification gate:

  1. `fetch_versions()` best-effort exports the vulnerable + patched source for a seed
     (svn export from plugins.svn.wordpress.org, or a version zip). Needs network + svn/unzip.
  2. `localize_defect()` (PURE, unit-tested) diffs the two and returns the changed line
     ranges in the vulnerable file — a DRAFT localization, because a CVE patch often carries
     ride-along refactors.
  3. `emit_draft_fixture()` (PURE, unit-tested) writes a draft quad into a NON-globbed
     `fixtures/_drafts/` staging dir (invisible to the integrity guard, the frozen validator,
     and the scorer, all of which use non-recursive globs), marked `status: draft`.
  4. A HUMAN promotes a draft: confirms the defect lines, trims unrelated churn, writes
     `must_detect`/rubric/grounding, runs `verify_critic_tool_invisibility.py`, sets
     `status: active`, and moves the quad up into `fixtures/`. Only then can it be scored.

Licensing: plugin code is GPL — fine in this repo. Seeds come from CVWP
(github.com/david-prv/vulnerable-wordpress-plugins) or the Wordfence feed (attribution,
commercial-OK). NEVER the WPScan DB (CC BY-NC-SA, non-commercial).
"""
from __future__ import annotations

import argparse
import difflib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITES_ROOT = ROOT / "evals" / "suites"

# CVWP's 12 CVE-pinned plugins (github.com/david-prv/vulnerable-wordpress-plugins README map).
# vulnerable_version is the pinned exploitable release; patched_version is the first fixed
# release to diff against. Fill patched_version before running the fetch step.
CVWP_SEEDS = [
    {"slug": "give", "cve": "CVE-2024-5932", "vulnerable_version": "3.14.1",
     "patched_version": "3.14.2", "cwe": "CWE-502", "suite": "wordpress-security-critic"},
    {"slug": "litespeed-cache", "cve": "CVE-2024-28000", "vulnerable_version": "6.3",
     "patched_version": "6.4", "cwe": "CWE-287", "suite": "wordpress-security-critic"},
    {"slug": "essential-addons-for-elementor-lite", "cve": "CVE-2023-32243",
     "vulnerable_version": "5.7.1", "patched_version": "5.7.2", "cwe": "CWE-620",
     "suite": "wordpress-security-critic"},
]


@dataclass(frozen=True)
class Seed:
    slug: str
    cve: str
    vulnerable_version: str
    patched_version: str
    cwe: str
    suite: str = "wordpress-security-critic"

    @staticmethod
    def from_dict(d: dict) -> "Seed":
        return Seed(d["slug"], d["cve"], d["vulnerable_version"], d["patched_version"],
                    d.get("cwe", "CWE-unknown"), d.get("suite", "wordpress-security-critic"))


@dataclass
class DefectHunk:
    """A vulnerable-side region the patch changed, deleted, or (for a missing guard) inserted
    code around. `kind` is 'replace' | 'delete' | 'insert'. For an insert (the common
    add-a-guard fix), start == end is the vulnerable-side anchor line where the fix belongs and
    `removed` is empty; `added` always holds the patched-side lines the fix introduced."""
    start: int          # 1-indexed first vulnerable line of the hunk (anchor for inserts)
    end: int            # 1-indexed last vulnerable line (inclusive; == start for inserts)
    kind: str = "replace"
    removed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# PURE: diff localization + draft emission (unit-tested)
# --------------------------------------------------------------------------- #

def localize_defect(vulnerable_src: str, patched_src: str) -> list[DefectHunk]:
    """Diff patched vs vulnerable; return the vulnerable-side line ranges that the patch
    REMOVED or REPLACED. Those ranges localize the defect (a DRAFT — ride-along refactors
    mean a human must trim). Pure: no I/O."""
    vuln_lines = vulnerable_src.splitlines()
    patch_lines = patched_src.splitlines()
    sm = difflib.SequenceMatcher(a=vuln_lines, b=patch_lines, autojunk=False)
    hunks: list[DefectHunk] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):  # lines present/changed in the vulnerable file
            hunks.append(DefectHunk(start=i1 + 1, end=i2, kind=tag,
                                    removed=vuln_lines[i1:i2], added=patch_lines[j1:j2]))
        elif tag == "insert":  # a pure addition (e.g. a missing guard the patch adds back)
            anchor = i1 if i1 >= 1 else 1     # 1-indexed vulnerable line the fix belongs near
            hunks.append(DefectHunk(start=anchor, end=anchor, kind="insert",
                                    removed=[], added=patch_lines[j1:j2]))
    return hunks


def _fence(src: str) -> str:
    return "```php\n" + src.rstrip("\n") + "\n```"


def draft_review_target(slug: str, cve: str, src: str) -> str:
    """A BLIND review target .md for a draft — code plus a neutral instruction, no hints.
    The human promoting the draft rewrites/trims this."""
    return (
        f"# Review target: {slug} ({cve}, draft)\n\n"
        "Review this WordPress plugin excerpt with `wordpress-security-critic`. Report the "
        "security issues you find, each with a `file:line` reference and a concrete fix.\n\n"
        f"{_fence(src)}\n\n"
        "## Scope\n\n"
        "Static review of the code shown. Name any runtime, WP-CLI, or PHPUnit checks that "
        "would still be needed. Do not claim supply-chain review or production-exploit proof.\n"
    )


def draft_sidecar(seed: Seed, hunks: list[DefectHunk], file_name: str) -> str:
    """A DRAFT provenance sidecar. status:draft keeps it out of every scored run and every
    globbed gate. The human fills grounding.description + must_detect + tool_invisibility."""
    lines = [
        f"fixture_id: {seed.slug}-{seed.cve.lower()}",
        "tranche: J",
        "provenance: researcher",
        "license: GPL-2.0-or-later",
        f"source: \"cve:{seed.cve} plugin={seed.slug} vulnerable={seed.vulnerable_version} patched={seed.patched_version}\"",
        "expected_verdict: REJECT",
        "status: draft",
        "# HUMAN GATE (do not score until done):",
        "#  1. confirm the defect lines below; trim ride-along refactors from the diff",
        "#  2. write must_detect (rubric) + grounding.description to match",
        "#  3. run verify_critic_tool_invisibility.py; if a sniff fires, this is tranche T not J",
        "#  4. set status: active and move the quad up into fixtures/",
        "draft_localized_ranges:",
    ]
    for h in hunks:
        lines.append(f"  - file: {file_name}")
        lines.append(f"    line_start: {h.start}")
        lines.append(f"    line_end: {h.end}")
    lines.append(f"grounding:  # DRAFT — cwe from the CVE record; description written by the human")
    lines.append(f"  - description: \"TODO: written during human verification\"")
    lines.append(f"    cwe: {seed.cwe}")
    lines.append(f"    file: {file_name}")
    lines.append(f"    line: {hunks[0].start if hunks else 1}")
    lines.append("    severity: CRITICAL")
    return "\n".join(lines) + "\n"


def emit_draft_fixture(seed: Seed, vulnerable_src: str, patched_src: str,
                       file_name: str) -> dict[str, str]:
    """Return {relative_path: content} for a draft quad, staged under fixtures/_drafts/ so it
    is invisible to the (non-recursive) guard, validator, and scorer globs. Pure."""
    hunks = localize_defect(vulnerable_src, patched_src)
    stem = f"{seed.slug}-{seed.cve.lower()}"
    base = f"evals/suites/{seed.suite}/fixtures/_drafts"
    return {
        f"{base}/{stem}.md": draft_review_target(seed.slug, seed.cve, vulnerable_src),
        f"{base}/{stem}-clean.md": draft_review_target(f"{seed.slug} (patched)", seed.cve, patched_src),
        f"{base}/{stem}.provenance.yaml": draft_sidecar(seed, hunks, file_name),
    }


# --------------------------------------------------------------------------- #
# I/O: best-effort version fetch (needs network + svn/unzip; not unit-tested)
# --------------------------------------------------------------------------- #

def fetch_versions(seed: Seed, work: Path) -> tuple[Path, Path]:  # pragma: no cover
    """svn-export the vulnerable + patched tags from plugins.svn.wordpress.org into `work`.
    Returns (vulnerable_dir, patched_dir). Raises if svn or the network is unavailable."""
    if shutil.which("svn") is None:
        raise RuntimeError("svn not found; install subversion or fetch the version zips manually")
    out = []
    for ver in (seed.vulnerable_version, seed.patched_version):
        dest = work / f"{seed.slug}-{ver}"
        url = f"https://plugins.svn.wordpress.org/{seed.slug}/tags/{ver}/"
        proc = subprocess.run(["svn", "export", "--force", url, str(dest)],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"svn export failed for {seed.slug}@{ver}: {proc.stderr[:200]}")
        out.append(dest)
    return out[0], out[1]


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=Path, help="JSON list of seed dicts; default: the bundled CVWP map.")
    ap.add_argument("--slug", help="Emit only this slug from the seed set.")
    ap.add_argument("--fetch", action="store_true",
                    help="Actually svn-export and diff (needs network + svn). Without it, prints the plan.")
    ap.add_argument("--main-file", default=None,
                    help="Path within the plugin of the primary vulnerable file to diff.")
    args = ap.parse_args(argv)

    seeds = [Seed.from_dict(d) for d in (json.loads(args.seeds.read_text()) if args.seeds else CVWP_SEEDS)]
    if args.slug:
        seeds = [s for s in seeds if s.slug == args.slug]
    if not seeds:
        print("no matching seeds", file=sys.stderr)
        return 1

    if not args.fetch:
        print("DRY RUN — seeds that would be sourced (pass --fetch with network + svn to run):")
        for s in seeds:
            print(f"  {s.slug:40s} {s.cve}  {s.vulnerable_version} -> {s.patched_version}  ({s.cwe})")
        print("\nEach produces a DRAFT quad under fixtures/_drafts/ that a human must verify "
              "and promote (see the sidecar HUMAN GATE checklist).")
        return 0

    written = 0
    for seed in seeds:
        work = ROOT / ".cve-work" / seed.slug
        work.mkdir(parents=True, exist_ok=True)
        vuln_dir, patch_dir = fetch_versions(seed, work)
        rel = args.main_file or _guess_main_file(vuln_dir, seed.slug)
        vuln_src = (vuln_dir / rel).read_text(encoding="utf-8", errors="replace")
        patch_src = (patch_dir / rel).read_text(encoding="utf-8", errors="replace")
        for rel_path, content in emit_draft_fixture(seed, vuln_src, patch_src, Path(rel).name).items():
            dest = ROOT / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            written += 1
            print("wrote draft", rel_path)
    print(f"\n{written} draft file(s) written. Now run the HUMAN GATE on each before scoring.")
    return 0


def _guess_main_file(plugin_dir: Path, slug: str) -> str:  # pragma: no cover
    candidate = plugin_dir / f"{slug}.php"
    if candidate.exists():
        return f"{slug}.php"
    php = sorted(plugin_dir.glob("*.php"))
    if not php:
        raise RuntimeError(f"no top-level PHP file in {plugin_dir}; pass --main-file")
    return php[0].name


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
