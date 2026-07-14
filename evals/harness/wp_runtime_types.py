"""Typed request and evidence records for the isolated WordPress runtime."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import artifact_staging


@dataclass(frozen=True)
class RuntimeRequest:
    staged: artifact_staging.StagedTree
    plugin_slug: str
    evidence_id: str
    input_artifact_digest: str
    expected_input_artifact_digest: str
    timeout_sec: int = 300
    result_parent: Path | None = None
    requested_oracles: tuple[str, ...] = ("activation", "browser")


@dataclass(frozen=True)
class RuntimeResult:
    status: str
    evidence_id: str
    input_artifact_digest: str
    post_command_manifest_digest: str | None
    checks: tuple[dict[str, Any], ...] = ()
    inspection: dict[str, Any] = field(default_factory=dict)
    cleanup: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["pass"] = self.passed
        return result
