import errno
import io
import os
import subprocess
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import artifact_staging
import sandbox_process_transport as transport
import workspace_lease


def request(timeout=10):
    return SimpleNamespace(timeout=timeout,stdout_limit=4096,stderr_limit=4096,result_parent=None)


def assert_reaped(process):
    assert process.poll() is not None
    with pytest.raises(ProcessLookupError): os.killpg(process.pid,0)
    assert process.stdout.closed and process.stderr.closed


def sandbox_output(tmp_path):
    source=tmp_path/"source"; source.mkdir(); (source/"plugin.php").write_text("<?php")
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode="w") as archive: archive.add(source,arcname=".")
    stream.seek(0)
    return artifact_staging.import_tar_stream(stream,tmp_path/"output",dependency_policy="strict")


@pytest.mark.parametrize("cleanup_fails",[False,True])
def test_post_import_transport_failure_preserves_only_meaningful_cleanup_receipt(tmp_path,monkeypatch,cleanup_fails):
    output=sandbox_output(tmp_path); original_cleanup=workspace_lease.cleanup
    monkeypatch.setattr(transport,"tar_command",lambda *_args:["/bin/sh","-c","exit 1"])
    if cleanup_fails:
        monkeypatch.setattr(artifact_staging.workspace_lease,"cleanup",lambda _lease:(_ for _ in ()).throw(workspace_lease.WorkspaceCleanupError("cleanup failed")))
    try:
        with pytest.raises(Exception) as caught:
            transport._tar_process("container",request(),False,lambda _stream:output,"output archive")
        current=caught.value; staging_error=None; seen=set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current,artifact_staging.StagingCleanupError): staging_error=current; break
            current=current.__cause__ or current.__context__
        if cleanup_fails:
            receipt=staging_error.receipt
            assert receipt.issuer is artifact_staging.StageRole.SANDBOX_OUTPUT
            assert receipt.state=="retained" and receipt.exists and receipt.live and receipt.error
            assert receipt.recovery_path==str(output.root)
        else:
            assert staging_error is None and output.lease.lease_id not in workspace_lease._LIVE_LEASES
    finally:
        monkeypatch.setattr(artifact_staging.workspace_lease,"cleanup",original_cleanup)
        if output.lease.lease_id in workspace_lease._LIVE_LEASES: original_cleanup(output.lease)


def test_hung_capped_process_reserves_cleanup_inside_absolute_deadline(monkeypatch):
    processes=[]; threads=[]
    real_popen=transport.subprocess.Popen; real_thread=transport.threading.Thread
    monkeypatch.setattr(transport.subprocess,"Popen",lambda *args,**kwargs:processes.append(real_popen(*args,**kwargs)) or processes[-1])
    monkeypatch.setattr(transport.threading,"Thread",lambda *args,**kwargs:threads.append(real_thread(*args,**kwargs)) or threads[-1])
    started=time.monotonic(); deadline=started+5.25
    with pytest.raises(TimeoutError,match="timed out"):
        transport.run_capped_process(["/bin/sh","-c","sleep 30"],request(),deadline=deadline)
    assert time.monotonic()<=deadline and len(processes)==1 and len(threads)==2
    assert_reaped(processes[0]); assert all(not thread.is_alive() for thread in threads)


def test_successful_main_exit_cannot_leave_owned_process_group(monkeypatch):
    processes=[]; real_popen=transport.subprocess.Popen
    monkeypatch.setattr(transport.subprocess,"Popen",lambda *args,**kwargs:processes.append(real_popen(*args,**kwargs)) or processes[-1])
    result=transport.run_capped_process(["/bin/sh","-c","sleep 30 >/dev/null 2>/dev/null &"],request(timeout=2))
    assert result["returncode"]==0 and len(processes)==1
    assert_reaped(processes[0])


def test_hung_tar_reserves_cleanup_and_joins_drain_watchdog(monkeypatch):
    processes=[]; observed={}
    real_popen=transport.subprocess.Popen; real_cleanup=transport._cleanup_transport
    monkeypatch.setattr(transport,"tar_command",lambda *_args:["/bin/sh","-c","sleep 30"])
    monkeypatch.setattr(transport.subprocess,"Popen",lambda *args,**kwargs:processes.append(real_popen(*args,**kwargs)) or processes[-1])
    def cleanup(process,threads,streams,deadline,terminate,stop=None,watchdog=None):
        observed["threads"]=threads; observed["watchdog"]=watchdog
        return real_cleanup(process,threads,streams,deadline,terminate,stop,watchdog)
    monkeypatch.setattr(transport,"_cleanup_transport",cleanup)
    started=time.monotonic(); deadline=started+5.25
    with pytest.raises((RuntimeError,TimeoutError),match="deadline|transport"):
        transport._tar_process("container",request(),False,lambda stream:stream.read(),"test tar",deadline)
    assert time.monotonic()<=deadline and len(processes)==len(observed["threads"])==1
    assert_reaped(processes[0]); assert not observed["threads"][0].is_alive() and not observed["watchdog"].is_alive()


def test_streaming_tar_health_failure_kills_transport_before_deadline(monkeypatch):
    processes=[]; checks=[]; real_popen=transport.subprocess.Popen
    monkeypatch.setattr(transport,"tar_command",lambda *_args:["/bin/sh","-c","printf x; sleep 30"])
    monkeypatch.setattr(transport.subprocess,"Popen",lambda *args,**kwargs:processes.append(real_popen(*args,**kwargs)) or processes[-1])
    def health(): checks.append(True); raise RuntimeError("daemon drift")
    started=time.monotonic()
    with pytest.raises(RuntimeError,match="daemon drift"):
        transport._tar_process("container",request(),False,lambda stream:stream.read(),"test tar",started+5.25,health)
    assert time.monotonic()-started<2 and checks
    assert_reaped(processes[0])


@pytest.mark.parametrize("target",["run","tar"])
def test_insufficient_absolute_budget_rejects_before_popen(monkeypatch,target):
    launches=[]; monkeypatch.setattr(transport.subprocess,"Popen",lambda *_args,**_kwargs:launches.append(True))
    deadline=time.monotonic()+transport.CLEANUP_SECONDS-0.1
    with pytest.raises(TimeoutError,match="no positive execution budget"):
        if target=="run": transport.run_capped_process(["ignored"],request(),deadline=deadline)
        else: transport._tar_process("container",request(),False,lambda _stream:None,"test tar",deadline)
    assert launches==[]


def test_cleanup_attempts_reap_all_joins_watchdog_and_both_pipe_closes(monkeypatch):
    events=[]
    class Process: pid=9
    class Thread:
        def __init__(self,name,fail=False): self.name=name; self.fail=fail
        def join(self,_timeout): events.append("join-"+self.name); (_ for _ in ()).throw(RuntimeError("join")) if self.fail else None
        def is_alive(self): return False
    class Watchdog(Thread):
        def cancel(self): events.append("cancel-watchdog"); raise RuntimeError("cancel")
    class Stream:
        def __init__(self,name,fail=False): self.name=name; self.fail=fail; self.closed=False
        def close(self):
            events.append("close-"+self.name); self.closed=True
            if self.fail: raise RuntimeError("close")
    monkeypatch.setattr(transport,"terminate_process",lambda *_args:events.append("reap") or (_ for _ in ()).throw(RuntimeError("reap")))
    errors=transport._cleanup_transport(Process(),(Thread("one",True),Thread("two")),(Stream("out",True),Stream("err")),time.monotonic()+1,True,watchdog=Watchdog("watchdog"))
    assert events==["reap","cancel-watchdog","join-one","join-two","join-watchdog","close-out","close-err"]
    assert len(errors)==4
    with pytest.raises(RuntimeError,match="cleanup also failed"):
        transport._finish(ValueError("original"),errors)


def test_nominal_cleanup_reaps_authenticated_live_group(monkeypatch):
    events=[]; alive=[True]
    process=SimpleNamespace(pid=44,poll=lambda:0)
    monkeypatch.setattr(transport,"_group_alive",lambda _pid:alive[0])
    def reap(_process,_deadline): events.append("reap"); alive[0]=False
    monkeypatch.setattr(transport,"terminate_process",reap)
    assert transport._cleanup_transport(process,(),(),time.monotonic()+1,False)==[]
    assert events==["reap"] and not alive[0]


def test_unexpected_group_probe_error_blocks_but_cleanup_continues(monkeypatch):
    events=[]; process=SimpleNamespace(pid=44,poll=lambda:0)
    monkeypatch.setattr(transport,"_group_alive",lambda _pid:(_ for _ in ()).throw(OSError(errno.EIO,"probe failed")))
    monkeypatch.setattr(transport,"terminate_process",lambda *_args:events.append("reap"))
    stream=SimpleNamespace(closed=False)
    def close(): events.append("close"); stream.closed=True
    stream.close=close
    errors=transport._cleanup_transport(process,(),(stream,),time.monotonic()+1,False)
    assert events==["reap","close"] and any("process group liveness" in item for item in errors)
    with pytest.raises(RuntimeError,match="process group liveness"): transport._finish(None,errors)


def test_reap_failure_raw_closes_blocked_readers_and_attempts_fair_joins(monkeypatch):
    pipes=[os.pipe(),os.pipe()]; streams=tuple(os.fdopen(read_fd,"rb",buffering=0) for read_fd,_write_fd in pipes)
    threads=tuple(transport.threading.Thread(target=lambda stream=stream:stream.read(1),daemon=True) for stream in streams)
    for thread in threads: thread.start()
    process=SimpleNamespace(pid=55,poll=lambda:None); joins=[]; real_join=transport.join_thread
    monkeypatch.setattr(transport,"_group_alive",lambda _pid:True)
    monkeypatch.setattr(transport,"terminate_process",lambda *_args:(_ for _ in ()).throw(RuntimeError("forced reap failure")))
    monkeypatch.setattr(transport,"join_thread",lambda thread,limit,label:joins.append((thread,limit,label)) or real_join(thread,limit,label))
    started=time.monotonic(); deadline=started+0.12
    try:
        errors=transport._cleanup_transport(process,threads,streams,deadline,True)
        assert time.monotonic()<=deadline
        for read_fd,_write_fd in pipes:
            with pytest.raises(OSError): os.fstat(read_fd)
        assert len(joins)==2 and any("reap failure" in item for item in errors)
        assert all(stream.closed for stream in streams) or any("surviving drain" in item for item in errors)
    finally:
        for _read_fd,write_fd in pipes: os.close(write_fd)
        for thread in threads: thread.join(1)
        for stream in streams:
            try: stream.close()
            except OSError: pass


class RawCloseWrapper:
    def __init__(self,descriptor,error,finalized): self.descriptor=descriptor; self.error=error; self.finalized=finalized; self.closed=False
    def fileno(self): return self.descriptor
    def close(self):
        self.closed=self.finalized
        if self.error is not None: raise OSError(self.error,"buffered close")


class JoinCompletes:
    def __init__(self): self.alive=True; self.joined=False
    def is_alive(self): return self.alive
    def join(self,_timeout): self.joined=True; self.alive=False


@pytest.mark.parametrize("error,finalized,clean",[(errno.EBADF,True,True),(errno.EBADF,False,False),(errno.EIO,True,False)])
def test_raw_close_wrapper_finalization_accepts_only_expected_ebadf(monkeypatch,error,finalized,clean):
    read_fd,write_fd=os.pipe(); stream=RawCloseWrapper(read_fd,error,finalized); thread=JoinCompletes()
    process=SimpleNamespace(pid=77,poll=lambda:0); monkeypatch.setattr(transport,"_group_alive",lambda _pid:False)
    try:
        errors=transport._cleanup_transport(process,(thread,),(stream,),time.monotonic()+1,False)
        assert thread.joined and stream.closed is finalized
        assert (errors==[]) is clean
        if not clean: assert any("buffered close" in item or "remained open" in item for item in errors)
    finally:
        os.close(write_fd)
        try: os.close(read_fd)
        except OSError: pass
