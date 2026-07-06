"""Regression test for the WordPress Exact API contract validator."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def wordpress_surface_root() -> Path:
    monorepo_wordpress = ROOT / "wordpress-skills"
    if (monorepo_wordpress / ".claude").exists():
        return monorepo_wordpress
    return ROOT


def test_wordpress_exact_api_contract_validator_passes():
    result = subprocess.run(
        [sys.executable, "scripts/validate-wordpress-exact-api-contract.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_wordpress_performance_critic_names_query_cache_boundaries():
    surface = wordpress_surface_root()
    paths = [
        surface / ".claude" / "agents" / "wordpress-performance-critic.md",
        surface / ".claude" / "skills" / "wordpress-performance-critic" / "SKILL.md",
    ]

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "measurement is required before claiming production impact" in text
        assert "custom tables require scale evidence" in text
