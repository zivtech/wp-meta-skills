"""Reviewed runtime image/source inventory for the Plan 009 feasibility gate."""
from __future__ import annotations
import errno, hashlib, json, os, queue, signal, subprocess, threading, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INVENTORY = ROOT / "container-images.json"
CLEANUP_SECONDS = 2

def inventory():
    return json.loads(INVENTORY.read_text(encoding="utf-8"))

def normalize_arch(machine):
    key = {"x86_64":"amd64", "amd64":"amd64", "aarch64":"arm64", "arm64":"arm64"}.get(machine)
    if not key: raise RuntimeError(f"unsupported Docker platform: {machine}")
    return key

def platform_digest(item, machine):
    key = normalize_arch(machine)
    return item[key]

def download_core(destination):
    core=inventory()["wordpress_core"]
    digest=hashlib.sha256(); total=0; maximum=64*1024*1024
    try:
        with urllib.request.urlopen(core["url"], timeout=60) as response, destination.open("xb") as out:
            length=response.headers.get("Content-Length")
            if length and int(length)>maximum: raise RuntimeError("WordPress core archive exceeds byte limit")
            while chunk := response.read(1024*1024):
                total+=len(chunk)
                if total>maximum: raise RuntimeError("WordPress core archive exceeds byte limit")
                digest.update(chunk); out.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True); raise
    actual=digest.hexdigest()
    if actual != core["sha256"]:
        destination.unlink(missing_ok=True); raise RuntimeError("WordPress core SHA-256 mismatch")
    return actual

def _group_alive(pid):
    try: os.killpg(pid,0); return True
    except ProcessLookupError: return False
    except PermissionError: return True

def _emit(events,stop,item):
    while not stop.is_set():
        try: events.put(item,timeout=0.05); return
        except queue.Full: continue

def _drain(name,stream,events,stop,sizes,limit):
    try:
        while not stop.is_set() and (data:=stream.read(8192)):
            sizes[name]+=len(data)
            if sizes[name]>limit: _emit(events,stop,(name,"overflow")); return
            _emit(events,stop,(name,data))
        _emit(events,stop,(name,None))
    except Exception as exc:
        if not stop.is_set(): _emit(events,stop,(name,("error",type(exc).__name__)))

def _collect(process,events,chunks,deadline):
    closed=set()
    while len(closed)<2 or process.poll() is None:
        remaining=deadline-time.monotonic()
        if remaining<=0: raise RuntimeError("command timed out")
        if len(closed)==2:
            try: process.wait(timeout=min(0.05,remaining))
            except subprocess.TimeoutExpired: pass
            continue
        try: name,data=events.get(timeout=min(0.05,remaining))
        except queue.Empty: continue
        if data is None: closed.add(name)
        elif data=="overflow": raise RuntimeError(f"{name} output limit exceeded")
        elif isinstance(data,tuple): raise RuntimeError(f"{name} output drain failed: {data[1]}")
        else: chunks[name].append(data)

def _raw_interrupt(streams,threads):
    closed=set()
    if not any(thread.is_alive() for thread in threads): return closed
    for index,stream in enumerate(streams):
        try: os.close(stream.fileno()); closed.add(index)
        except OSError as exc:
            if exc.errno!=errno.EBADF: raise
    return closed

def _finalize_streams(streams,threads,raw_closed):
    errors=[]
    if any(thread.is_alive() for thread in threads): return ["output drain thread did not terminate"]
    for index,stream in enumerate(streams):
        try: stream.close()
        except OSError as exc:
            expected=index in raw_closed and exc.errno==errno.EBADF and getattr(stream,"closed",False)
            if not expected: errors.append(f"pipe {index} close {type(exc).__name__}")
        if not getattr(stream,"closed",False): errors.append(f"pipe {index} wrapper remained open")
    return errors

def _cleanup(process,streams,threads,stop):
    deadline=time.monotonic()+CLEANUP_SECONDS; errors=[]
    try: alive=_group_alive(process.pid)
    except OSError as exc: errors.append(f"process group probe {type(exc).__name__}"); alive=True
    if alive or process.poll() is None:
        try: os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError: pass
        except OSError as exc: errors.append(f"process group kill {type(exc).__name__}")
    stop.set()
    try: raw_closed=_raw_interrupt(streams,threads)
    except OSError as exc: errors.append(f"pipe raw close {type(exc).__name__}"); raw_closed=set()
    while time.monotonic()<deadline:
        leader_alive=process.poll() is None
        try: group_alive=_group_alive(process.pid)
        except OSError as exc: errors.append(f"process group reap probe {type(exc).__name__}"); group_alive=True; break
        drain_alive=any(thread.is_alive() for thread in threads)
        if not leader_alive and not group_alive and not drain_alive: break
        if leader_alive:
            try: process.wait(timeout=min(0.02,max(0,deadline-time.monotonic())))
            except subprocess.TimeoutExpired: pass
        for thread in threads: thread.join(0)
        if not leader_alive: time.sleep(min(0.01,max(0,deadline-time.monotonic())))
    if process.poll() is None: errors.append("process survived cleanup deadline")
    try:
        if _group_alive(process.pid): errors.append("process group survived cleanup deadline")
    except OSError as exc: errors.append(f"final process group probe {type(exc).__name__}")
    errors.extend(_finalize_streams(streams,threads,raw_closed))
    return errors

def run_capped(command, *, cwd=None, limit=131072, timeout=300):
    process=subprocess.Popen(command,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={"PATH":"/usr/bin:/bin"},start_new_session=True)
    events=queue.Queue(maxsize=32); chunks={"stdout":[],"stderr":[]}; sizes={"stdout":0,"stderr":0}; stop=threading.Event(); threads=[]; original=None
    deadline=time.monotonic()+timeout; streams=(process.stdout,process.stderr)
    try:
        for name,stream in zip(("stdout","stderr"),streams):
            thread=threading.Thread(target=_drain,args=(name,stream,events,stop,sizes,limit),daemon=True)
            thread.start(); threads.append(thread)
        _collect(process,events,chunks,deadline)
    except Exception as exc: original=exc
    cleanup=_cleanup(process,streams,threads,stop)
    if cleanup:
        detail=", ".join(cleanup)
        if original is not None: raise RuntimeError(f"command failed ({original}); cleanup also failed ({detail})") from original
        raise RuntimeError(f"command cleanup failed ({detail})")
    if original is not None: raise original
    return {"returncode":process.returncode,"stdout":b"".join(chunks["stdout"]).decode("utf-8","replace"),"stderr":b"".join(chunks["stderr"]).decode("utf-8","replace")}
