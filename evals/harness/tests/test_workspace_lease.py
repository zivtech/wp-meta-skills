from pathlib import Path

import pytest

import workspace_lease


def test_ephemeral_lease_creates_unique_child_and_cleanup_preserves_parent(tmp_path):
    marker = tmp_path / "caller.txt"
    marker.write_text("keep", encoding="utf-8")
    lease = workspace_lease.create_ephemeral(tmp_path, workspace_lease.WorkspacePurpose.RUNTIME)
    assert lease.root.parent == tmp_path.resolve()
    assert lease.root != tmp_path
    workspace_lease.cleanup(lease)
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not lease.root.exists()


def test_named_lease_refuses_existing_directory(tmp_path):
    (tmp_path / "existing").mkdir()
    with pytest.raises(FileExistsError):
        workspace_lease.create_named(tmp_path, "existing", workspace_lease.WorkspacePurpose.RESULT)


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\\b", "/tmp/x", "C:\\x", " space"])
def test_named_lease_rejects_unsafe_names(tmp_path, name):
    with pytest.raises(ValueError):
        workspace_lease.create_named(tmp_path, name, workspace_lease.WorkspacePurpose.RESULT)


def test_cleanup_refuses_mismatched_and_missing_sentinel(tmp_path):
    lease = workspace_lease.create_ephemeral(tmp_path, workspace_lease.WorkspacePurpose.RUNTIME)
    sentinel = lease.root / workspace_lease.SENTINEL_NAME
    sentinel.write_text("wrong\nruntime\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not match"):
        workspace_lease.cleanup(lease)
    sentinel.unlink()
    with pytest.raises(workspace_lease.WorkspaceCleanupError, match="cleanup validation failed"):
        workspace_lease.cleanup(lease)


def test_cleanup_refuses_reconstructed_lease_with_all_visible_fields(tmp_path):
    lease = workspace_lease.create_ephemeral(tmp_path, workspace_lease.WorkspacePurpose.RUNTIME)
    reconstructed = workspace_lease.WorkspaceLease(
        lease.root, lease.caller_parent, lease.purpose, lease.lease_id, lease.cleanup_allowed
    )
    with pytest.raises(workspace_lease.WorkspaceCleanupError, match="factory-issued live authority"):
        workspace_lease.cleanup(reconstructed)
    assert lease.root.is_dir()
    workspace_lease.cleanup(lease)


def test_cleanup_refuses_wrong_sentinel_mode(tmp_path):
    lease = workspace_lease.create_ephemeral(tmp_path, workspace_lease.WorkspacePurpose.RUNTIME)
    (lease.root / workspace_lease.SENTINEL_NAME).chmod(0o644)
    with pytest.raises(RuntimeError, match="mode-0600"):
        workspace_lease.cleanup(lease)


def test_cleanup_refuses_symlink_root(tmp_path):
    lease = workspace_lease.create_ephemeral(tmp_path, workspace_lease.WorkspacePurpose.RUNTIME)
    moved = tmp_path / "moved"
    lease.root.rename(moved)
    try:
        lease.root.symlink_to(moved, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(RuntimeError, match="real directory"):
        workspace_lease.cleanup(lease)
