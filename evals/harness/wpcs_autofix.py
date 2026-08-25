#!/usr/bin/env python3
"""Deterministic WPCS auto-fix stage for the executor repair loop.

phpcbf — from the same pinned toolchain the phpcs_wpcs gate resolves — fixes
the mechanical whitespace/formatting half of a WPCS failure without spending
a model repair slot. The rewriter splices fixed file bodies back into the
packet text, so the loop keeps exchanging packets and every later gate sees
exactly what re-materialization produces.

The oracle never runs phpcbf: gates measure what the packet contains. This
stage repairs the packet, and the repaired packet is re-certified in full,
recorded as a distinct autofix pass in the loop history.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import materialize_wordpress_executor_packet as materializer
import validate_wordpress_executor_packet as packet_oracle
import wp_security_gate
from validate_wordpress_artifact import PHPCS_IGNORE_PATTERNS

PHPCBF_SUMMARY_LIMIT = 2000


@dataclass(frozen=True)
class AutofixOutcome:
    changed: bool
    packet_text: str
    files_changed: tuple[str, ...]
    detail: str


def _unchanged(packet_text: str, detail: str) -> AutofixOutcome:
    return AutofixOutcome(False, packet_text, (), detail)


def phpcbf_path(toolchain: wp_security_gate.Toolchain) -> Path:
    return toolchain.phpcs.parent / "phpcbf"


def run_phpcbf(target: Path, toolchain: wp_security_gate.Toolchain,
               timeout_sec: int) -> str:
    """Run phpcbf mirroring the phpcs_wpcs gate invocation, fixing in place.

    phpcbf exit codes are not usable signal (a fully successful fix exits
    non-zero), so callers must detect change by content comparison.
    """
    command = [
        toolchain.php, str(phpcbf_path(toolchain)),
        "--runtime-set", "installed_paths", toolchain.installed_paths,
        "--standard=WordPress", "--extensions=php",
        f"--ignore={','.join(PHPCS_IGNORE_PATTERNS)}", str(target),
    ]
    proc = subprocess.run(command, capture_output=True, text=True,
                          timeout=timeout_sec, check=False, cwd=toolchain.root)
    return (proc.stdout or "")[-PHPCBF_SUMMARY_LIMIT:]


def rewrite_packet(packet_text: str, executor: str,
                   fixed: dict[str, str]) -> tuple[str, tuple[str, ...]]:
    """Splice fixed file bodies back into the packet's file sections.

    Pure. Uses the same section/fence scanners as materialization, so the
    rewritten packet re-materializes to exactly the fixed contents. Returns
    (new_packet_text, files_changed); files absent from the packet or whose
    normalized content is already identical are left untouched.
    """
    splices: list[tuple[int, int, str]] = []
    changed: list[str] = []
    section_spans = packet_oracle.section_spans(packet_text)
    for name in materializer.PACKET_SECTIONS.get(executor, ()):
        if name not in section_spans:
            continue
        s_start, s_end = section_spans[name]
        section_text = packet_text[s_start:s_end]
        file_spans, _issues = materializer.file_fence_spans(section_text)
        for rel_path, (f_start, f_end) in file_spans:
            key = str(rel_path)
            if key not in fixed:
                continue
            current = section_text[f_start:f_end].rstrip() + "\n"
            replacement = fixed[key].rstrip() + "\n"
            if replacement == current:
                continue
            # The span excludes the closing "\n```"; that newline stays owned
            # by the fence, so the spliced body must not carry a trailing one.
            splices.append((s_start + f_start, s_start + f_end,
                            replacement.rstrip("\n")))
            changed.append(key)
    if not splices:
        return packet_text, ()
    pieces: list[str] = []
    cursor = 0
    for start, end, body in sorted(splices):
        pieces.append(packet_text[cursor:start])
        pieces.append(body)
        cursor = end
    pieces.append(packet_text[cursor:])
    return "".join(pieces), tuple(changed)


def _php_blocks(packet_text: str, executor: str) -> dict[str, str]:
    parsed = packet_oracle.sections(packet_text)
    blocks: dict[str, str] = {}
    for name in materializer.PACKET_SECTIONS.get(executor, ()):
        extracted, _issues = materializer.extract_file_blocks(parsed.get(name, ""))
        for rel_path, content in extracted:
            if rel_path.suffix.lower() == ".php":
                blocks[str(rel_path)] = content
    return blocks


def autofix_packet_text(packet_text: str, executor: str, workspace: Path,
                        timeout_sec: int) -> AutofixOutcome:
    """Materialize the packet's PHP files, phpcbf them, splice fixes back.

    Never raises for the expected failure shapes (missing toolchain, phpcbf
    timeout, nothing fixable): the loop must fall through to a model repair,
    not crash. The workspace must be a fresh directory owned by the caller.
    """
    if executor == "blueprint":
        return _unchanged(packet_text, "blueprint packets carry no PHP files")
    toolchain, reason = wp_security_gate.resolve_toolchain()
    if toolchain is None:
        return _unchanged(packet_text, reason or "pinned WPCS toolchain unavailable")
    if not phpcbf_path(toolchain).exists():
        return _unchanged(packet_text, "phpcbf missing from pinned toolchain")
    php_blocks = _php_blocks(packet_text, executor)
    if not php_blocks:
        return _unchanged(packet_text, "packet contains no extractable PHP files")

    tree = workspace / "tree"
    for key, content in php_blocks.items():
        target = tree / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    try:
        summary = run_phpcbf(tree, toolchain, timeout_sec)
    except subprocess.TimeoutExpired:
        return _unchanged(packet_text, f"phpcbf exceeded {timeout_sec}s")

    fixed: dict[str, str] = {}
    for key, before in php_blocks.items():
        try:
            after = (tree / key).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if after != before:
            fixed[key] = after
    if not fixed:
        return _unchanged(packet_text, "phpcbf found nothing auto-fixable")
    new_text, changed = rewrite_packet(packet_text, executor, fixed)
    detail = f"phpcbf fixed {len(changed)} file(s): {', '.join(changed)}"
    return AutofixOutcome(bool(changed), new_text, changed, detail)
