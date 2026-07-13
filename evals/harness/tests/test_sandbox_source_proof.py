import os
import stat
from pathlib import Path

import pytest

import artifact_staging
import sandbox_source_proof as proof
import workspace_lease


def _staged(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    (source / "a.txt").write_bytes(b"abc")
    nested = source / "nested"; nested.mkdir(); (nested / "run.sh").write_bytes(b"echo ok\n"); (nested / "run.sh").chmod(0o700)
    return artifact_staging.stage_tree(source, tmp_path / "leases")


def _proxy_file(tmp_path):
    path = tmp_path / "proxy.py"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    os.fchmod(descriptor, 0o400); os.write(descriptor, b"print('safe')\n"); os.close(descriptor)
    return path


def test_unified_artifact_proof_returns_identity_manifest_graph_and_totals(tmp_path):
    tree = _staged(tmp_path); descriptor = proof.open_canonical_directory(tree.root)
    try:
        observed = proof.prove_artifact(descriptor, proof.ProofBudget())
        assert observed.root.kind == "directory" and observed.root.mode == 0o700
        assert observed.manifest == tree.manifest
        assert observed.path_kinds == (("a.txt", "file"), ("nested", "directory"), ("nested/run.sh", "file"))
        assert observed.total_bytes == 11 and observed.entries == 3
    finally:
        os.close(descriptor); workspace_lease.cleanup(tree.lease)


def test_seventh_artifact_and_proxy_pass_are_rejected_without_retry(tmp_path):
    tree = _staged(tmp_path); descriptor = proof.open_canonical_directory(tree.root); budget = proof.ProofBudget()
    try:
        for _index in range(6): proof.prove_artifact(descriptor, budget)
        with pytest.raises(RuntimeError, match="pass budget"): proof.prove_artifact(descriptor, budget)
        assert budget.artifact_passes == 6
    finally:
        os.close(descriptor); workspace_lease.cleanup(tree.lease)
    path = _proxy_file(tmp_path); descriptor = proof.open_canonical_file(path); budget = proof.ProofBudget()
    try:
        for _index in range(6): proof.prove_proxy(descriptor, budget)
        with pytest.raises(RuntimeError, match="pass budget"): proof.prove_proxy(descriptor, budget)
        assert budget.proxy_passes == 6
    finally: os.close(descriptor)


@pytest.mark.parametrize("field,value", [("ARTIFACT_AGGREGATE_ENTRIES", 0), ("ARTIFACT_AGGREGATE_BYTES", 2)])
def test_artifact_aggregate_budget_blocks(field, value, tmp_path, monkeypatch):
    tree = _staged(tmp_path); descriptor = proof.open_canonical_directory(tree.root)
    monkeypatch.setattr(proof, field, value); budget = proof.ProofBudget()
    try:
        with pytest.raises(RuntimeError, match="aggregate budget"): proof.prove_artifact(descriptor, budget)
        assert budget.artifact_passes == 1
    finally:
        os.close(descriptor); workspace_lease.cleanup(tree.lease)


@pytest.mark.parametrize("field,value", [("PROXY_AGGREGATE_ENTRIES", 0), ("PROXY_AGGREGATE_BYTES", 2)])
def test_proxy_aggregate_budget_blocks(field, value, tmp_path, monkeypatch):
    path = _proxy_file(tmp_path); descriptor = proof.open_canonical_file(path)
    monkeypatch.setattr(proof, field, value); budget = proof.ProofBudget()
    try:
        with pytest.raises(RuntimeError, match="aggregate budget"): proof.prove_proxy(descriptor, budget)
        assert budget.proxy_passes == 1
    finally: os.close(descriptor)


class SequenceClock:
    def __init__(self, values): self.values = iter(values); self.last = 0
    def __call__(self):
        try: self.last = next(self.values)
        except StopIteration: pass
        return self.last


@pytest.mark.parametrize("values", [(0, 0, 181), (0, 0, 0, 0, 0, 181)])
def test_deadline_expiry_during_entry_or_file_chunk_never_retries(tmp_path, values):
    tree = _staged(tmp_path); descriptor = proof.open_canonical_directory(tree.root); budget = proof.ProofBudget(clock=SequenceClock(values))
    try:
        with pytest.raises(TimeoutError, match="deadline"): proof.prove_artifact(descriptor, budget)
        assert budget.artifact_passes == 1
    finally:
        os.close(descriptor); workspace_lease.cleanup(tree.lease)


def test_proof_rejects_hardlinks_casefold_collisions_and_symlinked_ancestor(tmp_path):
    root = tmp_path / "root"; root.mkdir(mode=0o700); root.chmod(0o700)
    first = root / "A"; first.write_text("x"); first.chmod(0o600); os.link(first, root / "hard")
    descriptor = proof.open_canonical_directory(root)
    try:
        with pytest.raises(ValueError, match="link violation"): proof.prove_artifact(descriptor, proof.ProofBudget())
    finally: os.close(descriptor)
    (root / "hard").unlink(); first.write_text("x"); first.chmod(0o600); (root / "a").write_text("y"); (root / "a").chmod(0o600)
    if len(list(root.iterdir())) < 2: pytest.skip("case-insensitive filesystem cannot construct fixture")
    descriptor = proof.open_canonical_directory(root)
    try:
        with pytest.raises(ValueError, match="case-fold"): proof.prove_artifact(descriptor, proof.ProofBudget())
    finally: os.close(descriptor)
    real = tmp_path / "real"; real.mkdir(); (tmp_path / "alias").symlink_to(real, target_is_directory=True)
    with pytest.raises(OSError): proof.open_canonical_directory(tmp_path / "alias")


def test_exclusion_policy_lstats_but_does_not_descend_dependency_roots(tmp_path):
    root = tmp_path / "artifact"; root.mkdir(mode=0o700); root.chmod(0o700)
    (root / "safe.txt").write_text("safe"); (root / "safe.txt").chmod(0o600)
    dependency = root / "node_modules"; dependency.mkdir(); dependency.chmod(0o700); (dependency / "linked").symlink_to("/etc/passwd")
    descriptor = proof.open_canonical_directory(root)
    try:
        observed = proof.prove_artifact(descriptor, proof.ProofBudget(), "exclude")
        assert observed.path_kinds == (("safe.txt", "file"),) and observed.total_bytes == 4
    finally: os.close(descriptor)
    dependency.rename(root / "saved"); (root / "node_modules").symlink_to(root / "saved", target_is_directory=True)
    descriptor = proof.open_canonical_directory(root)
    try:
        with pytest.raises(ValueError, match="real directory"): proof.prove_artifact(descriptor, proof.ProofBudget(), "exclude")
    finally: os.close(descriptor)
