import dataclasses, io, os, socket, stat, sys, tarfile, threading
from pathlib import Path
import pytest
HARNESS=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(HARNESS))
import artifact_staging as staging
import measure_artifact_staging
import sandbox_source_proof
import workspace_lease
import certify_wordpress_executor_artifact as certifier
import run_wordpress_runtime_smoke as runtime_smoke

def cleanup(result): workspace_lease.cleanup(result.lease)

def test_stage_tree_copies_regular_files_into_fresh_lease(tmp_path):
    source=tmp_path/"source"; (source/"nested").mkdir(parents=True); (source/"nested/a.txt").write_text("alive")
    result=staging.stage_tree(source,tmp_path/"leases")
    try:
        assert (result.root/"nested/a.txt").read_text()=="alive"
        assert result.manifest[0].sha256=="135fc7a09da25f03e44f7a2c700efd4a9d0a989af4d4704eabfe9ada71b26590"
    finally: cleanup(result)

def test_staging_measurement_emits_finite_metrics_under_watchdog():
    packet=measure_artifact_staging.measure(1024*1024,100,10)
    assert packet["status"]=="pass" and packet["snapshot_entries"]==100
    assert packet["scan_handoff_entries"]==100
    assert packet["elapsed_sec"]>=0 and packet["peak_bytes"]>=0

def test_staging_measurement_rejects_values_above_reviewed_limits():
    with pytest.raises(ValueError,match="bytes"):
        measure_artifact_staging.measure(staging.MAX_FILE_BYTES+1,1,10)
    with pytest.raises(ValueError,match="entries"):
        measure_artifact_staging.measure(1,staging.MAX_ENTRIES+1,10)
    with pytest.raises(ValueError,match="watchdog"):
        measure_artifact_staging.measure(1,1,measure_artifact_staging.MAX_WATCHDOG_SEC+1)

def test_held_stage_clone_is_fd_rooted_across_aba_swap(tmp_path):
    source=tmp_path/"source"; source.mkdir(); (source/"value").write_text("safe")
    external=tmp_path/"external"; external.mkdir(); (external/"value").write_text("SECRET")
    staged=staging.stage_tree(source,tmp_path/"input")
    forged=dataclasses.replace(staged)
    with pytest.raises(ValueError,match="authentic"):
        with staging.hold_staged_tree(forged): pass
    moved=staged.lease.root/"held-artifact"; clone=None
    try:
        with staging.hold_staged_tree(staged) as held:
            staged.root.rename(moved); staged.root.symlink_to(external,target_is_directory=True)
            clone=staging.stage_held_tree(held,tmp_path/"clone")
        assert (clone.root/"value").read_text()=="safe"
        assert clone.role is staging.StageRole.CALLER_INPUT
        assert clone.lease.purpose is workspace_lease.WorkspacePurpose.ARTIFACT_EXECUTION
    finally:
        if staged.root.is_symlink(): staged.root.unlink()
        if moved.exists(): moved.rename(staged.root)
        if clone is not None: cleanup(clone)
        cleanup(staged)

def test_public_staging_apis_cannot_issue_privileged_roles(tmp_path):
    source=tmp_path/"source"; source.mkdir(); (source/"value").write_text("safe")
    staged=staging.stage_tree(source,tmp_path/"input")
    forged=dataclasses.replace(staged,role=staging.StageRole.SANDBOX_OUTPUT)
    try:
        with pytest.raises(TypeError): staging.stage_tree(source,tmp_path/"tree",role=staging.StageRole.SANDBOX_OUTPUT)
        with pytest.raises(TypeError): staging.stage_snapshot([],tmp_path/"snapshot",role=staging.StageRole.SCAN_HANDOFF)
        with staging.hold_staged_tree(staged) as held:
            with pytest.raises(TypeError): staging.stage_held_tree(held,tmp_path/"held",role=staging.StageRole.SYNTHESIZED_RUNTIME)
        assert not staging.has_stage_authority(forged,staging.StageRole.SANDBOX_OUTPUT)
    finally: cleanup(staged)

def test_snapshot_reuses_shared_proof_budget_without_extra_reproofs(tmp_path,monkeypatch):
    source=tmp_path/"source"; source.mkdir(); (source/"value").write_text("safe")
    staged=staging.stage_tree(source,tmp_path/"input"); calls=[]
    original=sandbox_source_proof.prove_artifact
    def prove(descriptor,budget,policy="canonical"):
        calls.append(budget)
        return original(descriptor,budget,policy)
    monkeypatch.setattr(sandbox_source_proof,"prove_artifact",prove)
    try:
        with staging.hold_staged_tree(staged) as held:
            assert len(staging.snapshot_held_tree(held))==1
            assert held.proof_budget.artifact_passes==2
        assert len(calls)==2 and calls[0] is calls[1]
        assert held.proof_budget.artifact_passes==3
    finally: cleanup(staged)

def test_held_snapshot_and_reproof_share_six_pass_ceiling(tmp_path):
    source=tmp_path/"source"; source.mkdir(); (source/"value").write_text("safe")
    staged=staging.stage_tree(source,tmp_path/"input")
    try:
        with pytest.raises(RuntimeError,match="pass budget"):
            with staging.hold_staged_tree(staged) as held:
                for _index in range(5): staging.snapshot_held_tree(held)
    finally: cleanup(staged)

def test_staged_modes_are_normalized_not_preserved(tmp_path):
    source=tmp_path/"source"; source.mkdir(); regular=source/"regular"; executable=source/"executable"
    regular.write_text("r"); executable.write_text("x"); regular.chmod(0o666); executable.chmod(0o777)
    result=staging.stage_tree(source,tmp_path/"leases")
    try:
        assert stat.S_IMODE((result.root/"regular").stat().st_mode)==0o600
        assert stat.S_IMODE((result.root/"executable").stat().st_mode)==0o700
        assert {entry.path:entry.mode_class for entry in result.manifest}=={"executable":"executable","regular":"regular"}
    finally: cleanup(result)

def test_manifest_sha256_is_order_independent_and_binds_every_field():
    first=staging.ManifestEntry("a.php","regular",3,"1"*64); second=staging.ManifestEntry("bin/run","executable",4,"2"*64)
    digest=staging.manifest_sha256((second,first))
    assert digest==staging.manifest_sha256((first,second))
    assert len(digest)==64
    for changed in (
        staging.ManifestEntry("b.php",first.mode_class,first.size,first.sha256),
        staging.ManifestEntry(first.path,"executable",first.size,first.sha256),
        staging.ManifestEntry(first.path,first.mode_class,4,first.sha256),
        staging.ManifestEntry(first.path,first.mode_class,first.size,"3"*64),
    ):
        assert staging.manifest_sha256((changed,second))!=digest

def test_execution_closure_ignore_is_one_canonical_object():
    assert certifier.EXECUTION_CLOSURE_IGNORE is staging.EXECUTION_CLOSURE_IGNORE
    assert runtime_smoke.EXECUTION_CLOSURE_IGNORE is staging.EXECUTION_CLOSURE_IGNORE

def test_symlink_secret_hardlink_and_dependency_roots_rejected(tmp_path):
    source=tmp_path/"source"; source.mkdir(); secret=tmp_path/"secret"; secret.write_text("secret")
    (source/"link").symlink_to(secret)
    with pytest.raises(ValueError,match="symlink"): staging.stage_tree(source,tmp_path/"l1")
    (source/"link").unlink(); (source/"a").write_text("x"); os.link(source/"a",source/"b")
    with pytest.raises(ValueError,match="hardlink"): staging.stage_tree(source,tmp_path/"l2")
    (source/"b").unlink(); (source/"node_modules").mkdir()
    with pytest.raises(ValueError,match="dependency root"): staging.stage_tree(source,tmp_path/"l3")

def test_fifo_and_socket_rejected(tmp_path):
    source=tmp_path/"source"; source.mkdir(); fifo=source/"fifo"; os.mkfifo(fifo)
    with pytest.raises(ValueError,match="special"): staging.stage_tree(source,tmp_path/"l1")
    fifo.unlink(); sock=socket.socket(socket.AF_UNIX)
    try: sock.bind(str(source/"socket"))
    except OSError: sock.close(); pytest.skip("platform Unix socket path limit prevents fixture")
    try:
        with pytest.raises(ValueError,match="special"): staging.stage_tree(source,tmp_path/"l2")
    finally: sock.close()

def test_bounds_depth_count_file_and_total(tmp_path,monkeypatch):
    source=tmp_path/"source"; source.mkdir(); (source/"a").write_bytes(b"1234")
    monkeypatch.setattr(staging,"MAX_FILE_BYTES",3)
    with pytest.raises(ValueError,match="file exceeds"): staging.stage_tree(source,tmp_path/"l1")
    monkeypatch.setattr(staging,"MAX_FILE_BYTES",10); monkeypatch.setattr(staging,"MAX_TOTAL_BYTES",3)
    with pytest.raises(ValueError,match="exceeds bounds"): staging.stage_tree(source,tmp_path/"l2")
    monkeypatch.setattr(staging,"MAX_TOTAL_BYTES",100); monkeypatch.setattr(staging,"MAX_ENTRIES",0)
    with pytest.raises(ValueError,match="entry bounds"): staging.stage_tree(source,tmp_path/"l3")
    monkeypatch.setattr(staging,"MAX_ENTRIES",10); monkeypatch.setattr(staging,"MAX_DEPTH",0); (source/"nested").mkdir()
    with pytest.raises(ValueError,match="depth"): staging.stage_tree(source,tmp_path/"l4")

def test_post_command_dependency_root_is_not_descended_but_must_be_real(tmp_path):
    source=tmp_path/"source"; source.mkdir(); modules=source/"node_modules"; modules.mkdir(); (modules/"link").symlink_to("../secret")
    assert staging.snapshot_regular_tree(source,dependency_policy="post")==[]
    modules.rename(source/"real"); (source/"node_modules").symlink_to("real",target_is_directory=True)
    with pytest.raises(ValueError,match="dependency root"): staging.snapshot_regular_tree(source,dependency_policy="post")

def test_canonical_digest_includes_vendor_while_staging_rejects_it(tmp_path):
    source=tmp_path/"source"; source.mkdir(); (source/"base").write_text("base")
    before=staging.digest_regular_tree(source); vendor=source/"vendor"; vendor.mkdir(); (vendor/"package").write_text("dependency")
    assert staging.digest_regular_tree(source)!=before
    with pytest.raises(ValueError,match="dependency root"): staging.stage_tree(source,tmp_path/"leases")

def test_stage_rejects_symlink_at_ignored_git_name(tmp_path):
    source=tmp_path/"source"; source.mkdir(); target=tmp_path/"target"; target.mkdir(); (source/".git").symlink_to(target,target_is_directory=True)
    with pytest.raises(ValueError,match="ignored root"): staging.stage_tree(source,tmp_path/"leases")

def test_ancestor_swap_uses_held_fd_not_sentinel(tmp_path):
    source=tmp_path/"source"; source.mkdir(); (source/"value").write_text("safe")
    sentinel=tmp_path/"sentinel"; sentinel.mkdir(); (sentinel/"value").write_text("SECRET")
    moved=tmp_path/"moved"; fired=False
    def barrier(relative):
        nonlocal fired
        if not fired and relative==Path():
            fired=True; source.rename(moved); source.symlink_to(sentinel,target_is_directory=True)
    kind,snapshot=staging.snapshot_regular_tree_with_kind(source,barrier=barrier)
    assert kind=="directory" and snapshot[0][1]==b"safe"

def test_final_root_stat_is_dirfd_relative_and_root_swap_fails_closed(tmp_path,monkeypatch):
    source=tmp_path/"source"; source.mkdir(); (source/"value").write_text("safe")
    sentinel=tmp_path/"sentinel"; sentinel.mkdir(); (sentinel/"value").write_text("SECRET")
    moved=tmp_path/"moved"; original=staging.os.stat; observed=[]
    def swap(name,*args,**kwargs):
        if name=="source" and kwargs.get("dir_fd") is not None and not observed:
            observed.append((name,kwargs["dir_fd"])); info=original(name,*args,**kwargs)
            source.rename(moved); source.symlink_to(sentinel,target_is_directory=True); return info
        return original(name,*args,**kwargs)
    monkeypatch.setattr(staging.os,"stat",swap)
    with pytest.raises(OSError): staging.snapshot_regular_tree(source)
    assert observed and b"SECRET" not in [content for _path,content,_info in getattr(staging,"_test_snapshot",[])]

def test_snapshot_never_path_lstats_untrusted_final(tmp_path,monkeypatch):
    source=tmp_path/"source"; source.mkdir(); (source/"value").write_text("safe")
    monkeypatch.setattr(Path,"lstat",lambda *_args,**_kwargs:(_ for _ in ()).throw(AssertionError("path lstat used")))
    assert staging.snapshot_regular_tree(source)[0][1]==b"safe"

def test_symlinked_intermediate_parent_is_rejected(tmp_path):
    real=tmp_path/"real"; real.mkdir(); source=real/"source"; source.mkdir(); (source/"value").write_text("safe")
    linked=tmp_path/"linked"; linked.symlink_to(real,target_is_directory=True)
    with pytest.raises(OSError): staging.snapshot_regular_tree(linked/"source")

def test_child_opens_are_descriptor_relative(tmp_path,monkeypatch):
    source=tmp_path/"source"; source.mkdir(); (source/"a").write_text("x")
    original=staging.os.open; observed=[]
    def spy(path,flags,*args,**kwargs):
        if kwargs.get("dir_fd") is not None: observed.append(path); assert not os.path.isabs(path)
        return original(path,flags,*args,**kwargs)
    monkeypatch.setattr(staging.os,"open",spy)
    staging.snapshot_regular_tree(source)
    assert "a" in observed

def test_hardlink_created_between_stat_and_open_is_rejected(tmp_path,monkeypatch):
    source=tmp_path/"source"; source.mkdir(); target=source/"a"; target.write_text("safe")
    original=staging.os.open; fired=False
    def race(name,flags,*args,**kwargs):
        nonlocal fired
        if name=="a" and kwargs.get("dir_fd") is not None and not fired:
            fired=True; os.link(target,source/"hardlink")
        return original(name,flags,*args,**kwargs)
    monkeypatch.setattr(staging.os,"open",race)
    with pytest.raises(ValueError,match="changed while opening"): staging.snapshot_regular_tree(source)

def test_depth_limit_is_exact_per_entry(tmp_path,monkeypatch):
    monkeypatch.setattr(staging,"MAX_DEPTH",2)
    exact=tmp_path/"exact"; (exact/"a").mkdir(parents=True); (exact/"a/file").write_text("ok")
    assert staging.snapshot_regular_tree(exact)[0][1]==b"ok"
    beyond=tmp_path/"beyond"; (beyond/"a/b").mkdir(parents=True); (beyond/"a/b/file").write_text("no")
    with pytest.raises(ValueError,match="depth"): staging.snapshot_regular_tree(beyond)

def test_stage_destination_swap_fails_without_writing_sentinel(tmp_path,monkeypatch):
    source=tmp_path/"source"; source.mkdir(); (source/"a").write_text("safe")
    sentinel=tmp_path/"sentinel"; sentinel.mkdir(); secret=sentinel/"secret"; secret.write_text("SECRET")
    original=staging.os.stat; fired=False
    def swap(name,*args,**kwargs):
        nonlocal fired
        if name=="artifact" and kwargs.get("dir_fd") is not None and not fired:
            fired=True
            os.rename("artifact","moved",src_dir_fd=kwargs["dir_fd"],dst_dir_fd=kwargs["dir_fd"])
            os.symlink(sentinel,"artifact",target_is_directory=True,dir_fd=kwargs["dir_fd"]); return original(name,*args,**kwargs)
        return original(name,*args,**kwargs)
    monkeypatch.setattr(staging.os,"stat",swap)
    with pytest.raises(ValueError,match="destination root changed"): staging.stage_tree(source,tmp_path/"leases")
    assert secret.read_text()=="SECRET"

def test_stage_rejects_raced_extra_destination_directory(tmp_path,monkeypatch):
    source=tmp_path/"source"; source.mkdir(); (source/"a").write_text("safe")
    original=staging._manifest_from_fd
    def inject(root_fd,*args,**kwargs):
        manifest=original(root_fd,*args,**kwargs); os.mkdir("extra",0o700,dir_fd=root_fd); return manifest
    monkeypatch.setattr(staging,"_manifest_from_fd",inject)
    with pytest.raises(ValueError,match="filesystem entry mismatch"): staging.stage_tree(source,tmp_path/"leases")

def test_stage_tree_dual_failure_preserves_primary_and_retained_lease(tmp_path,monkeypatch):
    source=tmp_path/"source"; source.mkdir(); (source/"plugin.php").write_text("<?php")
    parent=tmp_path/"leases"; original_cleanup=staging.workspace_lease.cleanup
    monkeypatch.setattr(staging,"_manifest_from_fd",lambda *_args,**_kwargs:(_ for _ in ()).throw(RuntimeError("manifest failed")))
    monkeypatch.setattr(staging.workspace_lease,"cleanup",lambda _lease:(_ for _ in ()).throw(workspace_lease.WorkspaceCleanupError("cleanup failed")))
    with pytest.raises(staging.StagingCleanupError,match="manifest failed.*cleanup") as caught:
        staging.stage_tree(source,parent)
    error=caught.value; receipt=error.receipt
    assert isinstance(error.primary,RuntimeError) and str(error.primary)=="manifest failed"
    assert receipt.component=="caller_input" and receipt.issuer is staging.StageRole.CALLER_INPUT
    assert receipt.state=="retained" and receipt.exists and receipt.live and receipt.error
    assert receipt.recovery_path and Path(receipt.recovery_path).exists()
    monkeypatch.setattr(staging.workspace_lease,"cleanup",original_cleanup)
    original_cleanup(receipt.lease)
    live_before=set(workspace_lease._LIVE_LEASES)
    with pytest.raises(RuntimeError,match="manifest failed"):
        staging.stage_tree(source,parent)
    assert set(workspace_lease._LIVE_LEASES)==live_before and not any(parent.iterdir())

def tar_bytes(entries):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode="w") as archive:
        for name,data,kind in entries:
            info=tarfile.TarInfo(name); info.size=len(data)
            if kind=="symlink": info.type=tarfile.SYMTYPE; info.linkname="target"; info.size=0
            archive.addfile(info,io.BytesIO(data) if info.isfile() else None)
    stream.seek(0); return stream

def test_bounded_tar_import_success_and_link_traversal_rejection(tmp_path):
    result=staging.import_tar_stream(tar_bytes([("nested/a",b"ok","file")]),tmp_path/"ok")
    try: assert (result.root/"nested/a").read_bytes()==b"ok"
    finally: cleanup(result)
    with pytest.raises(ValueError,match="unsafe archive path"): staging.import_tar_stream(tar_bytes([("../escape",b"x","file")]),tmp_path/"bad")
    with pytest.raises(ValueError,match="link or special"): staging.import_tar_stream(tar_bytes([("link",b"","symlink")]),tmp_path/"link")

def test_tar_directory_root_member_is_accepted_only_as_directory(tmp_path):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode="w") as archive:
        root=tarfile.TarInfo("."); root.type=tarfile.DIRTYPE; archive.addfile(root)
        item=tarfile.TarInfo("a"); item.size=2; archive.addfile(item,io.BytesIO(b"ok"))
    stream.seek(0); result=staging.import_tar_stream(stream,tmp_path/"root-dir")
    try: assert (result.root/"a").read_bytes()==b"ok"
    finally: cleanup(result)
    bad=io.BytesIO()
    with tarfile.open(fileobj=bad,mode="w") as archive:
        item=tarfile.TarInfo("."); item.size=1; archive.addfile(item,io.BytesIO(b"x"))
    bad.seek(0)
    with pytest.raises(ValueError,match="root member must be a directory"): staging.import_tar_stream(bad,tmp_path/"root-file")
    duplicate=io.BytesIO()
    with tarfile.open(fileobj=duplicate,mode="w") as archive:
        for name in (".","./"):
            item=tarfile.TarInfo(name); item.type=tarfile.DIRTYPE; archive.addfile(item)
    duplicate.seek(0)
    with pytest.raises(ValueError,match="duplicate archive member"): staging.import_tar_stream(duplicate,tmp_path/"duplicate-root")

def test_tar_import_destination_opens_are_descriptor_relative(tmp_path,monkeypatch):
    original=staging.os.open; original_mkdir=staging.os.mkdir; observed=[]
    def spy(path,flags,*args,**kwargs):
        if kwargs.get("dir_fd") is not None: observed.append(path); assert not os.path.isabs(path)
        return original(path,flags,*args,**kwargs)
    monkeypatch.setattr(staging.os,"open",spy)
    def mkdir_spy(path,*args,**kwargs):
        if kwargs.get("dir_fd") is not None: observed.append(path); assert not os.path.isabs(path)
        return original_mkdir(path,*args,**kwargs)
    monkeypatch.setattr(staging.os,"mkdir",mkdir_spy)
    result=staging.import_tar_stream(tar_bytes([("nested/a",b"ok","file")]),tmp_path/"leases")
    try: assert {"artifact","nested","a"} <= set(observed)
    finally: cleanup(result)

def test_casefold_collision_rejected_when_filesystem_supports_fixture(tmp_path):
    source=tmp_path/"source"; source.mkdir(); (source/"A").write_text("a"); (source/"a").write_text("b")
    if len(list(source.iterdir()))<2: pytest.skip("case-insensitive filesystem cannot construct fixture")
    with pytest.raises(ValueError,match="case-fold"): staging.stage_tree(source,tmp_path/"leases")

def test_tar_import_enforces_streamed_size_limit(tmp_path,monkeypatch):
    monkeypatch.setattr(staging,"MAX_TOTAL_BYTES",2)
    with pytest.raises(ValueError,match="archive exceeds"): staging.import_tar_stream(tar_bytes([("a",b"123","file")]),tmp_path/"bad")

def test_entire_valid_tar_is_transport_bounded_before_member_acceptance(tmp_path,monkeypatch):
    monkeypatch.setattr(staging,"MAX_ARCHIVE_STREAM_BYTES",511)
    with pytest.raises(ValueError,match="transport bound"):
        staging.import_tar_stream(tar_bytes([("a",b"ok","file")]),tmp_path/"bounded")

def test_compressed_tar_is_rejected(tmp_path):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode="w:gz") as archive:
        info=tarfile.TarInfo("a"); info.size=2; archive.addfile(info,io.BytesIO(b"ok"))
    stream.seek(0)
    with pytest.raises((tarfile.ReadError,ValueError)):
        staging.import_tar_stream(stream,tmp_path/"compressed")

def test_header_flood_hits_transport_bound(tmp_path,monkeypatch):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode="w",format=tarfile.PAX_FORMAT) as archive:
        for index in range(20):
            info=tarfile.TarInfo(f"header-{index}"); info.size=0; archive.addfile(info)
    stream.seek(0); monkeypatch.setattr(staging,"MAX_ARCHIVE_STREAM_BYTES",1024)
    with pytest.raises(ValueError,match="transport bound"):
        staging.import_tar_stream(stream,tmp_path/"headers")

def test_archive_prefix_alias_and_file_directory_conflicts_rejected(tmp_path):
    with pytest.raises(ValueError,match="prefix alias"):
        staging.import_tar_stream(tar_bytes([("A/file",b"x","file"),("a/other",b"y","file")]),tmp_path/"alias")
    with pytest.raises(ValueError,match="kind conflict"):
        staging.import_tar_stream(tar_bytes([("a",b"x","file"),("a/child",b"y","file")]),tmp_path/"kind")

def test_dependency_descendants_are_consumed_but_materialize_empty_root(tmp_path):
    stream=tar_bytes([("node_modules/pkg/file",b"dependency","file"),("node_modules/.bin/tool",b"","symlink")])
    result=staging.import_tar_stream(stream,tmp_path/"deps")
    try:
        assert (result.root/"node_modules").is_dir()
        assert list((result.root/"node_modules").iterdir())==[]
        assert result.manifest==()
    finally: cleanup(result)
    with pytest.raises(ValueError,match="dependency archive root"):
        staging.import_tar_stream(tar_bytes([("vendor",b"file","file")]),tmp_path/"bad-root")

def test_strict_manifest_verifier_creates_no_lease_or_files_and_rejects_dependencies(tmp_path):
    before=set(workspace_lease._LIVE_LEASES)
    proof=staging.verify_tar_stream_manifest(tar_bytes([("dir/a",b"ok","file")]))
    assert proof.manifest[0].path=="dir/a"
    assert proof.path_kinds==(("dir","directory"),("dir/a","file"))
    assert set(workspace_lease._LIVE_LEASES)==before and list(tmp_path.iterdir())==[]
    injected=tar_bytes([("a",b"ok","file"),("node_modules/evil",b"bad","file")])
    with pytest.raises(ValueError,match="dependency archive path forbidden"):
        staging.verify_tar_stream_manifest(injected)
    assert set(workspace_lease._LIVE_LEASES)==before and list(tmp_path.iterdir())==[]

def test_strict_manifest_verifier_exposes_extra_graph_entries():
    proof=staging.verify_tar_stream_manifest(tar_bytes([("a",b"ok","file"),("extra/",b"","file")]))
    assert ("extra","file") in proof.path_kinds

def test_import_manifest_is_rebuilt_and_exact_compared(tmp_path,monkeypatch):
    monkeypatch.setattr(staging,"_manifest_from_fd",lambda *_args,**_kwargs:())
    with pytest.raises(ValueError,match="manifest mismatch"):
        staging.import_tar_stream(tar_bytes([("a",b"x","file")]),tmp_path/"mismatch")

def test_import_dual_failure_preserves_primary_and_sandbox_output_receipt(tmp_path,monkeypatch):
    parent=tmp_path/"leases"; original_cleanup=staging.workspace_lease.cleanup
    monkeypatch.setattr(staging,"_finalize_archive",lambda *_args,**_kwargs:(_ for _ in ()).throw(RuntimeError("import verification failed")))
    monkeypatch.setattr(staging.workspace_lease,"cleanup",lambda _lease:(_ for _ in ()).throw(workspace_lease.WorkspaceCleanupError("cleanup failed")))
    with pytest.raises(staging.StagingCleanupError,match="import verification failed.*cleanup") as caught:
        staging.import_tar_stream(tar_bytes([("a",b"ok","file")]),parent)
    error=caught.value; receipt=error.receipt
    assert isinstance(error.primary,RuntimeError) and str(error.primary)=="import verification failed"
    assert receipt.component=="sandbox_output" and receipt.issuer is staging.StageRole.SANDBOX_OUTPUT
    assert receipt.state=="retained" and receipt.exists and receipt.live and receipt.error
    assert receipt.recovery_path and Path(receipt.recovery_path).exists()
    monkeypatch.setattr(staging.workspace_lease,"cleanup",original_cleanup)
    original_cleanup(receipt.lease)
    live_before=set(workspace_lease._LIVE_LEASES)
    with pytest.raises(RuntimeError,match="import verification failed"):
        staging.import_tar_stream(tar_bytes([("a",b"ok","file")]),parent)
    assert set(workspace_lease._LIVE_LEASES)==live_before and not any(parent.iterdir())


def test_held_tree_accepts_one_caller_owned_absolute_proof_deadline(tmp_path):
    source=tmp_path/"source"; source.mkdir(); (source/"plugin.php").write_text("<?php")
    staged=staging.stage_tree(source,tmp_path/"leases")
    proof_deadline=sandbox_source_proof.time.monotonic()+60
    try:
        with staging.hold_staged_tree(staged,proof_deadline=proof_deadline) as held:
            assert held.proof_budget.deadline==proof_deadline
    finally:
        staging.cleanup_staged_tree(staged)
