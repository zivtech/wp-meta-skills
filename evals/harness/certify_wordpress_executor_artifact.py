#!/usr/bin/env python3
"""Certify a saved WordPress executor packet through artifact validation.

This composes the deterministic executor evidence stack:

1. saved packet contract;
2. packet-to-file materialization;
3. generated artifact oracle.

It does not call an LLM and does not claim benchmark quality. It answers one
smaller but useful question: can this saved executor packet become files that
pass the requested WordPress artifact gate?
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import materialize_wordpress_executor_packet
import validate_wordpress_artifact
import validate_wordpress_executor_packet


ARTIFACT_TYPES = {
    "plugin": "plugin",
    "block": "block",
    "blueprint": "blueprint",
}
EVIDENCE_SCHEMA_VERSION = 1
MAX_DIGEST_FILES = 10_000
MAX_DIGEST_BYTES = 256 * 1024 * 1024
MAX_DIGEST_PATH_BYTES = 4096


def digest_regular_tree(path: Path) -> str:
    """Digest a bounded tree without following symlinks or special files."""
    if stat.S_ISLNK(path.lstat().st_mode):
        raise ValueError(f"artifact root is a symlink: {path}")
    root = path.resolve(strict=True)
    entries: list[dict[str, Any]] = []
    total = 0
    candidates = [root] if root.is_file() else sorted(root.rglob("*"), key=lambda item: item.as_posix())
    for candidate in candidates:
        if candidate != root and ".workspace-lease" in candidate.relative_to(root).parts:
            continue
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"artifact contains symlink: {candidate}")
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"artifact contains non-regular file: {candidate}")
        if len(entries) >= MAX_DIGEST_FILES or total + info.st_size > MAX_DIGEST_BYTES:
            raise ValueError("artifact exceeds digest bounds")
        relative = candidate.name if root.is_file() else candidate.relative_to(root).as_posix()
        if len(relative.encode("utf-8")) > MAX_DIGEST_PATH_BYTES:
            raise ValueError("artifact path exceeds digest bounds")
        content_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
        entries.append({"path": relative, "size": info.st_size, "sha256": content_hash})
        total += info.st_size
    lines = "\n".join(
        json.dumps(record, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        for record in entries
    )
    encoded = ((lines + "\n") if lines else "").encode()
    return hashlib.sha256(encoded).hexdigest()


def display_path(path: Path) -> str:
    return validate_wordpress_artifact.repo_relative(path)


def artifact_path_for(executor: str, out_dir: Path) -> Path:
    if executor == "blueprint":
        return out_dir / "blueprint.json"
    return out_dir


def execution_closure_for(executor: str, out_dir: Path) -> Path:
    if executor != "plugin":
        return artifact_path_for(executor, out_dir)
    children = [item for item in out_dir.iterdir()
                if item.name != ".workspace-lease" and stat.S_ISDIR(item.lstat().st_mode)]
    if len(children) != 1:
        raise ValueError("plugin materialization must contain exactly one plugin directory")
    return children[0]


def overall_status(packet_result: dict[str, Any], materialization: dict[str, Any], artifact: dict[str, Any] | None) -> str:
    if not packet_result.get("pass") or not materialization.get("pass"):
        return "fail"
    if not artifact:
        return "fail"
    if artifact.get("status") == "blocked":
        return "blocked"
    if artifact.get("pass"):
        return "pass"
    return "fail"


def artifact_args(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        profile=args.profile,
        require_tool=args.require_tool or [],
        timeout_sec=args.timeout_sec,
        wp_root=args.wp_root,
        wp_env_root=args.wp_env_root,
        plugin_check_require=args.plugin_check_require,
    )


def feedback_items(
    packet_result: dict[str, Any],
    materialization: dict[str, Any],
    artifact: dict[str, Any] | None,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for check in packet_result.get("checks", []):
        if not check.get("passed", False):
            items.append(
                {
                    "gate": "packet",
                    "id": str(check.get("id", "unknown")),
                    "detail": str(check.get("detail", "")),
                }
            )
    for issue in materialization.get("issues", []):
        if issue.get("status") in {"fail", "blocked", "skip"}:
            items.append(
                {
                    "gate": "materialization",
                    "id": str(issue.get("status", "issue")),
                    "detail": str(issue.get("detail", "")),
                }
            )
    for check in (artifact or {}).get("checks", []):
        if check.get("required", True) and check.get("status") in {"fail", "blocked"}:
            items.append(
                {
                    "gate": "artifact",
                    "id": str(check.get("id", "unknown")),
                    "detail": str(check.get("detail", "")),
                }
            )
    return items


def build_repair_prompt(result: dict[str, Any], packet_text: str) -> str:
    lines = [
        "# WordPress Executor Repair Prompt",
        "",
        "Revise the saved executor packet so it passes the deterministic certification gate.",
        "Return the full corrected packet only; do not summarize the changes.",
        "",
        "## Certification Context",
        "",
        f"- Executor: `{result['executor']}`",
        f"- Packet: `{result['packet']}`",
        f"- Failed status: `{result['status']}`",
        f"- Profile: `{result['profile']}`",
        "",
        "## Failing Evidence",
        "",
    ]
    if result.get("feedback"):
        lines.extend(f"- `{item['gate']}` / `{item['id']}`: {item['detail']}" for item in result["feedback"])
    else:
        lines.append("- No structured failing check was recorded; inspect `certification.json` before revising.")
    lines.extend(
        [
            "",
            "## Repair Constraints",
            "",
            "- Preserve the original requested functionality and WordPress scope.",
            "- Preserve all required executor output headings exactly.",
            "- Keep file paths materializable as `### relative/path.ext` followed immediately by one fenced file block.",
            "- Keep exact WordPress APIs and verification commands concrete.",
            "- Keep negative-space language for any WPCS, PHPUnit, Plugin Check, wp-env, MCP Adapter, AI Client, browser/editor, or release-readiness claims that were not actually run.",
            "- Do not add credentials, provider configuration, production write commands, or unrelated features.",
            "",
            "## Saved Packet To Revise",
            "",
            "````markdown",
            packet_text.rstrip(),
            "````",
            "",
        ]
    )
    return "\n".join(lines)


def certify_executor_artifact(args: argparse.Namespace) -> dict[str, Any]:
    packet_path = Path(args.packet).resolve()
    out_dir = Path(args.out_dir).resolve()
    packet_text = packet_path.read_text(encoding="utf-8")
    packet_sha256 = hashlib.sha256(packet_path.read_bytes()).hexdigest()

    packet_result = validate_wordpress_executor_packet.validate_packet(packet_text, args.executor)
    materialization: dict[str, Any]
    artifact_result: dict[str, Any] | None = None

    if packet_result.get("pass"):
        materialization = materialize_wordpress_executor_packet.materialize_packet(
            args.executor,
            packet_text,
            out_dir,
            overwrite=args.overwrite,
        )
        materialization["out_dir"] = display_path(out_dir)
    else:
        materialization = {
            "executor": args.executor,
            "out_dir": display_path(out_dir),
            "status": "skip",
            "pass": False,
            "written": [],
            "issues": [{"status": "skip", "detail": "packet contract failed; materialization skipped"}],
        }

    if materialization.get("pass"):
        artifact_result = validate_wordpress_artifact.validate_artifact(
            ARTIFACT_TYPES[args.executor],
            artifact_path_for(args.executor, out_dir),
            artifact_args(args),
        )

    status = overall_status(packet_result, materialization, artifact_result)
    artifact_digest = None
    if materialization.get("pass"):
        try:
            artifact_digest = digest_regular_tree(execution_closure_for(args.executor, out_dir))
        except (OSError, ValueError) as exc:
            status = "fail"
            materialization.setdefault("issues", []).append({"status": "fail", "detail": str(exc)})
    result = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_id": getattr(args, "evidence_id", None),
        "executor": args.executor,
        "packet": display_path(packet_path),
        "out_dir": display_path(out_dir),
        "artifact_path": display_path(artifact_path_for(args.executor, out_dir)),
        "profile": args.profile,
        "packet_sha256": packet_sha256,
        "artifact_digest": artifact_digest,
        "required_tools": args.require_tool or [],
        "status": status,
        "pass": status == "pass",
        "packet_gate": packet_result,
        "materialization_gate": materialization,
        "artifact_gate": artifact_result,
        "feedback": feedback_items(packet_result, materialization, artifact_result),
        "negative_space": [
            "This certifies only the supplied saved executor packet, not model quality or variance.",
            "Static profile passes do not prove Plugin Check, PHPUnit, wp-env, browser, editor, frontend behavior, or runtime behavior.",
            "Runtime profile results are environment-specific and report missing required tools as blocked.",
        ],
    }
    if args.result_dir:
        write_results(result, Path(args.result_dir).resolve(), packet_text)
    return result


def write_results(result: dict[str, Any], result_dir: Path, packet_text: str) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "certification.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    api_lint = (result.get("artifact_gate") or {}).get("api_lint")
    if api_lint:
        (result_dir / "api-lint.json").write_text(json.dumps(api_lint, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    security_gate = (result.get("artifact_gate") or {}).get("security_gate")
    if security_gate:
        (result_dir / "security-gate.json").write_text(json.dumps(security_gate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# WordPress Executor Artifact Certification",
        "",
        f"- Executor: `{result['executor']}`",
        f"- Status: `{result['status']}`",
        f"- Packet: `{result['packet']}`",
        f"- Output directory: `{result['out_dir']}`",
        f"- Artifact path: `{result['artifact_path']}`",
        f"- Profile: `{result['profile']}`",
        f"- Required tools: `{', '.join(result['required_tools']) if result['required_tools'] else 'none'}`",
        "",
        "## Gates",
        "",
        f"- Packet gate: `{'pass' if result['packet_gate'].get('pass') else 'fail'}`",
        f"- Materialization gate: `{result['materialization_gate'].get('status')}`",
        f"- Artifact gate: `{(result['artifact_gate'] or {}).get('status', 'not-run')}`",
    ]
    security_gate = (result.get("artifact_gate") or {}).get("security_gate")
    if security_gate:
        lines.append(f"- Security gate: `{security_gate.get('status')}` (`security-gate.json`)")
    lines.append("")
    if result.get("feedback"):
        lines.extend(
            [
                "## Feedback",
                "",
            ]
        )
        lines.extend(f"- `{item['gate']}` / `{item['id']}`: {item['detail']}" for item in result["feedback"])
        lines.append("")
    lines.extend(
        [
            "## Negative Space",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in result["negative_space"])
    (result_dir / "scorecard.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if result["status"] != "pass":
        (result_dir / "repair-prompt.md").write_text(build_repair_prompt(result, packet_text), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Certify a WordPress executor packet through artifact validation.")
    parser.add_argument("--executor", choices=sorted(ARTIFACT_TYPES), required=True)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing generated artifact directory.")
    parser.add_argument("--result-dir", type=Path, help="Optional directory for certification.json and scorecard.md.")
    parser.add_argument("--profile", choices=("static", "runtime"), default="static")
    parser.add_argument("--evidence-id", help="Opaque caller identity recorded in certification evidence.")
    parser.add_argument(
        "--require-tool",
        action="append",
        choices=("php-lint", "phpcs", "wpcs", "phpunit", "npm-build", "plugin-check", "wp-env"),
        help="External tool gate to require in addition to structural checks. May be repeated.",
    )
    parser.add_argument("--wp-root", help="WordPress root to use as cwd for WP-CLI checks.")
    parser.add_argument("--wp-env-root", help="Directory containing the .wp-env.json/package.json to use as cwd for wp-env checks.")
    parser.add_argument("--plugin-check-require", help="Optional Plugin Check cli.php path for runtime checks.")
    parser.add_argument("--timeout-sec", type=int, default=120)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = certify_executor_artifact(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] == "pass":
        return 0
    if result["status"] == "blocked":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
