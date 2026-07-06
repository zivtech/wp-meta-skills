#!/usr/bin/env python3
"""Audit static WordPress Playground Blueprints for launch-smoke readiness.

This is a preflight check, not a browser runtime. It answers whether a
generated `blueprint.json` can be launched directly from the committed evidence
bundle, or whether launch evidence is blocked by missing payloads such as VFS
plugin/theme ZIP files.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATIC_RUN = ROOT / "evals" / "results" / "wordpress-blueprint-executor-static-cert-20260621"
DEFAULT_OUT_DIR = ROOT / "evals" / "results" / "wordpress-blueprint-executor-launch-preflight-20260621"
PLAYGROUND_URL = "https://playground.wordpress.net/"


@dataclass(frozen=True)
class VfsReference:
    json_path: str
    path: str
    basename: str
    local_candidate: str | None
    local_exists: bool


@dataclass(frozen=True)
class BlueprintAudit:
    fixture_id: str
    blueprint_path: str
    landing_page: str | None
    steps_count: int
    vfs_references: list[VfsReference]
    missing_vfs_payloads: list[str]
    launch_method: str
    launch_url: str | None
    status: str
    blockers: list[str]


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def collect_vfs_refs(value: Any, *, trail: str = "$") -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    if isinstance(value, dict):
        if value.get("resource") == "vfs" and isinstance(value.get("path"), str):
            refs.append((trail, value["path"]))
        for key, child in value.items():
            refs.extend(collect_vfs_refs(child, trail=f"{trail}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            refs.extend(collect_vfs_refs(child, trail=f"{trail}[{index}]"))
    return refs


def encoded_fragment_url(blueprint: dict[str, Any]) -> str:
    compact = json.dumps(blueprint, separators=(",", ":"), sort_keys=True)
    return f"{PLAYGROUND_URL}#{quote(compact, safe='')}"


def local_candidate_for(vfs_path: str, asset_root: Path | None) -> Path | None:
    if asset_root is None:
        return None
    return asset_root / Path(vfs_path).name


def audit_blueprint(path: Path, *, asset_root: Path | None = None) -> BlueprintAudit:
    blueprint = load_json(path)
    refs: list[VfsReference] = []
    missing: list[str] = []
    for json_path, vfs_path in collect_vfs_refs(blueprint):
        candidate = local_candidate_for(vfs_path, asset_root)
        exists = bool(candidate and candidate.exists())
        if not exists:
            missing.append(vfs_path)
        refs.append(
            VfsReference(
                json_path=json_path,
                path=vfs_path,
                basename=Path(vfs_path).name,
                local_candidate=rel(candidate) if candidate else None,
                local_exists=exists,
            )
        )

    blockers: list[str] = []
    if missing:
        blockers.append(
            "Blueprint references VFS resources, but the required local payload "
            "files are not present in the committed evidence bundle."
        )

    steps = blueprint.get("steps") or []
    status = "blocked" if blockers else "ready_for_manual_launch"
    launch_method = "requires-vfs-payloads" if refs else "url-fragment"
    launch_url = None if refs else encoded_fragment_url(blueprint)
    fixture_id = path.parent.parent.name if path.parent.name == "generated-blueprint" else path.stem

    return BlueprintAudit(
        fixture_id=fixture_id,
        blueprint_path=rel(path),
        landing_page=blueprint.get("landingPage") if isinstance(blueprint.get("landingPage"), str) else None,
        steps_count=len(steps) if isinstance(steps, list) else 0,
        vfs_references=refs,
        missing_vfs_payloads=missing,
        launch_method=launch_method,
        launch_url=launch_url,
        status=status,
        blockers=blockers,
    )


def discover_blueprints(run_dir: Path) -> list[Path]:
    return sorted(run_dir.glob("*/generated-blueprint/blueprint.json"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_scorecard(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# WordPress Blueprint Launch Readiness Preflight",
        "",
        f"- Run: `{summary['run_id']}`",
        f"- Created: `{summary['created_at']}`",
        f"- Static certification run: `{summary['static_run']}`",
        f"- Overall status: `{summary['overall_status']}`",
        "",
        "## Boundary",
        "",
        "This is a launch-readiness preflight, not a WordPress Playground browser runtime.",
        "It checks whether generated Blueprints can be launched from committed evidence",
        "without missing VFS payloads. It does not prove plugin activation, page render,",
        "frontend behavior, editor behavior, or benchmark quality.",
        "",
        "## Results",
        "",
        "| Fixture | Status | Steps | VFS refs | Missing payloads | Landing page |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in summary["audits"]:
        lines.append(
            "| {fixture} | {status} | {steps} | {refs} | {missing} | {landing} |".format(
                fixture=row["fixture_id"],
                status=row["status"],
                steps=row["steps_count"],
                refs=len(row["vfs_references"]),
                missing=len(row["missing_vfs_payloads"]),
                landing=row["landing_page"] or "n/a",
            )
        )

    lines.extend(["", "## Blocking Details", ""])
    for row in summary["audits"]:
        if not row["blockers"]:
            lines.append(f"- `{row['fixture_id']}`: no preflight blockers.")
            continue
        missing = ", ".join(f"`{item}`" for item in row["missing_vfs_payloads"])
        lines.append(f"- `{row['fixture_id']}`: missing VFS payloads: {missing}.")

    lines.extend(
        [
            "",
            "## Next Required Evidence",
            "",
            "- Supply the referenced VFS plugin/theme ZIP payloads, or generate a self-contained Blueprint that does not require local VFS payloads.",
            "- Launch the generated Blueprint in WordPress Playground.",
            "- Record the landing URL, visible assertion, browser status, and any console/runtime errors.",
            "- Keep static certification separate from live Playground launch proof.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="wordpress-blueprint-executor-launch-preflight-20260621")
    parser.add_argument("--static-run-dir", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--asset-root", type=Path, help="Optional directory containing VFS ZIP payloads by basename.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    blueprints = discover_blueprints(args.static_run_dir)
    if not blueprints:
        raise SystemExit(f"No generated Blueprint files found under {args.static_run_dir}")

    audits = [audit_blueprint(path, asset_root=args.asset_root) for path in blueprints]
    overall = "blocked" if any(audit.status == "blocked" for audit in audits) else "ready_for_manual_launch"
    summary = {
        "run_id": args.run_id,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "static_run": args.static_run_dir.name,
        "asset_root": rel(args.asset_root) if args.asset_root else None,
        "overall_status": overall,
        "audits": [asdict(audit) for audit in audits],
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "launch-preflight-summary.json", summary)
    write_scorecard(args.out_dir / "scorecard.md", summary)
    print(f"Wrote {rel(args.out_dir / 'launch-preflight-summary.json')}")
    print(f"Wrote {rel(args.out_dir / 'scorecard.md')}")
    return 0 if overall != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
