#!/usr/bin/env python3
"""Remove a git worktree without silently destroying expensive, untracked evidence.

`git worktree remove` deletes the directory including gitignored contents, and
`git status --short` -- the natural "is this safe?" check -- cannot see ignored files by
design. On 2026-08-12 that combination destroyed a recorded judged run: `evals/results/`
is gitignored, the run lived in a disposable worktree, the worktree reported clean, and
the artifacts went with it.

Tracked files are recoverable from git and throwaway caches are cheap to rebuild. Run
artifacts are neither: regenerating one costs real model spend and hours of wall clock.
This wrapper checks for that category first, and refuses rather than asking forgiveness.

    scripts/safe-worktree-remove.py <worktree>                     # check, then remove
    scripts/safe-worktree-remove.py <worktree> --check-only        # report only
    scripts/safe-worktree-remove.py <worktree> --archive-to DIR    # move evidence, then remove
    scripts/safe-worktree-remove.py <worktree> --force             # discard deliberately

Exit codes: 0 removed or nothing at risk; 1 refused (evidence present); 2 usage/git error.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

# Ignored paths that are expensive to regenerate. Everything else ignored -- caches, venvs,
# node_modules, build output, per-environment capability manifests -- is cheap and may go.
PRECIOUS_PREFIXES = ("evals/results/",)


def classify(entries: Iterable[str],
             precious_prefixes: Iterable[str] = PRECIOUS_PREFIXES) -> dict[str, list[str]]:
    """PURE. Split ignored entries into the expensive-to-regenerate ones and the rest.

    `entries` are repo-relative paths as `git status --ignored --porcelain` reports them;
    git emits directories with a trailing slash, so prefix matching covers a whole tree.
    """
    prefixes = tuple(precious_prefixes)
    precious, disposable = [], []
    for entry in entries:
        normalized = entry.lstrip("./")
        is_dir = normalized.endswith("/")
        matched = any(
            normalized.startswith(prefix)               # entry sits inside a precious tree
            or (is_dir and prefix.startswith(normalized))  # entry is an ancestor of one
            for prefix in prefixes
        )
        (precious if matched else disposable).append(entry)
    return {"precious": precious, "disposable": disposable}


def parse_ignored(porcelain: str) -> list[str]:
    """PURE. Pull the ignored entries (`!!`) out of `git status --ignored --porcelain`."""
    out = []
    for line in porcelain.splitlines():
        if line.startswith("!! "):
            out.append(line[3:].strip().strip('"'))
    return out


def format_refusal(worktree: str, precious: list[str]) -> str:
    """PURE. The message a caller sees instead of losing their run artifacts."""
    listed = "\n".join(f"    {p}" for p in precious[:20])
    more = f"\n    ... and {len(precious) - 20} more" if len(precious) > 20 else ""
    return (
        f"REFUSED: {worktree} holds untracked run artifacts that git would delete.\n\n"
        f"{listed}{more}\n\n"
        "These are gitignored, so `git status --short` reports this worktree clean and\n"
        "`git worktree remove` would destroy them without warning. Regenerating a judged\n"
        "run costs model spend and hours.\n\n"
        "Choose one:\n"
        "  --archive-to <dir>   move them somewhere durable, then remove the worktree\n"
        "  --force              discard them deliberately\n"
        "  --check-only         just report and leave the worktree alone"
    )


def _git(args: list[str], cwd: Path | None = None) -> str:  # pragma: no cover
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:400]}")
    return proc.stdout


def scan(worktree: Path) -> dict[str, Any]:  # pragma: no cover
    porcelain = _git(["status", "--ignored", "--porcelain"], cwd=worktree)
    return classify(parse_ignored(porcelain))


def archive(worktree: Path, precious: list[str], dest: Path) -> list[str]:  # pragma: no cover
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    for rel in precious:
        src = worktree / rel
        if not src.exists():
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))
        moved.append(rel)
    return moved


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("worktree", type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--archive-to", type=Path, default=None)
    parser.add_argument("--force", action="store_true",
                        help="Remove even though run artifacts would be destroyed.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    worktree = args.worktree.resolve()
    if not worktree.is_dir():
        print(f"not a directory: {worktree}", file=sys.stderr)
        return 2
    try:
        found = scan(worktree)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    precious = found["precious"]
    if args.json:
        print(json.dumps({"worktree": str(worktree), **found}, indent=2))
    if args.check_only:
        if not args.json:
            print(f"{len(precious)} precious path(s), {len(found['disposable'])} disposable")
            for path in precious:
                print(f"  PRECIOUS  {path}")
        return 1 if precious else 0

    if precious and not (args.archive_to or args.force):
        print(format_refusal(str(worktree), precious), file=sys.stderr)
        return 1
    if precious and args.archive_to:
        moved = archive(worktree, precious, args.archive_to.resolve())
        print(f"archived {len(moved)} path(s) to {args.archive_to.resolve()}")

    _git(["worktree", "remove", str(worktree)])
    print(f"removed worktree {worktree}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
