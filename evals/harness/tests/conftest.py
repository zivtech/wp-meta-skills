import sys
from pathlib import Path

import pytest

# Make the harness modules importable when collected by pytest.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_api_lint: run the real API-existence lint (PHPStan subprocess) instead of the hermetic unit-test stub",
    )
    config.addinivalue_line(
        "markers",
        "real_security_gate: run the real security gate (phpcs subprocess) instead of the hermetic unit-test stub",
    )


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
