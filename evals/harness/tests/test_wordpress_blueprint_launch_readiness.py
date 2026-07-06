"""Tests for WordPress Blueprint launch-readiness preflight."""

from __future__ import annotations

import json

import audit_wordpress_blueprint_launch_readiness as audit


def write_blueprint(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_blueprint_without_vfs_payloads_gets_fragment_launch_url(tmp_path):
    blueprint = tmp_path / "fixture-a" / "generated-blueprint" / "blueprint.json"
    write_blueprint(
        blueprint,
        {
            "landingPage": "/wp-admin/",
            "steps": [{"step": "login", "username": "admin"}],
        },
    )

    result = audit.audit_blueprint(blueprint)

    assert result.status == "ready_for_manual_launch"
    assert result.launch_method == "url-fragment"
    assert result.launch_url.startswith("https://playground.wordpress.net/#")
    assert result.missing_vfs_payloads == []


def test_blueprint_with_missing_vfs_payload_is_blocked(tmp_path):
    blueprint = tmp_path / "fixture-a" / "generated-blueprint" / "blueprint.json"
    write_blueprint(
        blueprint,
        {
            "landingPage": "/wp-admin/",
            "steps": [
                {
                    "step": "installPlugin",
                    "pluginData": {
                        "resource": "vfs",
                        "path": "/wordpress/wp-content/uploads/acme.zip",
                    },
                }
            ],
        },
    )

    result = audit.audit_blueprint(blueprint)

    assert result.status == "blocked"
    assert result.launch_method == "requires-vfs-payloads"
    assert result.missing_vfs_payloads == ["/wordpress/wp-content/uploads/acme.zip"]


def test_blueprint_with_asset_root_can_satisfy_vfs_payload(tmp_path):
    blueprint = tmp_path / "fixture-a" / "generated-blueprint" / "blueprint.json"
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "acme.zip").write_bytes(b"zip-placeholder")
    write_blueprint(
        blueprint,
        {
            "landingPage": "/wp-admin/",
            "steps": [
                {
                    "step": "installPlugin",
                    "pluginData": {
                        "resource": "vfs",
                        "path": "/wordpress/wp-content/uploads/acme.zip",
                    },
                }
            ],
        },
    )

    result = audit.audit_blueprint(blueprint, asset_root=assets)

    assert result.status == "ready_for_manual_launch"
    assert result.missing_vfs_payloads == []
