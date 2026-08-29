"""Output-contract tests for the WordPress site auditor.

An auditor reports on a running site it does not control, and that report is
the only artifact it writes. Registering it here follows the prober precedent:
the one skill without a contract oracle is where the last defect reached
review.
"""

import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

import validate_wordpress_skill_output as output_oracle  # noqa: E402


AUDITOR_SAMPLE_REPORT = """## Access Tier And Authorization

Tier 1, unauthenticated public surfaces only, authorized by the site owner.
Canonical origin resolved once with `curl -sIL` reading `url_effective`, and
every later request reused that value.

## Stack

Core cross-checked at the `/wp-json/` root against `?ver=` strings on
`/wp-includes/` assets. Theme read from `/wp-content/themes/example/style.css`;
no `theme.json` present, so this is a classic theme.

## Findings

Two popup plugins are both present, observed as separate slugs under
`/wp-content/plugins/`. Their published versions come from `readme.txt`, which
states what the directory ships rather than what this site runs.

## Evidence

`/wp-json/wp/v2/types` returned three registered types. Currency measured
against `api.wordpress.org/plugins/info/1.2/` per slug and
`api.wordpress.org/core/version-check/1.7/` for core. A reader can settle the
duplicate-popup finding independently in a browser devtools network panel.

## Not Checked

Accessibility: NOT CHECKED, no browser was available in this run, so no
accessibility conformance is claimed either way. Admin-only inventory: NOT
CHECKED, the access tier was never raised, so the true installed plugin list
is unknown and this report does not claim to enumerate it.
"""


def test_auditor_contract_is_registered() -> None:
    assert "wordpress-site-audit" in output_oracle.CONTRACT_CHOICES
    assert output_oracle.CONTRACTS["wordpress-site-audit"]["role"] == "auditor"


def test_auditor_output_contract_passes_a_conforming_report() -> None:
    result = output_oracle.validate_output("wordpress-site-audit", AUDITOR_SAMPLE_REPORT)

    assert result["role"] == "auditor"
    assert result["pass"] is True, result["checks"]


def test_auditor_output_contract_fails_a_missing_heading() -> None:
    truncated = AUDITOR_SAMPLE_REPORT.replace("## Not Checked", "## Caveats")

    result = output_oracle.validate_output("wordpress-site-audit", truncated)

    assert result["pass"] is False
    assert any(
        check["id"] == "required_output_headings" and not check["passed"] for check in result["checks"]
    ), result["checks"]


def test_observed_surfaces_are_scored_for_the_auditor_alone() -> None:
    """The auditor's route list must not leak into the shared surface floor.

    Widening the shared registry to admit HTTP routes would loosen the
    exact-surface requirement for every planner and critic too, which the
    registry's own boundary note forbids. Scoring the routes role-locally is
    the reason that widening was avoided, so it is worth pinning.
    """
    auditor = output_oracle.CONTRACTS["wordpress-site-audit"]
    prober = output_oracle.CONTRACTS["wordpress-environment-probe"]

    assert auditor["observed_surfaces"], "auditor must carry its own observed surfaces"
    assert "observed_surfaces" not in prober

    routes_only = "\n".join(auditor["observed_surfaces"])
    assert output_oracle.check_exact_surfaces(routes_only, auditor).passed
    assert not output_oracle.check_exact_surfaces(routes_only, prober).passed
