#!/usr/bin/env python3
"""Re-certify a saved executor packet through the exact repair-loop gate path.

This is the converged-artifact handoff entry point. A packet that cleared every
macOS-reachable gate locally (packet contract, materialization, static artifact
heuristics, pinned-toolchain phpcs_wpcs) is committed under ``evals/handoff/``;
the no-secrets Linux CI lane re-runs the same ``make_certify`` composition the
repair loop used — static certifier plus isolated runtime smoke — where the
Linux-only oracles (wp_cli_activation, plugin_check, container_browser)
actually execute.

No LLM is involved. On a non-Linux host the isolated generated runtime reports
blocked by design, so the exit code is nonzero there for a runtime profile;
that is the expected macOS reading, not a defect. Green belongs to Linux.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS))

import invoke  # noqa: E402
import run_executor_repair_loop as repair_loop  # noqa: E402
import runtime_assertions  # noqa: E402
from workspace_lease import WorkspacePurpose, create_named  # noqa: E402

RECERTIFICATION_SCHEMA_VERSION = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path,
                        help="Committed executor packet markdown to re-certify.")
    parser.add_argument("--executor", default="plugin",
                        choices=("plugin", "block", "blueprint"))
    parser.add_argument("--profile", default="runtime", choices=("static", "runtime"))
    parser.add_argument("--run-id", required=True,
                        help="Fresh results workspace name; refused if it exists.")
    parser.add_argument("--suite", help="Required only for block runtime assertions.")
    parser.add_argument("--fixture", help="Required only for block runtime assertions.")
    parser.add_argument("--expected-packet-sha256",
                        help="Refuse re-certification when the committed packet "
                             "does not hash to this provenance value.")
    parser.add_argument("--timeout-sec", type=int, default=900)
    return parser


def load_block_assertion(args: argparse.Namespace):
    """Mirror the repair loop's fixture-owned assertion loading for block runtime."""
    if args.executor != "block" or args.profile != "runtime":
        return None
    if not args.suite or not args.fixture:
        raise ValueError("block runtime re-certification requires --suite and --fixture")
    pair = runtime_assertions.load_block_runtime_fixture(
        invoke.SUITES_ROOT, args.suite, args.fixture,
    )
    return pair.assertion


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        packet_bytes = args.packet.read_bytes()
    except OSError as exc:
        print(f"re-certification refused: packet unreadable: {exc}", file=sys.stderr)
        return 2
    packet_sha256 = hashlib.sha256(packet_bytes).hexdigest()
    if args.expected_packet_sha256 and packet_sha256 != args.expected_packet_sha256:
        print("re-certification refused: packet sha256 "
              f"{packet_sha256} does not match expected "
              f"{args.expected_packet_sha256}", file=sys.stderr)
        return 2
    try:
        block_assertion = load_block_assertion(args)
        repair_loop.validate_compatibility(args.executor, args.profile, block_assertion)
    except ValueError as exc:
        print(f"re-certification refused: {exc}", file=sys.stderr)
        return 2
    try:
        run_dir = create_named(repair_loop.RESULTS, args.run_id,
                               WorkspacePurpose.REPAIR_RUN).root
    except (ValueError, FileExistsError) as exc:
        print(f"re-certification refused: {exc}", file=sys.stderr)
        return 2
    certify = repair_loop.make_certify(
        args.suite or "handoff", args.executor, run_dir, args.profile,
        args.timeout_sec, block_assertion,
    )
    verdict = certify(0, args.packet)
    record = {
        "schema_version": RECERTIFICATION_SCHEMA_VERSION,
        "run_id": args.run_id,
        "executor": args.executor,
        "profile": args.profile,
        "packet_sha256": packet_sha256,
        "passed": bool(verdict.get("passed")),
        "failing_gates": verdict.get("failing_gates", []),
        "gate_vector": verdict.get("gate_vector", {}),
        "failures": verdict.get("failures", ""),
    }
    (run_dir / "recertification.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(record, indent=2))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
