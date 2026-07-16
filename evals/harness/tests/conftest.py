import sys
from pathlib import Path

import pytest

# Make the harness modules importable when collected by pytest.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DOCKER_SHARDS = {
    "test_sandbox_proxy_supervisor_contract.py": "docker_sandbox",
    "test_sandbox_python_preflight.py": "docker_sandbox",
    "test_sandbox_tunnel_poll.py": "docker_sandbox",
    "test_sandboxed_package_runner.py": "docker_sandbox",
    "test_sandboxed_package_runner_canonical_bind.py": "docker_sandbox",
    "test_sandboxed_package_runner_limits.py": "docker_sandbox",
    "test_wp_staged_runtime_docker.py": "docker_generated_runtime",
}
DOCKER_SHARD_MARKERS = frozenset(DOCKER_SHARDS.values())


def pytest_itemcollected(item):
    """Assign every Docker node to exactly one reviewed CI shard."""
    is_docker = item.get_closest_marker("docker_boundary") is not None
    existing = {
        marker for marker in DOCKER_SHARD_MARKERS if item.get_closest_marker(marker)
    }
    if not is_docker:
        if existing:
            raise pytest.UsageError(f"non-Docker node has Docker shard: {item.nodeid}")
        return
    if item.get_closest_marker("live_provider"):
        raise pytest.UsageError(f"Docker/live-provider marker overlap: {item.nodeid}")
    expected = DOCKER_SHARDS.get(Path(str(item.path)).name)
    if expected is None:
        raise pytest.UsageError(f"Docker node has no reviewed shard: {item.nodeid}")
    if existing and existing != {expected}:
        raise pytest.UsageError(f"Docker node has multiple or wrong shards: {item.nodeid}")
    item.add_marker(expected)


@pytest.fixture(autouse=True)
def _hermetic_structural_gates(request, monkeypatch):
    """Keep unit tests of other gates hermetic.

    The API-existence lint and the security gate are required structural gates
    that shell out (PHPStan / phpcs). Each is independently stubbed to `skip`
    unless the test opts in with its own marker, so every non-gate test stays
    deterministic and toolchain-independent. The two are gated separately: an
    `real_api_lint` test still gets the security gate stubbed (and vice versa),
    so neither gate's integration tests are perturbed by the other.
    """
    import validate_wordpress_artifact as oracle

    if not request.node.get_closest_marker("real_api_lint"):

        def _stubbed_check_api_existence(path, timeout_sec=120):
            return (
                oracle.skip_check(
                    "api_existence",
                    "api-existence lint stubbed in unit tests (@pytest.mark.real_api_lint opts out)",
                ),
                None,
            )

        monkeypatch.setattr(oracle, "check_api_existence", _stubbed_check_api_existence)

    if not request.node.get_closest_marker("real_security_gate"):

        def _stubbed_check_security_gate(path, timeout_sec=120):
            return (
                oracle.skip_check(
                    "security_gate",
                    "security gate stubbed in unit tests (@pytest.mark.real_security_gate opts out)",
                ),
                None,
            )

        monkeypatch.setattr(oracle, "check_security_gate", _stubbed_check_security_gate)

    yield
