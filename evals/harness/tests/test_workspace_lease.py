import os
import stat
from pathlib import Path

import pytest

import workspace_lease


@pytest.mark.parametrize("purpose", list(workspace_lease.WorkspacePurpose))
@pytest.mark.parametrize("mask", [0o000, 0o022, 0o077, 0o777])
def test_every_lease_purpose_is_exact_under_hostile_umask(tmp_path, purpose, mask):
    previous = os.umask(mask)
    try:
        lease = workspace_lease.create_ephemeral(tmp_path, purpose)
        root = lease.root.lstat(); sentinel = (lease.root / workspace_lease.SENTINEL_NAME).lstat()
        assert stat.S_ISDIR(root.st_mode) and stat.S_IMODE(root.st_mode) == 0o700
        assert (root.st_uid, root.st_gid) == (os.getuid(), os.getgid())
        assert stat.S_ISREG(sentinel.st_mode) and stat.S_IMODE(sentinel.st_mode) == 0o600 and sentinel.st_nlink == 1
        assert (sentinel.st_uid, sentinel.st_gid) == (os.getuid(), os.getgid())
        lease_fd = workspace_lease._open_directory_nofollow(lease.root)
        artifact_fd = workspace_lease.create_secure_directory(lease_fd, "artifact")
        proxy_fd = workspace_lease.create_secure_file(lease_fd, "proxy.py", 0o400)
        artifact = os.fstat(artifact_fd); proxy = os.fstat(proxy_fd)
        assert stat.S_IMODE(artifact.st_mode) == 0o700 and (artifact.st_uid, artifact.st_gid) == (os.getuid(), os.getgid())
        assert stat.S_IMODE(proxy.st_mode) == 0o400 and proxy.st_nlink == 1 and (proxy.st_uid, proxy.st_gid) == (os.getuid(), os.getgid())
        os.close(proxy_fd); os.close(artifact_fd); os.close(lease_fd)
    finally:
        os.umask(previous)
    workspace_lease.cleanup(lease)


def test_mode_zero_root_is_normalized_before_ordinary_open(tmp_path, monkeypatch):
    events = []; real_chmod = os.chmod; real_open = os.open
    def observed_chmod(path, mode, **kwargs):
        if path == "ordered":
            events.append("chmod")
            before = os.stat(path, dir_fd=kwargs["dir_fd"], follow_symlinks=False)
            assert stat.S_IMODE(before.st_mode) == 0
        return real_chmod(path, mode, **kwargs)
    def observed_open(path, flags, *args, **kwargs):
        if path == "ordered": events.append("open")
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(workspace_lease.os, "chmod", observed_chmod)
    monkeypatch.setattr(workspace_lease.os, "open", observed_open)
    previous = os.umask(0o777)
    try: lease = workspace_lease.create_named(tmp_path, "ordered", workspace_lease.WorkspacePurpose.RUNTIME)
    finally: os.umask(previous)
    try: assert events[:2] == ["chmod", "open"]
    finally: workspace_lease.cleanup(lease)


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
    existing=tmp_path / "existing"; existing.mkdir(); (existing/"keep.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        workspace_lease.create_named(tmp_path, "existing", workspace_lease.WorkspacePurpose.RESULT)
    assert (existing/"keep.txt").read_text()=="keep"


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


def test_public_safe_name_validator_matches_factory_grammar():
    workspace_lease.validate_safe_name("repair-run_1.2")
    for unsafe in ("", ".", "..", "a/b", "a\\b", "/absolute", "x" * 129):
        with pytest.raises(ValueError):
            workspace_lease.validate_safe_name(unsafe)


def test_named_lease_rejects_symlinked_parent_ancestor(tmp_path):
    real = tmp_path / "real"; real.mkdir()
    linked = tmp_path / "linked"; linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink component"):
        workspace_lease.create_named(linked / "results", "run", workspace_lease.WorkspacePurpose.RESULT)
    assert list(real.iterdir()) == []


def test_ephemeral_lease_rejects_symlinked_parent_ancestor(tmp_path):
    real = tmp_path / "real"; real.mkdir()
    linked = tmp_path / "linked"; linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink component"):
        workspace_lease.create_ephemeral(linked, workspace_lease.WorkspacePurpose.RUNTIME)
