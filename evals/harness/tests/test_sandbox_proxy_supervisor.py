import io
import json
import errno
import os
import signal
import subprocess
import time
from types import SimpleNamespace

import pytest

import sandbox_proxy_supervisor as supervisor


def record(value,inode=7): return supervisor.ControlRecord(value,1,inode)


def test_control_json_requires_complete_canonical_unique_payload():
    assert supervisor._canonical_json('{"nonce":"n","pid":7}\n',512)=={"nonce":"n","pid":7}
    with pytest.raises(EOFError): supervisor._canonical_json('{"nonce":"n"}',512)
    with pytest.raises(RuntimeError,match="canonical"): supervisor._canonical_json('{"pid":7, "nonce":"n"}\n',512)
    with pytest.raises(RuntimeError,match="duplicate"): supervisor._canonical_json('{"nonce":"n","nonce":"n","pid":7}\n',512)
    with pytest.raises(RuntimeError,match="byte limit"): supervisor._canonical_json('x'*513+'\n',512)


@pytest.mark.parametrize("value", [
    {"nonce":"forged","pid":7}, {"nonce":"n","pid":0}, {"nonce":"n","pid":True},
    {"nonce":"n","pid":7,"extra":1},
])
def test_pid_record_rejects_forgery_and_nonpositive_or_ambiguous_pid(value):
    with pytest.raises(RuntimeError,match="PID record"): supervisor._pid_record(record(value),"n")


def test_independent_stream_drain_records_overflow_without_unbounded_growth():
    buffers={"stdout":bytearray(),"stderr":bytearray()}; overflow=[]
    supervisor._drain(io.BytesIO(b"x"*(supervisor.STREAM_LIMIT+1)),"stdout",buffers,overflow)
    supervisor._drain(io.BytesIO(b"safe"),"stderr",buffers,overflow)
    assert overflow==["stdout"] and len(buffers["stdout"])<=supervisor.STREAM_LIMIT
    assert buffers["stderr"]==b"safe"


class OpenStream:
    def __init__(self): self.closed=False
    def close(self): self.closed=True


class LiveProcess:
    pid=1234; returncode=None
    def poll(self): return None
    def wait(self,timeout): raise AssertionError("expired deadline must not wait")


class LiveThread:
    def __init__(self): self.joined=False
    def join(self,timeout): self.joined=True
    def is_alive(self): return True


def _fake(process=None,threads=None):
    streams=(OpenStream(),OpenStream())
    return supervisor.ProxySupervisor("proxy","nonce",8,("/usr/local/bin/python",),"/usr/local/bin/python3.13",process or LiveProcess(),threads or (LiveThread(),LiveThread()),streams,{"stdout":bytearray(),"stderr":bytearray()},[],time.monotonic()+20,"501:20")


def test_expired_teardown_kills_host_group_without_blocking_wait_or_join(monkeypatch):
    observed=[]; item=_fake()
    monkeypatch.setattr(supervisor.os,"killpg",lambda pid,sig:observed.append((pid,sig)))
    with pytest.raises(RuntimeError,match="survived teardown"): supervisor._finish_transport(item,time.monotonic()-1)
    assert [item for item in observed if item[1]]==[(1234,signal.SIGTERM),(1234,signal.SIGKILL)]
    assert not any(stream.closed for stream in item.streams) and all(thread.joined for thread in item.threads)


class ExitedProcess:
    pid=22; returncode=9
    def poll(self): return 9


def test_overflow_nonzero_exit_and_live_drain_thread_each_block():
    item=_fake(process=ExitedProcess()); item.overflow.append("stderr")
    with pytest.raises(RuntimeError,match="stderr exceeded"): supervisor.check(item)
    item.overflow.clear()
    with pytest.raises(RuntimeError,match="exited early with 9"): supervisor.check(item)
    with pytest.raises(RuntimeError,match="survived teardown"): supervisor._finish_transport(item,time.monotonic()-1)


def test_status_schema_rejects_negative_boolean_or_nonce_drift():
    base={"nonce":"n","accepted":0,"active":0,"completed":0,"rejected":0,"client_bytes":0,"upstream_bytes":0}
    assert supervisor._status_record(record(base),"n").value==base
    for change in ({"nonce":"x"},{"active":-1},{"accepted":True},{"extra":0}):
        value={**base,**change}
        with pytest.raises(RuntimeError,match="status"): supervisor._status_record(record(value),"n")


def test_short_control_timeout_is_float_remaining_never_rounded_up(monkeypatch):
    monkeypatch.setattr(supervisor.time,"monotonic",lambda:10.75)
    assert supervisor._timeout(11.0)==pytest.approx(0.25)
    assert supervisor._timeout(20.0)==2.0
    with pytest.raises(TimeoutError): supervisor._timeout(10.75)


def test_subsecond_hung_status_control_cannot_receive_one_second(monkeypatch):
    seen=[]; monkeypatch.setattr(supervisor.time,"monotonic",lambda:20.75)
    def hung(_command,timeout): seen.append(timeout); raise TimeoutError("hung control")
    with pytest.raises(TimeoutError,match="hung control"):
        supervisor._read_file(hung,"proxy","/tmp/status.json",21.0,8192)
    assert seen==[pytest.approx(0.25)]


def test_wait_file_retries_stale_inode_then_accepts_fresh_at_fixed_cadence(monkeypatch):
    base={"nonce":"n","accepted":0,"active":0,"completed":0,"rejected":0,"client_bytes":0,"upstream_bytes":0}; inodes=iter((7,8)); sleeps=[]
    monkeypatch.setattr(supervisor,"_read_file",lambda *_args:record(base,next(inodes)))
    monkeypatch.setattr(supervisor.time,"sleep",lambda value:sleeps.append(value))
    def fresh(item):
        status=supervisor._status_record(item,"n")
        if status.inode==7: raise supervisor.StaleRecord("old")
        return status
    status=supervisor._wait_file(lambda *_args:None,"proxy","/tmp/status.json",time.monotonic()+2,8192,2,fresh)
    assert status.inode==8 and len(sleeps)==1 and 0<sleeps[0]<=0.1


@pytest.mark.parametrize("phase",["stat","cat"])
def test_control_file_only_retries_exact_enoent_not_other_errors(phase):
    calls=[]
    def control(command,_timeout):
        calls.append(command)
        if command[-2]=="stat" or "stat" in command:
            if phase=="stat": return {"returncode":2,"stdout":"","stderr":"permission denied"}
            return {"returncode":0,"stdout":f"1:2:600:{__import__('os').getuid()}:{__import__('os').getgid()}:1:10\n","stderr":""}
        return {"returncode":2,"stdout":"","stderr":"permission denied"}
    with pytest.raises(RuntimeError,match="metadata|content"):
        supervisor._read_file(control,"proxy","/tmp/status.json",time.monotonic()+2,8192)

def test_term_and_kill_control_failures_are_not_silently_accepted(monkeypatch):
    item=_fake(); control=lambda *_args:{"returncode":0,"stdout":"","stderr":""}
    monkeypatch.setattr(supervisor,"_process_evidence",lambda *_args:None); monkeypatch.setattr(supervisor,"_top_gate",lambda *_args:None)
    monkeypatch.setattr(supervisor.python_preflight,"start_attached",lambda *_args,**_kwargs:object())
    monkeypatch.setattr(supervisor.python_preflight,"await_attached",lambda *_args:{"returncode":1,"stdout":"","stderr":"denied"})
    for signal_name in ("TERM","KILL"):
        with pytest.raises(RuntimeError,match=signal_name): supervisor._signal_inside(item,control,signal_name,time.monotonic()+1)
    monkeypatch.setattr(supervisor,"_container_reap",lambda *_args:None); monkeypatch.setattr(supervisor,"_finish_transport",lambda *_args:None)
    with pytest.raises(RuntimeError,match="in-container teardown failed"): supervisor.abort(item,control)


def test_signal_control_uses_constant_isolated_python_helper_without_shell_or_kill_binary(monkeypatch):
    item=_fake(); commands=[]
    monkeypatch.setattr(supervisor,"_process_evidence",lambda *_args:None)
    monkeypatch.setattr(supervisor,"_top_gate",lambda *_args:None)
    monkeypatch.setattr(supervisor,"_top_no_helper_gate",lambda *_args:None)
    monkeypatch.setattr(supervisor.python_preflight,"start_attached",lambda command,limit:commands.append(command) or object())
    monkeypatch.setattr(supervisor.python_preflight,"await_attached",lambda *_args:{"returncode":0,"stdout":"","stderr":""})
    supervisor._signal_inside(item,lambda *_args:None,"TERM",time.monotonic()+5)
    assert len(commands)==1
    command=commands[0]
    assert command[:7]==["docker","exec","--user","501:20","--","proxy","/usr/bin/env"]
    assert command[7:12]==["-i","/usr/local/bin/python","-I","-S","-c"]
    assert command[12] is supervisor.python_preflight.SIGNAL_HELPER and command[-2:]==["8","TERM"]
    assert "/usr/bin/kill" not in command and not any(item in command for item in ("sh","bash","pkill"))


def test_pid_identity_change_blocks_before_signal_helper_starts(monkeypatch):
    item=_fake(); started=[]
    monkeypatch.setattr(supervisor,"_process_evidence",lambda *_args:(_ for _ in ()).throw(RuntimeError("identity drift")))
    monkeypatch.setattr(supervisor.python_preflight,"start_attached",lambda *_args:started.append(1))
    with pytest.raises(RuntimeError,match="identity drift"):
        supervisor._signal_inside(item,lambda *_args:None,"KILL",time.monotonic()+5)
    assert started==[] and item.termination==("pid-identity-loss",) and not item.identity_valid
    with pytest.raises(RuntimeError,match="previously lost"):
        supervisor._signal_inside(item,lambda *_args:None,"TERM",time.monotonic()+5)


def test_launch_uses_exact_user_env_i_isolated_python_argv(monkeypatch):
    commands=[]
    class Process:
        pid=44; returncode=None
        stdout=io.BytesIO(); stderr=io.BytesIO()
        def poll(self): return None
    monkeypatch.setattr(supervisor.subprocess,"Popen",lambda command,**kwargs:commands.append((command,kwargs)) or Process())
    values=iter((9,{"nonce":"n","accepted":0,"active":0,"completed":0,"rejected":0,"client_bytes":0,"upstream_bytes":0}))
    monkeypatch.setattr(supervisor,"_wait_file",lambda *_args,**_kwargs:next(values))
    monkeypatch.setattr(supervisor,"_process_evidence",lambda *_args:None); monkeypatch.setattr(supervisor,"_top_gate",lambda *_args:None)
    argv=("/usr/bin/env","-i","/usr/local/bin/python","-I","-S","-B","/proxy.py","--nonce","n")
    item=supervisor.launch("proxy","n",argv,"501:20",lambda *_args:None,20)
    command,options=commands[0]
    assert command==["docker","exec","--user","501:20","--","proxy",*argv]
    assert options["start_new_session"] is True and options["env"]=={"PATH":"/usr/bin:/bin"}
    assert item.argv==argv[2:] and item.executable=="/usr/local/bin/python3.13"


@pytest.mark.parametrize("failure,target",[
    ("Thread constructor",1),("Thread constructor",2),
    ("Thread start",1),("Thread start",2),
])
def test_launch_setup_failure_reaps_partial_transport(monkeypatch,failure,target):
    processes=[]; threads=[]; calls=0; control_calls=[]
    real_popen=supervisor.subprocess.Popen; real_thread=supervisor.threading.Thread
    def popen(_command,**_kwargs):
        process=real_popen(["/bin/sh","-c","sleep 30"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,env={"PATH":"/usr/bin:/bin"})
        processes.append(process); return process
    def construct(*args,**kwargs):
        nonlocal calls
        calls+=1
        if failure=="Thread constructor" and calls==target: raise RuntimeError(f"{failure} {target} failed")
        thread=real_thread(*args,**kwargs); threads.append(thread)
        if failure=="Thread start" and calls==target:
            thread.start=lambda:(_ for _ in ()).throw(RuntimeError(f"{failure} {target} failed"))
        return thread
    monkeypatch.setattr(supervisor.subprocess,"Popen",popen)
    monkeypatch.setattr(supervisor.threading,"Thread",construct)
    argv=("/usr/bin/env","-i","/usr/local/bin/python","-I","-S","-B","/proxy.py","--nonce","n")
    started=time.monotonic()
    with pytest.raises(RuntimeError,match=f"{failure} {target} failed"):
        supervisor.launch("proxy","n",argv,"501:20",lambda *args:control_calls.append(args),20)
    assert time.monotonic()-started<supervisor.SETUP_CLEANUP_SECONDS+1
    assert control_calls==[] and len(processes)==1
    process=processes[0]; assert process.poll() is not None
    with pytest.raises(ProcessLookupError): os.killpg(process.pid,0)
    assert process.stdout.closed and process.stderr.closed
    assert all(not thread.is_alive() for thread in threads)


def test_launch_setup_failure_preserves_teardown_failure(monkeypatch):
    process=SimpleNamespace(pid=44,stdout=OpenStream(),stderr=OpenStream())
    observed=[]
    monkeypatch.setattr(supervisor.subprocess,"Popen",lambda *_args,**_kwargs:process)
    monkeypatch.setattr(supervisor.threading,"Thread",lambda *_args,**_kwargs:(_ for _ in ()).throw(RuntimeError("setup exploded")))
    monkeypatch.setattr(supervisor,"_finish_transport",lambda item,_deadline:observed.append(item) or (_ for _ in ()).throw(RuntimeError("cleanup exploded")))
    argv=("/usr/bin/env","-i","/usr/local/bin/python","-I","-S","-B","/proxy.py","--nonce","n")
    with pytest.raises(RuntimeError,match="setup exploded.*teardown also failed.*cleanup exploded"):
        supervisor.launch("proxy","n",argv,"501:20",lambda *_args:None,20)
    assert len(observed)==1 and observed[0].process is process and observed[0].threads==()


def test_signal_timeout_and_post_control_helper_survival_each_block(monkeypatch):
    item=_fake(); monkeypatch.setattr(supervisor,"_process_evidence",lambda *_args:None); monkeypatch.setattr(supervisor,"_top_gate",lambda *_args:None)
    monkeypatch.setattr(supervisor.python_preflight,"start_attached",lambda *_args,**_kwargs:object())
    monkeypatch.setattr(supervisor.python_preflight,"await_attached",lambda *_args:(_ for _ in ()).throw(TimeoutError("hung")))
    monkeypatch.setattr(supervisor.python_preflight,"cleanup_attached",lambda *_args:[])
    with pytest.raises(RuntimeError,match="TERM failed.*hung"):
        supervisor._signal_inside(item,lambda *_args:None,"TERM",time.monotonic()+5)
    monkeypatch.setattr(supervisor.python_preflight,"await_attached",lambda *_args:{"returncode":0,"stdout":"","stderr":""})
    monkeypatch.setattr(supervisor,"_top_no_helper_gate",lambda *_args:(_ for _ in ()).throw(RuntimeError("helper survived")))
    with pytest.raises(RuntimeError,match="helper survived"):
        supervisor._signal_inside(item,lambda *_args:None,"TERM",time.monotonic()+5)


@pytest.mark.parametrize("event",["authenticated-kill","host-term","host-kill","pid-identity-loss","whole-container-cleanup"])
def test_zero_exit_after_any_escalation_remains_blocked(monkeypatch,event):
    base={"nonce":"nonce","accepted":0,"active":0,"completed":0,"rejected":0,"client_bytes":0,"upstream_bytes":0}
    item=_fake(process=ExitedProcess()); item.process.returncode=0; item.termination=(event,)
    before=supervisor.StatusRecord(base,1,7); fresh=supervisor.StatusRecord(base,1,8)
    monkeypatch.setattr(supervisor,"read_status",lambda *_args,**_kwargs:before)
    monkeypatch.setattr(supervisor,"_signal_inside",lambda *_args:None); monkeypatch.setattr(supervisor,"_container_reap",lambda *_args:None); monkeypatch.setattr(supervisor,"_finish_transport",lambda *_args:None)
    monkeypatch.setattr(supervisor,"_wait_file",lambda *_args,**_kwargs:fresh)
    with pytest.raises(RuntimeError,match="required escalation"):
        supervisor.stop(item,lambda *_args:None)


def test_only_graceful_term_fresh_drained_status_and_zero_exit_can_pass(monkeypatch):
    base={"nonce":"nonce","accepted":1,"active":0,"completed":1,"rejected":0,"client_bytes":4,"upstream_bytes":4}
    item=_fake(process=ExitedProcess()); item.process.returncode=0
    monkeypatch.setattr(supervisor,"read_status",lambda *_args,**_kwargs:supervisor.StatusRecord(base,1,7))
    monkeypatch.setattr(supervisor,"_signal_inside",lambda *_args:None); monkeypatch.setattr(supervisor,"_container_reap",lambda *_args:None); monkeypatch.setattr(supervisor,"_finish_transport",lambda *_args:None)
    def final(_control,_container,_path,_deadline,_limit,polls,validator):
        assert polls==100
        return validator(record(base,8))
    monkeypatch.setattr(supervisor,"_wait_file",final)
    status=supervisor.stop(item,lambda *_args:None)
    assert status.value==base and status.inode==8 and item.termination==()


@pytest.mark.parametrize("mode,match",[
    ("missing","did not become ready"),("incomplete","did not become ready"),
    ("oversized","size drift"),("noncanonical","not canonical"),
    ("wrong-nonce","status record is invalid"),("non-drained","retained active tunnels"),
])
def test_stop_rejects_every_invalid_final_status_surface(monkeypatch,mode,match):
    base={"nonce":"nonce","accepted":1,"active":0,"completed":1,"rejected":0,"client_bytes":4,"upstream_bytes":4}
    item=_fake(process=ExitedProcess()); item.process.returncode=0
    before=supervisor.StatusRecord(base,1,7)
    monkeypatch.setattr(supervisor,"read_status",lambda *_args,**_kwargs:before)
    monkeypatch.setattr(supervisor,"_signal_inside",lambda *_args:None)
    monkeypatch.setattr(supervisor,"_container_reap",lambda *_args:None)
    monkeypatch.setattr(supervisor,"_finish_transport",lambda *_args:None)
    monkeypatch.setattr(supervisor.time,"sleep",lambda _value:None)
    value={**base}
    if mode=="wrong-nonce": value["nonce"]="wrong"
    if mode=="non-drained": value["active"]=1
    payload=json.dumps(value,sort_keys=True,separators=(",",":"))+"\n"
    if mode=="incomplete": payload=payload.rstrip("\n")
    if mode=="noncanonical": payload=json.dumps(value)+"\n"
    def control(command,_timeout):
        if command[-2]=="stat" or "stat" in command:
            if mode=="missing": return {"returncode":1,"stdout":"","stderr":"stat: cannot statx '/tmp/status.json': No such file or directory"}
            size=8193 if mode=="oversized" else len(payload.encode())
            return {"returncode":0,"stdout":f"1:8:600:{os.getuid()}:{os.getgid()}:1:{size}\n","stderr":""}
        return {"returncode":0,"stdout":payload,"stderr":""}
    with pytest.raises((RuntimeError,TimeoutError),match=match): supervisor.stop(item,control)


def test_stop_rejects_early_workload_exit(monkeypatch):
    base={"nonce":"nonce","accepted":0,"active":0,"completed":0,"rejected":0,"client_bytes":0,"upstream_bytes":0}
    item=_fake(process=ExitedProcess())
    monkeypatch.setattr(supervisor,"read_status",lambda *_args,**_kwargs:supervisor.StatusRecord(base,1,7))
    monkeypatch.setattr(supervisor,"_signal_inside",lambda *_args:None)
    monkeypatch.setattr(supervisor,"_container_reap",lambda *_args:None)
    monkeypatch.setattr(supervisor,"_finish_transport",lambda *_args:None)
    with pytest.raises(RuntimeError,match="did not exit cleanly"): supervisor.stop(item,lambda *_args:None)


def test_stop_term_survivor_kill_is_sticky_and_blocks_zero_exit(monkeypatch):
    base={"nonce":"nonce","accepted":0,"active":0,"completed":0,"rejected":0,"client_bytes":0,"upstream_bytes":0}
    class Survivor:
        pid=31; returncode=None
        def poll(self): return self.returncode
        def wait(self,timeout): raise subprocess.TimeoutExpired("proxy",timeout)
    item=_fake(process=Survivor()); signals=[]
    monkeypatch.setattr(supervisor,"read_status",lambda *_args,**_kwargs:supervisor.StatusRecord(base,1,7))
    def signal_inside(target,_control,name,_deadline):
        signals.append(name)
        if name=="KILL": target.process.returncode=0; supervisor._mark(target,"authenticated-kill")
    monkeypatch.setattr(supervisor,"_signal_inside",signal_inside)
    monkeypatch.setattr(supervisor,"_finish_transport",lambda *_args:None)
    monkeypatch.setattr(supervisor,"_wait_file",lambda *_args,**_kwargs:supervisor.StatusRecord(base,1,8))
    with pytest.raises(RuntimeError,match="required escalation"): supervisor.stop(item,lambda *_args:None)
    assert signals==["TERM","KILL"] and item.termination==("authenticated-kill",)


def test_finish_transport_closes_pipe_descriptors_on_forced_drain_interruption(monkeypatch):
    pipes=[os.pipe(),os.pipe()]; streams=tuple(os.fdopen(read_fd,"rb",buffering=0) for read_fd,_write_fd in pipes)
    class JoinedThread:
        alive=True
        def is_alive(self): return self.alive
        def join(self,_timeout): self.alive=False
    class Done:
        pid=71; returncode=0
        def poll(self): return 0
    item=supervisor.ProxySupervisor("proxy","nonce",8,("python",),"python",Done(),(JoinedThread(),JoinedThread()),streams,{"stdout":bytearray(),"stderr":bytearray()},[],time.monotonic()+5,"501:20")
    monkeypatch.setattr(supervisor,"_group_alive",lambda _pid:False)
    try:
        supervisor._finish_transport(item,time.monotonic()+1)
        for read_fd,_write_fd in pipes:
            with pytest.raises(OSError): os.fstat(read_fd)
        assert all(stream.closed for stream in streams)
    finally:
        for stream in streams:
            try: stream.close()
            except OSError: pass
        for _read_fd,write_fd in pipes: os.close(write_fd)


@pytest.mark.parametrize("error,closed",[(errno.EBADF,False),(errno.EIO,True)])
def test_finish_streams_blocks_unexpected_or_unfinalized_buffered_close(error,closed):
    read_fd,write_fd=os.pipe()
    class Wrapper:
        def __init__(self): self.closed=False
        def fileno(self): return read_fd
        def close(self): self.closed=closed; raise OSError(error,"close failed")
    class Thread:
        alive=True
        def is_alive(self): return self.alive
        def join(self,_timeout): self.alive=False
    item=SimpleNamespace(streams=(Wrapper(),),threads=(Thread(),))
    try:
        failures=supervisor._finish_streams(item,time.monotonic()+1)
        assert failures and any("buffered close" in failure or "wrapper open" in failure for failure in failures)
    finally:
        os.close(write_fd)
        try: os.close(read_fd)
        except OSError: pass


def test_exited_main_with_surviving_process_group_is_terminated_and_sticky(monkeypatch):
    item=_fake(process=ExitedProcess()); alive=iter((True,True,False,False,False)); signals=[]
    monkeypatch.setattr(supervisor,"_group_alive",lambda _pid:next(alive))
    monkeypatch.setattr(supervisor.os,"killpg",lambda pid,sig:signals.append((pid,sig)))
    monkeypatch.setattr(supervisor.time,"sleep",lambda _value:None)
    supervisor._host_reap(item,time.monotonic()+1)
    assert signals==[(22,signal.SIGTERM)] and item.termination==("host-term",)


def test_unexpected_process_group_probe_error_is_not_treated_as_absence(monkeypatch):
    monkeypatch.setattr(supervisor.os,"killpg",lambda *_args:(_ for _ in ()).throw(OSError(errno.EIO,"probe failed")))
    with pytest.raises(OSError,match="probe failed"): supervisor._group_alive(22)
