"""Bounded host transports for generated execution and tar evidence."""
from __future__ import annotations

import errno
import os
import queue
import subprocess
import threading
import time

import artifact_staging
import workspace_lease

CLEANUP_SECONDS=5


def join_thread(thread,deadline,label):
    thread.join(max(0,deadline-time.monotonic()))
    if thread.is_alive(): raise RuntimeError(f"{label} did not terminate")


def kill_process(process):
    try: os.killpg(process.pid,9)
    except OSError:
        if process.poll() is None:
            try: process.kill()
            except OSError: pass


def _group_alive(pid):
    try: os.killpg(pid,0); return True
    except ProcessLookupError: return False
    except PermissionError: return True


def terminate_process(process,deadline=None):
    deadline=deadline or time.monotonic()+5; kill_process(process)
    remaining=deadline-time.monotonic()
    if process.poll() is None and remaining>0:
        try: process.wait(timeout=remaining)
        except subprocess.TimeoutExpired: pass
    while _group_alive(process.pid) and time.monotonic()<deadline:
        time.sleep(min(0.01,max(0,deadline-time.monotonic())))
    if process.poll() is None or _group_alive(process.pid):
        raise RuntimeError("killed process group survived reap deadline")


def _deadlines(timeout,absolute):
    started=time.monotonic(); requested=started+timeout
    if absolute is None: return requested,requested+CLEANUP_SECONDS
    operation=min(requested,absolute-CLEANUP_SECONDS)
    if operation<=started: raise TimeoutError("transport deadline has no positive execution budget")
    return operation,absolute


def _attempt(errors,label,action):
    try: action()
    except Exception as exc: errors.append(f"{label}: {type(exc).__name__}: {exc}")


def _threads_alive(errors,threads):
    alive=False
    for index,thread in enumerate(threads):
        try: alive=thread.is_alive() or alive
        except Exception as exc:
            errors.append(f"drain {index} liveness: {type(exc).__name__}: {exc}"); alive=True
    return alive


def _raw_interrupt(errors,streams,threads):
    raw_closed=set()
    if not _threads_alive(errors,threads): return raw_closed
    for index,stream in enumerate(streams):
        if not hasattr(stream,"fileno"): continue
        try: os.close(stream.fileno()); raw_closed.add(index)
        except Exception as exc: errors.append(f"pipe {index} raw close: {type(exc).__name__}: {exc}")
    return raw_closed


def _finalize_stream(errors,index,stream,raw_closed):
    try: stream.close()
    except OSError as exc:
        expected=index in raw_closed and exc.errno==errno.EBADF and getattr(stream,"closed",False)
        if not expected: errors.append(f"pipe {index} buffered close: {type(exc).__name__}: {exc}")
    except Exception as exc: errors.append(f"pipe {index} buffered close: {type(exc).__name__}: {exc}")
    if not getattr(stream,"closed",False): errors.append(f"pipe {index} buffered wrapper remained open")


def _cleanup_transport(process,threads,streams,deadline,terminate,stop=None,watchdog=None):
    errors=[]
    reap=terminate or process.poll() is None
    try: reap=_group_alive(process.pid) or reap
    except Exception as exc:
        errors.append(f"process group liveness: {type(exc).__name__}: {exc}"); reap=True
    if reap:
        _attempt(errors,"process group reap",lambda:terminate_process(process,deadline))
    if stop is not None: stop.set()
    if watchdog is not None: _attempt(errors,"watchdog cancel",watchdog.cancel)
    raw_closed=_raw_interrupt(errors,streams,threads)
    joiners=[(f"drain {index} join",thread,"transport drain") for index,thread in enumerate(threads)]
    if watchdog is not None: joiners.append(("watchdog join",watchdog,"transport watchdog"))
    for index,(item,thread,label) in enumerate(joiners):
        remaining=max(0,deadline-time.monotonic()); share=0.9*remaining/(len(joiners)-index)
        _attempt(errors,item,lambda thread=thread,label=label,share=share:join_thread(thread,min(deadline,time.monotonic()+share),label))
    if _threads_alive(errors,threads):
        errors.append("buffered pipe finalization blocked by surviving drain")
    else:
        for index,stream in enumerate(streams):
            _finalize_stream(errors,index,stream,raw_closed)
    return errors


def _finish(original,errors):
    if errors:
        message="; ".join(errors)
        if original is not None: raise RuntimeError(f"transport failed ({original}); cleanup also failed: {message}") from original
        raise RuntimeError(f"transport cleanup failed: {message}")
    if original is not None: raise original


def run_capped_process(command,request,deadline=None,health_check=None):
    execution_deadline,final_deadline=_deadlines(request.timeout,deadline)
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,env={"PATH":"/usr/bin:/bin"})
    events=queue.Queue(maxsize=32); buffers={"stdout":bytearray(),"stderr":bytearray()}; limits={"stdout":request.stdout_limit,"stderr":request.stderr_limit}; stop=threading.Event()
    def drain(name,stream):
        while not stop.is_set() and (chunk:=stream.read(8192)):
            if len(buffers[name])+len(chunk)>limits[name]: events.put((name,"overflow")); return
            buffers[name].extend(chunk)
        events.put((name,"closed"))
    threads=[]; closed=set(); original=None
    try:
        threads=[threading.Thread(target=drain,args=item,daemon=True) for item in (("stdout",process.stdout),("stderr",process.stderr))]
        for thread in threads: thread.start()
        while len(closed)<2:
            if health_check is not None: health_check()
            remaining=execution_deadline-time.monotonic()
            if remaining<=0: raise TimeoutError("generated command timed out")
            try: name,event=events.get(timeout=min(remaining,0.1) if health_check is not None else remaining)
            except queue.Empty:
                if time.monotonic()>=execution_deadline: raise TimeoutError("generated command timed out")
                continue
            if event=="overflow": raise RuntimeError(f"generated {name} exceeded output limit")
            closed.add(name)
        if health_check is not None: health_check()
        remaining=execution_deadline-time.monotonic()
        if remaining<=0: raise TimeoutError("generated command timed out during reap")
        try: process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc: raise TimeoutError("generated command timed out during reap") from exc
    except Exception as exc: original=exc
    cleanup=_cleanup_transport(process,threads,(process.stdout,process.stderr),final_deadline,original is not None,stop=stop)
    _finish(original,cleanup)
    return {"returncode":process.returncode,"stdout":bytes(buffers["stdout"]).decode("utf-8","replace"),"stderr":bytes(buffers["stderr"]).decode("utf-8","replace")}


def tar_command(name,exclude_dependencies=False):
    command=["docker","exec",name,"tar","-C","/workspace"]
    if exclude_dependencies:
        for root in ("node_modules","vendor","sandbox-cache"): command.append(f"--exclude=./{root}")
    return command+["-cf","-","."]


def _tar_process(name,request,exclude_dependencies,consumer,label,deadline=None,health_check=None):
    execution_deadline,final_deadline=_deadlines(request.timeout,deadline)
    process=subprocess.Popen(tar_command(name,exclude_dependencies),stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,env={"PATH":"/usr/bin:/bin"})
    stderr=bytearray(); overflow=[]; timed_out=[]; health_failure=[]; health_stop=threading.Event()
    def drain():
        while chunk:=process.stderr.read(8192):
            if len(stderr)+len(chunk)>request.stderr_limit: overflow.append(True); kill_process(process); return
            stderr.extend(chunk)
    def expire(): timed_out.append(True); kill_process(process)
    def health_watch():
        while not health_stop.wait(0.1):
            try: health_check()
            except Exception as exc: health_failure.append(exc); kill_process(process); return
    thread=None; health_thread=None; watchdog=None; output=None; original=None
    try:
        thread=threading.Thread(target=drain,daemon=True)
        if health_check is not None: health_thread=threading.Thread(target=health_watch,daemon=True)
        watchdog=threading.Timer(execution_deadline-time.monotonic(),expire)
        thread.start(); watchdog.start()
        if health_thread is not None: health_thread.start()
        output=consumer(process.stdout)
        if health_failure: raise health_failure[0]
        remaining=execution_deadline-time.monotonic()
        if remaining<=0: raise TimeoutError(f"{label} operation deadline exceeded")
        try: process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc: raise TimeoutError(f"{label} operation deadline exceeded") from exc
        if health_failure: raise health_failure[0]
        if timed_out or overflow or process.returncode: raise RuntimeError(f"{label} transport failed")
    except Exception as exc: original=exc
    threads=tuple(item for item in (thread,health_thread) if item is not None)
    cleanup=_cleanup_transport(process,threads,(process.stdout,process.stderr),final_deadline,original is not None,stop=health_stop,watchdog=watchdog)
    if (original is not None or cleanup) and hasattr(output,"lease"):
        _attempt(cleanup,"output lease cleanup",lambda:workspace_lease.cleanup(output.lease))
    _finish(original,cleanup)
    return output


def import_output(name,request,run,exclude_dependencies=False,health_check=None):
    if exclude_dependencies: dependency_root_gate(name,request,run)
    consumer=lambda stream:artifact_staging.import_tar_stream(artifact_staging.BoundedArchiveReader(stream,artifact_staging.MAX_ARCHIVE_STREAM_BYTES),request.result_parent,dependency_policy="strict")
    return _tar_process(name,request,exclude_dependencies,consumer,"output archive",health_check=health_check)


def verify_copy(name,request,run,exclude_dependencies=False,deadline=None,health_check=None):
    if exclude_dependencies: dependency_root_gate(name,request,run,deadline)
    return _tar_process(name,request,exclude_dependencies,artifact_staging.verify_tar_stream_manifest,"workspace proof",deadline,health_check)


def dependency_root_gate(name,request,run=None,deadline=None):
    roots=("node_modules","vendor","sandbox-cache")
    checks="; ".join(f"if [ -e {root} ] || [ -L {root} ]; then [ -d {root} ] && [ ! -L {root} ] || exit 41; fi" for root in roots)
    runner=run or (lambda command,request,timeout:None)
    timeout=15
    if deadline is not None:
        remaining=deadline-time.monotonic()
        if remaining<=0: raise TimeoutError("workspace proof deadline exceeded")
        timeout=min(timeout,remaining)
    result=runner(["docker","exec","--workdir","/workspace",name,"sh","-eu","-c",checks],request,timeout)
    if result is None or result["returncode"]: raise RuntimeError("dependency or cache root is a symlink or special node")
