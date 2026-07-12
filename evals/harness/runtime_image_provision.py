"""Reviewed runtime image/source inventory for the Plan 009 feasibility gate."""
from __future__ import annotations
import hashlib, json, os, queue, subprocess, threading, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INVENTORY = ROOT / "container-images.json"

def inventory():
    return json.loads(INVENTORY.read_text(encoding="utf-8"))

def platform_digest(item, machine):
    key = {"x86_64":"amd64", "aarch64":"arm64", "arm64":"arm64"}.get(machine)
    if not key: raise RuntimeError(f"unsupported Docker platform: {machine}")
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

def run_capped(command, *, cwd=None, limit=131072, timeout=300):
    process=subprocess.Popen(command,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={"PATH":"/usr/bin:/bin"},start_new_session=True)
    events=queue.Queue(maxsize=32); chunks={"stdout":[],"stderr":[]}; sizes={"stdout":0,"stderr":0}; lock=threading.Lock(); stop=threading.Event()
    def emit(item):
        while not stop.is_set():
            try: events.put(item,timeout=0.05); return True
            except queue.Full: continue
        return False
    def drain(name, stream):
        while not stop.is_set() and (data := stream.read(8192)):
            with lock:
                sizes[name]+=len(data)
                overflow=sizes[name]>limit
            if overflow:
                emit((name,"overflow")); return
            if not emit((name,data)): return
        emit((name,None))
    threads=[]
    for name,stream in (("stdout",process.stdout),("stderr",process.stderr)):
        thread=threading.Thread(target=drain,args=(name,stream),daemon=True); thread.start(); threads.append(thread)
    closed=set(); deadline=time.monotonic()+timeout
    try:
        while len(closed)<2:
            remaining=deadline-time.monotonic()
            if remaining<=0: raise queue.Empty
            name,data=events.get(timeout=remaining)
            if data is None: closed.add(name); continue
            if data == "overflow":
                os.killpg(process.pid,9); process.wait(); raise RuntimeError(f"{name} output limit exceeded")
            chunks[name].append(data)
    except queue.Empty:
        os.killpg(process.pid,9); process.wait(); raise RuntimeError("command timed out")
    finally:
        stop.set()
        for stream in (process.stdout,process.stderr): stream.close()
        for thread in threads: thread.join(timeout=1)
        if any(thread.is_alive() for thread in threads): raise RuntimeError("output drain thread did not terminate")
    process.wait()
    return {"returncode":process.returncode,"stdout":b"".join(chunks["stdout"]).decode("utf-8","replace"),"stderr":b"".join(chunks["stderr"]).decode("utf-8","replace")}
