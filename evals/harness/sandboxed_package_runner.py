"""Linux-Docker boundary for direct generated package commands."""
from __future__ import annotations
import hashlib, json, math, os, platform, re, stat, time, uuid
from dataclasses import dataclass, replace
from pathlib import Path
import artifact_staging
import dependency_egress_proxy
import docker_event_guard
import runtime_image_provision as provision
import sandbox_evidence
import sandbox_dns_guard
import sandbox_network_policy
import sandbox_process_transport as process_transport
import sandbox_python_preflight as python_preflight
import sandbox_proxy_supervisor as proxy_supervisor
import sandbox_source_proof as source_proof
import workspace_lease
ENV_ALLOWLIST=frozenset({"HOME","TMPDIR","XDG_CACHE_HOME"})
_TEST_BARRIERS={}
MAX_WORKSPACE_BYTES=2*1024**3; MAX_WORKSPACE_INODES=200_000; MAX_PIDS=256
MAX_TIMEOUT=900; MAX_STREAM_BYTES=1024*1024; MAX_CPUS=4.0; MAX_MEMORY_BYTES=4*1024**3; PROXY_MEMORY_BYTES=256*1024**2; HOST_RESERVE_BYTES=1024**3

def _allowed_images(server_arch):
    inventory=provision.inventory()["images"]; allowed=set()
    for key in ("node","composer"):
        item=inventory[key]; repository=item["tag"].split(":")[0]
        allowed.add(f"{repository}@{item[server_arch]}")
    return frozenset(allowed)

def _normalize_server_arch(value):
    arch={"x86_64":"amd64","amd64":"amd64","aarch64":"arm64","arm64":"arm64"}.get(value.strip().lower())
    if arch is None: raise ValueError("unsupported Docker daemon architecture")
    return arch

def _validate_image(request,server_arch):
    if request.image not in _allowed_images(_normalize_server_arch(server_arch)): raise ValueError("sandbox image is not an approved daemon-platform child")
    if request.acquisition:
        profile=dependency_egress_proxy.ACQUISITION_PROFILES[request.acquisition]; item=provision.inventory()["images"][profile.image_key]
        arch=_normalize_server_arch(server_arch); bound=profile.amd64_digest if arch=="amd64" else profile.arm64_digest
        if item[arch]!=bound: raise ValueError("acquisition profile and image inventory digest mismatch")
        expected=f"{item['tag'].split(':')[0]}@{bound}"
        if request.image!=expected: raise ValueError("sandbox image does not match acquisition profile")

def _proxy_image(server_arch):
    item=provision.inventory()["images"]["python"]
    return f"{item['tag'].split(':')[0]}@{item[server_arch]}"

def _assert_local_image(reference):
    command=["docker","image","inspect",reference,"--format","{{json .Id}} {{json .RepoDigests}}"]
    result=provision.run_capped(command,timeout=30,limit=32768)
    if result["returncode"]: raise RuntimeError(f"required image is not locally provisioned: {reference}")
    try: image_id_raw,repo_digests_raw=result["stdout"].strip().split(" ",1); image_id=json.loads(image_id_raw); repo_digests=json.loads(repo_digests_raw)
    except (ValueError,json.JSONDecodeError) as exc: raise RuntimeError("local image evidence is malformed") from exc
    digest=reference.rpartition("@")[2]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}",image_id) or not isinstance(repo_digests,list) or not any(item.endswith(f"@{digest}") for item in repo_digests): raise RuntimeError("local image digest evidence mismatch")
    return image_id

@dataclass(frozen=True)
class SandboxRequest:
    staged:artifact_staging.StagedTree; image:str; argv:tuple[str,...]
    user:str=f"{os.getuid()}:{os.getgid()}"; environment:tuple[tuple[str,str],...]=()
    workspace_bytes:int=536870912; workspace_inodes:int=50000
    memory:str="1g"; pids:int=128; cpus:str="1.0"; timeout:int=300
    stdout_limit:int=131072; stderr_limit:int=131072; result_parent:Path|None=None
    acquisition:str|None=None

@dataclass(frozen=True)
class SandboxResult:
    status:str; returncode:int|None; stdout:str; stderr:str
    output:artifact_staging.StagedTree|None; detail:str; container_name:str
    runtime_identity:dict[str,object]|None=None

@dataclass(frozen=True)
class StagedCapability:
    lease_fd:int; root_fd:int; source:str; device:int; inode:int; path_kinds:tuple[tuple[str,str],...]; proof:source_proof.SourceProof; budget:source_proof.ProofBudget

@dataclass(frozen=True)
class ProxyCapability:
    lease:workspace_lease.WorkspaceLease; lease_fd:int; file_fd:int; source:str; sha256:str; proof:source_proof.FileProof|None=None; budget:source_proof.ProofBudget|None=None

@dataclass(frozen=True)
class ResourceEvent:
    kind:str; name:str; state:str

class ResourceLedger:
    def __init__(self): self.events=()
    def record(self,kind,name,state): self.events=self.events+(ResourceEvent(kind,name,state),)
    def created(self,kind,name): return any(item.kind==kind and item.name==name and item.state=="created" for item in self.events)
    def needs_cleanup(self,kind,name):
        states=[item.state for item in self.events if item.kind==kind and item.name==name]
        return bool(states) and states[-1] not in {"removed","detached","retained"}

@dataclass(frozen=True)
class AcquisitionContext:
    internal:str; egress:str; proxy:str; nonce:str; package_ip:str; proxy_ip:str
    gateway_ip:str; proxy_image:str; proxy_code:ProxyCapability; memory_available:int; ledger:ResourceLedger; supervisor:object|None=None

@dataclass(frozen=True)
class DetachedIdentity:
    container_id:str; started_at:str; network_mode:str; daemon_id:str; network_id:str
    package_image_id:str; proxy_container_id:str; proxy_image_id:str

class SandboxBoundaryError(RuntimeError):
    def __init__(self,message,timings,metrics,resources): super().__init__(message); self.timings=dict(timings); self.metrics=dict(metrics); self.resources=list(resources)
def _resource_events(ledger):
    return [{"kind":item.kind,"name":item.name,"state":item.state} for item in ledger.events] if ledger else []

def _blocked(request,name,detail,timings=None,metrics=None):
    return SandboxResult("blocked",None,"","",None,sandbox_evidence.encode("blocked",timings,metrics,detail),name)

def _validate_request(request,retain=False):
    if os.getuid()==0: raise ValueError("live sandbox rejects a root host UID")
    if not request.argv or any(not isinstance(item,str) or "\x00" in item for item in request.argv): raise ValueError("generated argv must be non-empty strings")
    if not re.fullmatch(r"(?:node|composer)@sha256:[0-9a-f]{64}",request.image): raise ValueError("sandbox image is not a canonical digest reference")
    if request.user.startswith("0:") or request.user!=f"{os.getuid()}:{os.getgid()}": raise ValueError("sandbox user must equal the exact non-root host UID:GID")
    keys=[key for key,_value in request.environment]
    if len(keys)!=len(set(keys)) or any(key not in ENV_ALLOWLIST for key in keys): raise ValueError("invalid sandbox environment key")
    if any(not value.isascii() or "\x00" in value or not value.startswith(("/tmp","/home/sandbox","/cache")) for _key,value in request.environment): raise ValueError("invalid sandbox environment value")
    if min(request.workspace_bytes,request.workspace_inodes,request.pids,request.timeout,request.stdout_limit,request.stderr_limit)<=0 or not re.fullmatch(r"[1-9][0-9]*[bkmg]?",request.memory.lower()): raise ValueError("sandbox limits must be positive")
    cpu=float(request.cpus); memory=_memory_bytes(request.memory)
    if not math.isfinite(cpu) or cpu>MAX_CPUS or memory>MAX_MEMORY_BYTES or request.workspace_bytes>MAX_WORKSPACE_BYTES or request.workspace_inodes>MAX_WORKSPACE_INODES or request.pids>MAX_PIDS or request.timeout>MAX_TIMEOUT or max(request.stdout_limit,request.stderr_limit)>MAX_STREAM_BYTES: raise ValueError("sandbox limits exceed reviewed maxima")
    if request.acquisition is not None and request.acquisition not in dependency_egress_proxy.ACQUISITION_PROFILES: raise ValueError("unsupported dependency acquisition profile")
    lease=request.staged.lease
    if not isinstance(lease,workspace_lease.WorkspaceLease) or workspace_lease._LIVE_LEASES.get(lease.lease_id) is not lease: raise ValueError("staged tree lease is not live and authentic")
    if request.staged.root.absolute()!=lease.root/"artifact": raise ValueError("staged tree root is outside its live lease")
    if "," in str(request.staged.root): raise ValueError("staged root contains unsupported Docker mount metacharacter")
    lease_fd=artifact_staging._verified_lease_fd(lease); root_fd=None
    try:
        info=os.stat("artifact",dir_fd=lease_fd,follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode): raise ValueError("staged artifact root is not a directory")
        root_fd=os.open("artifact",os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=lease_fd)
        budget=source_proof.ProofBudget(); proof=source_proof.prove_artifact(root_fd,budget)
        if proof.manifest!=request.staged.manifest: raise ValueError("staged tree manifest is stale")
        opened=os.fstat(root_fd); canonical=str(request.staged.root.absolute())
        capability=StagedCapability(lease_fd,root_fd,canonical,opened.st_dev,opened.st_ino,proof.path_kinds,proof,budget)
        if retain: return capability
    finally:
        if not retain or 'capability' not in locals():
            if root_fd is not None: os.close(root_fd)
            os.close(lease_fd)

def _barrier(kind,stage,path):
    callback=_TEST_BARRIERS.get((kind,stage))
    if callback is not None: callback(Path(path))

def _reprove_artifact(capability):
    descriptor=source_proof.open_canonical_directory(Path(capability.source))
    try: observed=source_proof.prove_artifact(descriptor,capability.budget)
    finally: os.close(descriptor)
    if observed!=capability.proof or (os.fstat(capability.root_fd).st_dev,os.fstat(capability.root_fd).st_ino)!=(capability.device,capability.inode): raise RuntimeError("canonical staged artifact proof drift")
    return observed

def _reprove_proxy(capability):
    descriptor=source_proof.open_canonical_file(Path(capability.source))
    try: observed=source_proof.prove_proxy(descriptor,capability.budget)
    finally: os.close(descriptor)
    held=os.fstat(capability.file_fd)
    if observed!=capability.proof or (held.st_dev,held.st_ino)!=(capability.proof.root.device,capability.proof.root.inode): raise RuntimeError("canonical proxy source proof drift")
    return observed

def _configured_mount_gate(name,request,source,destination):
    result=_run(["docker","inspect",name],request,30)
    if result["returncode"]: raise RuntimeError(f"pre-start container inspection failed: {result['stderr'][:4096]}")
    data=json.loads(result["stdout"])[0]; mounts=data["HostConfig"].get("Mounts",[])
    if len(mounts)!=1: raise RuntimeError("pre-start bind inventory drift")
    mount=mounts[0]; options=mount.get("BindOptions") or {}
    if mount.get("Type")!="bind" or mount.get("Source")!=source or mount.get("Target")!=destination or mount.get("ReadOnly") is not True or options.get("Propagation")!="rprivate": raise RuntimeError("pre-start canonical bind drift")

def _configured_proxy_mount_gate(context):
    result=_control_run(["docker","inspect",context.proxy],30)
    if result["returncode"]: raise RuntimeError(f"pre-start proxy inspection failed: {result['stderr'][:4096]}")
    data=json.loads(result["stdout"])[0]; python_preflight.assert_image_environment(data["Config"].get("Env"))
    mounts=data["HostConfig"].get("Mounts",[])
    if len(mounts)!=1: raise RuntimeError("pre-start proxy bind inventory drift")
    mount=mounts[0]; options=mount.get("BindOptions") or {}
    if mount.get("Type")!="bind" or mount.get("Source")!=context.proxy_code.source or mount.get("Target")!="/proxy.py" or mount.get("ReadOnly") is not True or options.get("Propagation")!="rprivate": raise RuntimeError("pre-start canonical proxy bind drift")

def _live_input_identity(name,request,capability,deadline=None):
    observed=_run(["docker","exec",name,"stat","-c","%d:%i","/input"],request,30 if deadline is None else min(30,_remaining(deadline)))
    if observed["returncode"] or observed["stdout"].strip()!=f"{capability.device}:{capability.inode}": raise RuntimeError("live input identity drift")

def _create_command(request,name,capability=None,network=None,ip=None):
    work=f"/workspace:size={request.workspace_bytes},nr_inodes={request.workspace_inodes},mode=0700,uid={request.user.split(':')[0]},gid={request.user.split(':')[1]},exec,nosuid,nodev"
    temp=lambda path:f"{path}:size=67108864,nr_inodes=4096,mode=0700,uid={request.user.split(':')[0]},gid={request.user.split(':')[1]},noexec,nosuid,nodev"
    command=["docker","create","--pull=never","--name",name,"--network",network or "none"]
    if network: command.extend(("--ip",ip,"--dns","127.0.0.1"))
    command.extend(("--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","--user",request.user,"--pids-limit",str(request.pids),"--memory",request.memory,"--memory-swap",request.memory,"--cpus",request.cpus,"--ulimit","nofile=1024:1024","--log-driver","none","--tmpfs",work))
    for path in ("/tmp","/home/sandbox","/cache"): command.extend(("--tmpfs",temp(path)))
    source=capability.source if capability else str(request.staged.root)
    command.extend(("--mount",f"type=bind,src={source},dst=/input,readonly"))
    for key,value in request.environment: command.extend(("--env",f"{key}={value}"))
    command.extend(("--entrypoint","sleep",request.image,"infinity")); return command

def _run(command,request,timeout=None):
    return provision.run_capped(command,timeout=timeout or request.timeout,limit=min(request.stdout_limit,request.stderr_limit))

def _control_run(command,timeout=30):
    return provision.run_capped(command,timeout=timeout,limit=32768)

def _memory_bytes(value):
    units={"b":1,"k":1024,"m":1024**2,"g":1024**3}; suffix=value[-1].lower()
    return int(value[:-1])*units[suffix] if suffix in units else int(value)

def _inspect_boundary(name,request,capability=None,context=None,deadline=None):
    timeout=lambda value:value if deadline is None else min(value,_remaining(deadline))
    result=_run(["docker","inspect",name],request,timeout(30))
    if result["returncode"]: raise RuntimeError("container inspection failed")
    data=json.loads(result["stdout"])[0]; host=data["HostConfig"]
    expected_image=_run(["docker","image","inspect",request.image,"--format","{{.Id}}"],request,timeout(30))
    if expected_image["returncode"] or data["Image"]!=expected_image["stdout"].strip() or data["Config"]["User"]!=request.user: raise RuntimeError("container image or user drift")
    if data["Config"].get("Entrypoint")!=["sleep"] or data["Config"].get("Cmd")!=["infinity"]: raise RuntimeError("container startup command drift")
    dangerous={"LD_PRELOAD","LD_LIBRARY_PATH","NODE_OPTIONS","PHP_INI_SCAN_DIR"}
    env_keys={item.split("=",1)[0].upper() for item in data["Config"].get("Env",[])}
    if env_keys&dangerous or any(key.endswith("PROXY") for key in env_keys): raise RuntimeError("container inherited dangerous environment")
    expected_network=context.internal if context else "none"
    if host["NetworkMode"]!=expected_network or not host["ReadonlyRootfs"] or host["CapDrop"]!=["ALL"]: raise RuntimeError("container isolation drift")
    if host.get("PidMode") or host.get("IpcMode") not in {"","private"} or host.get("UTSMode") or host.get("UsernsMode"): raise RuntimeError("container namespace drift")
    if host.get("RestartPolicy")!={"Name":"no","MaximumRetryCount":0}: raise RuntimeError("container restart drift")
    if host["PidsLimit"]!=request.pids or host["Memory"]!=_memory_bytes(request.memory) or host["MemorySwap"]!=_memory_bytes(request.memory) or host["NanoCpus"]!=int(float(request.cpus)*1_000_000_000): raise RuntimeError("container resource drift")
    if host["SecurityOpt"]!=["no-new-privileges:true"] or host["Binds"] or host["Privileged"]: raise RuntimeError("container security drift")
    expected_dns=["127.0.0.1"] if context else []
    if host.get("Devices") or host.get("PortBindings") or host.get("ExtraHosts") or host.get("Dns",[])!=expected_dns or host.get("DnsSearch"): raise RuntimeError("container host surface drift")
    if host.get("Ulimits")!=[{"Name":"nofile","Hard":1024,"Soft":1024}] or host["LogConfig"]["Type"]!="none": raise RuntimeError("container process/logging drift")
    mounts=data["Mounts"]
    expected_source=capability.source if capability else str(request.staged.root)
    if len(mounts)!=1 or mounts[0]["Type"]!="bind" or mounts[0]["Destination"]!="/input" or mounts[0]["RW"] or mounts[0].get("Propagation")!="rprivate" or mounts[0]["Source"]!=expected_source: raise RuntimeError("input bind drift")
    if capability:
        observed=_run(["docker","exec",name,"stat","-c","%d:%i","/input"],request,timeout(30))
        if observed["returncode"] or observed["stdout"].strip()!=f"{capability.device}:{capability.inode}": raise RuntimeError("input descriptor identity drift")
    expected={"/workspace","/tmp","/home/sandbox","/cache"}
    if set(host.get("Tmpfs",{}))!=expected: raise RuntimeError("tmpfs inventory drift")
    uid,gid=request.user.split(":")
    work={f"size={request.workspace_bytes}",f"nr_inodes={request.workspace_inodes}","mode=0700",f"uid={uid}",f"gid={gid}","exec","nosuid","nodev"}
    temp={"size=67108864","nr_inodes=4096","mode=0700",f"uid={uid}",f"gid={gid}","noexec","nosuid","nodev"}
    expected_options={"/workspace":work,"/tmp":temp,"/home/sandbox":temp,"/cache":temp}
    if {path:set(options.split(",")) for path,options in host["Tmpfs"].items()}!=expected_options: raise RuntimeError("tmpfs option drift")
    networks=data["NetworkSettings"]["Networks"]
    if context:
        if set(networks)!={context.internal} or networks[context.internal]["IPAddress"]!=context.package_ip: raise RuntimeError("package acquisition endpoint drift")
    elif networks: raise RuntimeError("network-none container has a live endpoint")

def _remaining(deadline):
    remaining=deadline-time.monotonic()
    if remaining<=0: raise TimeoutError("preparation deadline exceeded")
    return min(120,remaining)

def _prepare(name,request,capability,exclude_dependencies=False,deadline=None):
    deadline=deadline or time.monotonic()+120
    _live_input_identity(name,request,capability,deadline)
    copy="cp -R /input/. /workspace/; test -w /workspace; test ! -w /input; test ! -w /; df -Pk /workspace | tail -1; df -Pi /workspace | tail -1"
    result=_run(["docker","exec",name,"sh","-eu","-c",copy],request,_remaining(deadline))
    if result["returncode"]: raise RuntimeError("workspace copy or quota probe failed")
    fields=[line.split() for line in result["stdout"].splitlines() if line.strip()]
    if len(fields)!=2 or any(len(line)<3 for line in fields): raise RuntimeError("workspace quota probe missing")
    blocks,inodes=int(fields[0][1]),int(fields[1][1])
    if blocks>(request.workspace_bytes+1023)//1024+1 or inodes>request.workspace_inodes+max(16,request.workspace_inodes//100): raise RuntimeError("workspace quota exceeds request")
    proof=_verify_copy(name,request,exclude_dependencies,deadline)
    if proof.manifest!=request.staged.manifest or proof.path_kinds!=capability.path_kinds: raise RuntimeError("workspace copy manifest or graph mismatch")
    _reprove_artifact(capability); _live_input_identity(name,request,capability,deadline)

def _execute(name,request):
    command=["docker","exec","--workdir","/workspace"]
    for key,value in request.environment: command.extend(("--env",f"{key}={value}"))
    environment=["/usr/bin/env","-i","PATH=/usr/local/bin:/usr/bin:/bin"]
    environment.extend(f"{key}={value}" for key,value in request.environment)
    command.extend(("--",name,*environment,*request.argv)); return _run_capped_process(command,request)

_run_capped_process=process_transport.run_capped_process
_join_thread=process_transport.join_thread
_kill_process=process_transport.kill_process
_terminate_process=process_transport.terminate_process
def _import_output(name,request,exclude_dependencies=False): return process_transport.import_output(name,request,_run,exclude_dependencies)
def _tar_command(name,exclude_dependencies=False): return process_transport.tar_command(name,exclude_dependencies)
def _verify_copy(name,request,exclude_dependencies=False,deadline=None): return process_transport.verify_copy(name,request,_run,exclude_dependencies,deadline)

def _read_staged_bytes(request,root_fd,relative):
    parts=Path(relative).parts; fd=root_fd; opened=[]
    try:
        for part in parts[:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd); opened.append(child); fd=child
        before=os.stat(parts[-1],dir_fd=fd,follow_symlinks=False); data,after=artifact_staging._read_file(fd,parts[-1],Path(relative),before,[0])
        entry=next((item for item in request.staged.manifest if item.path==relative),None)
        if entry is None or entry.size!=len(data) or entry.sha256!=__import__("hashlib").sha256(data).hexdigest(): raise ValueError("dependency metadata does not match staged manifest")
        return data
    finally:
        for child in reversed(opened): os.close(child)

def _strict_json(data):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError(f"duplicate JSON key: {key}")
            result[key]=value
        return result
    return json.loads(data,object_pairs_hook=pairs,parse_constant=lambda value:(_ for _ in ()).throw(ValueError(f"nonfinite JSON value: {value}")))

def _validate_acquisition(request,capability):
    sensitive={".npmrc","npmrc","auth.json","composer-auth.json",".yarnrc",".yarnrc.yml",".pnpmfile.cjs","pnpm-workspace.yaml",".netrc","_netrc",".curlrc",".wgetrc",".gitconfig","credentials"}
    def unsafe(path):
        folded=path.casefold(); name=Path(folded).name
        return name in sensitive or name.startswith(".yarnrc.") or name.endswith((".pem",".crt",".key")) or "/.ssh/" in f"/{folded}/"
    if any(unsafe(entry.path) for entry in request.staged.manifest): raise ValueError("artifact contains package credential, custom CA, or custom-config file")
    profile=dependency_egress_proxy.ACQUISITION_PROFILES[request.acquisition]
    lock_bytes=_read_staged_bytes(request,capability.root_fd,profile.lock_path); manifest_bytes=_read_staged_bytes(request,capability.root_fd,profile.manifest_path)
    if __import__("hashlib").sha256(lock_bytes).hexdigest()!=profile.lock_sha256 or __import__("hashlib").sha256(manifest_bytes).hexdigest()!=profile.manifest_sha256: raise ValueError("dependency profile digest binding mismatch")
    lock=_strict_json(lock_bytes); manifest=_strict_json(manifest_bytes)
    hosts=dependency_egress_proxy.validate_npm_manifest(lock,manifest) if profile.kind=="npm" else dependency_egress_proxy.validate_composer_lock(lock,manifest)
    if hosts!=profile.allowed_hosts: raise ValueError("dependency profile host binding mismatch")
    return profile

def _acquisition_argv(kind,proxy_ip):
    proxy=f"http://{proxy_ip}:8080"
    prefix=["/usr/bin/env","-i","PATH=/usr/local/bin","HOME=/home/sandbox",f"HTTPS_PROXY={proxy}",f"HTTP_PROXY={proxy}",f"https_proxy={proxy}",f"http_proxy={proxy}","NO_PROXY=","no_proxy="]
    if kind=="npm": return prefix+["npm_config_cache=/workspace/sandbox-cache/npm","npm_config_userconfig=/home/sandbox/empty-npmrc","npm_config_strict_ssl=true","npm_config_maxsockets=8","npm","ci","--ignore-scripts","--no-audit","--no-fund"]
    return prefix+["COMPOSER_HOME=/home/sandbox/composer","COMPOSER_CACHE_DIR=/workspace/sandbox-cache/composer","COMPOSER_MAX_PARALLEL_HTTP=8","/usr/local/bin/php","/usr/bin/composer","install","--no-scripts","--no-plugins","--no-interaction","--no-progress","--prefer-dist"]

def _memory_admission(request):
    available=None
    with open("/proc/meminfo",encoding="ascii") as stream:
        for line in stream:
            if line.startswith("MemAvailable:"): available=int(line.split()[1])*1024; break
    required=_memory_bytes(request.memory)+request.workspace_bytes+PROXY_MEMORY_BYTES+HOST_RESERVE_BYTES
    if available is None or available<required: raise RuntimeError("host memory admission gate failed")
    return available

def _stage_proxy_code(run_token=None,budget=None):
    source=Path(dependency_egress_proxy.__file__).resolve(); before=source.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>1024*1024: raise RuntimeError("proxy source is not a bounded single-link file")
    descriptor=os.open(source,os.O_RDONLY|os.O_NOFOLLOW); lease=None; lease_fd=None; file_fd=None
    try:
        data=os.read(descriptor,before.st_size+1); after=os.fstat(descriptor)
        if len(data)!=before.st_size or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns): raise RuntimeError("proxy source changed while staging")
        digest=hashlib.sha256(data).hexdigest()
        if run_token is None: lease=workspace_lease.create_ephemeral(None,workspace_lease.WorkspacePurpose.ARTIFACT_EXECUTION)
        else:
            if not re.fullmatch(r"[0-9a-f]{16}",run_token): raise ValueError("invalid acquisition run token")
            lease=workspace_lease.create_named(Path(__import__("tempfile").gettempdir()),f"wp-meta-skills-artifact-execution-{run_token}",workspace_lease.WorkspacePurpose.ARTIFACT_EXECUTION)
        lease_fd=artifact_staging._verified_lease_fd(lease)
        target=lease.root/"proxy.py"; out=workspace_lease.create_secure_file(lease_fd,"proxy.py",0o400)
        try:
            workspace_lease._write_all(out,data)
            os.fsync(out)
        finally: os.close(out)
        file_fd=os.open("proxy.py",os.O_RDONLY|os.O_NOFOLLOW,dir_fd=lease_fd)
        proof_budget=budget or source_proof.ProofBudget(); proof=source_proof.prove_proxy(file_fd,proof_budget)
        if proof.sha256!=digest: raise RuntimeError("staged proxy identity or digest mismatch")
        return ProxyCapability(lease,lease_fd,file_fd,str(target.absolute()),digest,proof,proof_budget)
    except Exception:
        if file_fd is not None: os.close(file_fd)
        if lease_fd is not None: os.close(lease_fd)
        if lease is not None: workspace_lease.cleanup(lease)
        raise
    finally: os.close(descriptor)

def _release_proxy_code(capability):
    for descriptor in (capability.file_fd,capability.lease_fd):
        try: os.close(descriptor)
        except OSError: pass
    if workspace_lease._LIVE_LEASES.get(capability.lease.lease_id) is not capability.lease: return
    failure=None
    for _attempt in range(2):
        try: workspace_lease.cleanup(capability.lease); return
        except Exception as exc: failure=exc
    raise RuntimeError(f"proxy code lease cleanup failed: {failure}")

def _create_acquisition_context(request,server_arch,ledger=None,run_token=None,proof_budget=None):
    ledger=ledger if ledger is not None else ResourceLedger()
    token=run_token or uuid.uuid4().hex[:16]
    memory_available=_memory_admission(request); code=_stage_proxy_code(token,proof_budget)
    ledger.record("lease",str(code.lease.root),"created")
    internal=f"wp-acquire-internal-{token}"; egress=f"wp-acquire-egress-{token}"; proxy=f"wp-acquire-proxy-{token}"
    image=_proxy_image(server_arch)
    context=AcquisitionContext(internal,egress,proxy,uuid.uuid4().hex,"","","",image,code,memory_available,ledger)
    try:
        internal_spec=sandbox_network_policy.specification(token,"internal")
        command=sandbox_network_policy.create_command(internal,internal_spec,internal=True,label=f"wp-meta-run={token}")
        ledger.record("network",internal,"attempted")
        result=_control_run(command,60)
        if result["returncode"]: raise RuntimeError(f"internal network creation failed: {sandbox_network_policy.bounded_docker_error(result)}")
        ledger.record("network",internal,"created"); gateway,package_ip,proxy_ip=sandbox_network_policy.inspect(_control_run,internal,internal_spec,internal=True).addresses
        context=replace(context,gateway_ip=gateway,package_ip=package_ip,proxy_ip=proxy_ip)
        egress_spec=sandbox_network_policy.specification(token,"egress")
        command=sandbox_network_policy.create_command(egress,egress_spec,internal=False,label=f"wp-meta-run={token}")
        ledger.record("network",egress,"attempted")
        result=_control_run(command,60)
        if result["returncode"]: raise RuntimeError(f"egress network creation failed: {sandbox_network_policy.bounded_docker_error(result)}")
        ledger.record("network",egress,"created"); sandbox_network_policy.inspect(_control_run,egress,egress_spec,internal=False)
        return context
    except Exception as original:
        try: _cleanup_acquisition(context,"",force=True)
        except Exception as cleanup: raise RuntimeError(f"acquisition context setup failed ({type(original).__name__}: {original}); cleanup also failed ({cleanup})") from original
        raise

def _proxy_create_command(context,hosts,request):
    uid,gid=request.user.split(":")
    temporary=f"/tmp:size=16777216,nr_inodes=1024,mode=0700,uid={uid},gid={gid},noexec,nosuid,nodev"
    command=["docker","create","--pull=never","--name",context.proxy,"--network",context.internal,"--ip",context.proxy_ip,"--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","--user",request.user,"--pids-limit","64","--memory",str(PROXY_MEMORY_BYTES),"--memory-swap",str(PROXY_MEMORY_BYTES),"--cpus","1","--ulimit","nofile=1024:1024","--log-driver","none","--tmpfs",temporary,"--mount",f"type=bind,src={context.proxy_code.source},dst=/proxy.py,readonly","--entrypoint","sleep",context.proxy_image,"infinity"]
    return command

def _proxy_argv(context,hosts):
    return ("/usr/bin/env","-i","/usr/local/bin/python","-I","-S","-B","/proxy.py","--listen",context.proxy_ip,"--peer",context.package_ip,"--hosts",",".join(sorted(hosts)),"--status","/tmp/status.json","--pid-file","/tmp/proxy.pid.json","--nonce",context.nonce)

def _phase_timeout(deadline, limit):
    remaining=deadline-time.monotonic()
    if remaining<=0: raise TimeoutError("proxy lifecycle deadline exceeded")
    return min(limit,remaining)

def _wait_proxy(name,kind,proxy_ip,request,deadline):
    if kind=="npm":
        script=f"const n=require('net');let i=0;function t(){{const s=n.connect(8080,'{proxy_ip}',()=>{{s.destroy();process.exit(0)}});s.on('error',()=>{{if(++i>40)process.exit(1);setTimeout(t,250)}})}}t()"
        command=["docker","exec",name,"node","-e",script]
    else:
        script=f"$i=0; do {{ $s=@fsockopen('{proxy_ip}',8080); if($s){{fclose($s);exit(0);}} usleep(250000); }} while(++$i<40); exit(1);"
        command=["docker","exec",name,"php","-r",script]
    result=_control_run(command,_phase_timeout(deadline,15))
    if result["returncode"]: raise RuntimeError("dependency proxy readiness failed")

def _probe_versions(name,request,profile):
    if profile.kind=="npm": commands=(["node","--version"],["npm","--version"]); expected=("v"+profile.versions[0],profile.versions[1])
    else: commands=(["php","/usr/bin/composer","--version","--no-ansi"],["php","-r","echo PHP_VERSION;"]); expected=(f"Composer version {profile.versions[0]}",profile.versions[1])
    for index,command in enumerate(commands):
        result=_run(["docker","exec",name,*command],request,30); output=result["stdout"].strip()
        if result["returncode"] or (output!=expected[index] if index or profile.kind=="npm" else not output.startswith(expected[index]+" ")): raise RuntimeError("acquisition toolchain version drift")

def _prepare_acquisition_paths(name,request,profile):
    paths=["/workspace/sandbox-cache/npm"] if profile.kind=="npm" else ["/workspace/sandbox-cache/composer","/home/sandbox/composer"]
    result=_run(["docker","exec",name,"mkdir","-p",*paths],request,15)
    if result["returncode"]: raise RuntimeError("acquisition cache preparation failed")
    if profile.kind=="npm":
        result=_run(["docker","exec",name,"touch","/home/sandbox/empty-npmrc"],request,15)
        if result["returncode"]: raise RuntimeError("npm empty userconfig preparation failed")
    else:
        probe=["docker","exec",name,"/usr/bin/env","-i","PATH=/usr/local/bin","/bin/sh","-c","! command -v git && ! command -v ssh"]
        if _run(probe,request,15)["returncode"]: raise RuntimeError("Composer restricted PATH exposes source fallback tools")

def _inspect_proxy(context,name,request):
    result=_control_run(["docker","inspect",context.proxy,name],30)
    if result["returncode"]: raise RuntimeError("acquisition topology inspection failed")
    proxy,package=json.loads(result["stdout"]); host=proxy["HostConfig"]
    image=_control_run(["docker","image","inspect",context.proxy_image,"--format","{{.Id}}"],30)
    if image["returncode"] or proxy["Image"]!=image["stdout"].strip() or proxy["Config"]["User"]!=request.user: raise RuntimeError("proxy identity drift")
    python_preflight.assert_image_environment(proxy["Config"].get("Env"))
    if not host["ReadonlyRootfs"] or host["CapDrop"]!=["ALL"] or host["PidsLimit"]!=64 or host["Memory"]!=PROXY_MEMORY_BYTES or host["MemorySwap"]!=PROXY_MEMORY_BYTES or host["NanoCpus"]!=1_000_000_000: raise RuntimeError("proxy resource boundary drift")
    if host["NetworkMode"]!=context.internal or host.get("RestartPolicy")!={"Name":"no","MaximumRetryCount":0} or host.get("CapAdd"): raise RuntimeError("proxy namespace or restart drift")
    if host.get("PidMode") or host.get("IpcMode") not in {"","private"} or host.get("UTSMode") or host.get("UsernsMode"): raise RuntimeError("proxy namespace sharing drift")
    if host["SecurityOpt"]!=["no-new-privileges:true"] or host["Privileged"] or host.get("PortBindings") or host.get("Binds") or host.get("Dns") or host.get("ExtraHosts") or host.get("Devices"): raise RuntimeError("proxy host surface drift")
    if host.get("Ulimits")!=[{"Name":"nofile","Hard":1024,"Soft":1024}] or host["LogConfig"]["Type"]!="none": raise RuntimeError("proxy process/logging drift")
    uid,gid=request.user.split(":"); temporary={"size=16777216","nr_inodes=1024","mode=0700",f"uid={uid}",f"gid={gid}","noexec","nosuid","nodev"}
    if set(host.get("Tmpfs",{}))!={"/tmp"} or set(host["Tmpfs"]["/tmp"].split(","))!=temporary: raise RuntimeError("proxy tmpfs inventory drift")
    if proxy["Config"].get("Entrypoint")!=["sleep"] or proxy["Config"].get("Cmd")!=["infinity"]: raise RuntimeError("proxy startup command drift")
    env_keys={item.split("=",1)[0].casefold() for item in proxy["Config"].get("Env",[])}
    if env_keys&{"http_proxy","https_proxy","all_proxy","no_proxy","node_extra_ca_certs","requests_ca_bundle","curl_ca_bundle","docker_config"}: raise RuntimeError("proxy inherited host credential or transport environment")
    mounts=proxy["Mounts"]
    if len(mounts)!=1 or mounts[0]["Destination"]!="/proxy.py" or mounts[0]["RW"] or mounts[0].get("Propagation")!="rprivate" or mounts[0]["Source"]!=context.proxy_code.source: raise RuntimeError("proxy code mount drift")
    opened=os.fstat(context.proxy_code.file_fd)
    proof=_control_run(["docker","exec",context.proxy,"python","-c","import hashlib,os; s=os.stat('/proxy.py'); print(f'{s.st_dev}:{s.st_ino}:{s.st_mode&0o777:o}'); print(hashlib.sha256(open('/proxy.py','rb').read()).hexdigest())"],15)
    if proof["returncode"] or proof["stdout"].splitlines()!=[f"{opened.st_dev}:{opened.st_ino}:400",context.proxy_code.sha256]: raise RuntimeError("proxy descriptor identity or digest drift")
    proxy_networks=proxy["NetworkSettings"]["Networks"]; package_networks=package["NetworkSettings"]["Networks"]
    if set(proxy_networks)!={context.internal,context.egress} or proxy_networks[context.internal]["IPAddress"]!=context.proxy_ip: raise RuntimeError("proxy endpoint drift")
    if set(package_networks)!={context.internal} or package_networks[context.internal]["IPAddress"]!=context.package_ip: raise RuntimeError("package endpoint drift")
    internal_spec,egress_spec=sandbox_network_policy.acquisition_specifications(context.internal,context.egress)
    internal_snapshot=sandbox_network_policy.inspect(_control_run,context.internal,internal_spec,internal=True)
    egress_snapshot=sandbox_network_policy.inspect(_control_run,context.egress,egress_spec,internal=False)
    if internal_snapshot.containers!={proxy["Id"],package["Id"]} or egress_snapshot.containers!={proxy["Id"]}: raise RuntimeError("network peer membership drift")

def _read_proxy_status(context,request,deadline=None):
    if context.supervisor is not None:
        return proxy_supervisor.read_status(context.supervisor,lambda command,timeout:_control_run(command,timeout),deadline=deadline)
    uid,gid=request.user.split(":")
    metadata=_control_run(["docker","exec",context.proxy,"stat","-c","%a:%u:%g:%s","/tmp/status.json"],15)
    if metadata["returncode"]: raise RuntimeError("proxy status metadata unavailable")
    fields=metadata["stdout"].strip().split(":")
    if len(fields)!=4 or fields[:3]!=["600",uid,gid] or int(fields[3])>8192: raise RuntimeError("proxy status metadata drift")
    result=_control_run(["docker","exec",context.proxy,"cat","/tmp/status.json"],15)
    if result["returncode"] or len(result["stdout"].encode())>8192: raise RuntimeError("proxy status unavailable or oversized")
    status=_strict_json(result["stdout"]); expected={"nonce","accepted","active","completed","rejected","client_bytes","upstream_bytes"}
    if set(status)!=expected or status["nonce"]!=context.nonce or any(not isinstance(status[key],int) or status[key]<0 for key in expected-{"nonce"}): raise RuntimeError("proxy status is invalid")
    return status

def _live_proxy_source_gate(context,deadline=None):
    opened=os.fstat(context.proxy_code.file_fd)
    timeout=15 if deadline is None else _phase_timeout(deadline,15)
    proof=_control_run(["docker","exec",context.proxy,"python","-c","import hashlib,os; s=os.stat('/proxy.py'); print(f'{s.st_dev}:{s.st_ino}:{s.st_mode&0o777:o}'); print(hashlib.sha256(open('/proxy.py','rb').read()).hexdigest())"],timeout)
    if proof["returncode"] or proof["stdout"].splitlines()!=[f"{opened.st_dev}:{opened.st_ino}:400",context.proxy_code.sha256]: raise RuntimeError("live proxy source identity or digest drift")

def _start_proxy(context,name,request,profile):
    _reprove_proxy(context.proxy_code); _barrier("proxy","pre_create",context.proxy_code.source)
    context.ledger.record("container",context.proxy,"attempted")
    result=_control_run(_proxy_create_command(context,profile.allowed_hosts,request),120)
    if result["returncode"]: raise RuntimeError(f"proxy creation failed: {sandbox_network_policy.bounded_docker_error(result)}")
    context.ledger.record("container",context.proxy,"created")
    context.ledger.record("network",context.internal,"attached")
    _barrier("proxy","post_create_precheck",context.proxy_code.source); _reprove_proxy(context.proxy_code)
    _configured_proxy_mount_gate(context); _reprove_proxy(context.proxy_code); _barrier("proxy","post_final_prestart",context.proxy_code.source)
    result=_control_run(["docker","start",context.proxy],60)
    if result["returncode"]: raise RuntimeError(f"proxy start failed: {sandbox_network_policy.bounded_docker_error(result)}")
    _live_proxy_source_gate(context); _reprove_proxy(context.proxy_code)
    result=_control_run(["docker","network","connect",context.egress,context.proxy],60)
    if result["returncode"]: raise RuntimeError("proxy egress attachment failed")
    context.ledger.record("network",context.egress,"attached"); _inspect_proxy(context,name,request)
    supervisor=proxy_supervisor.launch(context.proxy,context.nonce,_proxy_argv(context,profile.allowed_hosts),request.user,lambda command,timeout:_control_run(command,timeout),request.timeout)
    context=replace(context,supervisor=supervisor)
    try: _wait_proxy(name,profile.kind,context.proxy_ip,request,supervisor.lifecycle_deadline)
    except Exception as original:
        try: proxy_supervisor.abort(supervisor,lambda command,timeout:_control_run(command,timeout))
        except Exception as cleanup: raise RuntimeError(f"proxy readiness failed ({original}); teardown also failed ({cleanup})") from original
        raise
    return context

def _assert_package_process(name,request,deadline=None):
    timeout=15 if deadline is None else _phase_timeout(deadline,15)
    result=_run(["docker","top",name,"-eo","pid,args"],request,timeout)
    lines=[line.split(None,1) for line in result["stdout"].splitlines()[1:] if line.strip()]
    if result["returncode"] or len(lines)!=1 or lines[0][1]!="sleep infinity": raise RuntimeError("package residual process inventory failed")

def _assert_proxy_process(context,request):
    if context.supervisor is None: raise RuntimeError("proxy supervisor is missing")
    proxy_supervisor.process_gate(context.supervisor,lambda command,timeout:_control_run(command,timeout))

def _wait_proxy_idle(context,request):
    if context.supervisor is None: raise RuntimeError("proxy supervisor is missing")
    deadline=min(time.monotonic()+10,context.supervisor.lifecycle_deadline); cadence=time.monotonic()
    for attempt in range(100):
        status=_read_proxy_status(context,request,deadline)
        if status["active"]==0: return status
        delay=min(deadline,cadence+(attempt+1)*0.1)-time.monotonic()
        if delay>0: time.sleep(delay)
    raise RuntimeError("proxy retains active tunnels")

def _stop_proxy(context,request):
    _wait_proxy_idle(context,request)
    if context.supervisor is None: raise RuntimeError("proxy supervisor is missing")
    status=proxy_supervisor.stop(context.supervisor,lambda command,timeout:_control_run(command,timeout))
    if status["active"]!=0: raise RuntimeError("proxy retained active tunnels at shutdown")
    _live_proxy_source_gate(context); _reprove_proxy(context.proxy_code)
    result=_control_run(["docker","stop","-t","1",context.proxy],10)
    if result["returncode"]: raise RuntimeError("proxy sleep PID 1 stop failed")

def _memory_peak(name,request,control=False,deadline=None):
    command=["docker","exec",name,"cat","/sys/fs/cgroup/memory.peak"]
    timeout=10 if deadline is None else _phase_timeout(deadline,10)
    result=_control_run(command,timeout) if control else _run(command,request,timeout)
    if result["returncode"] or not result["stdout"].strip().isdigit(): raise RuntimeError("container peak-memory evidence unavailable")
    return int(result["stdout"].strip())

def _workspace_used(name,request):
    result=_run(["docker","exec",name,"df","-B1","/workspace"],request,10)
    lines=[line.split() for line in result["stdout"].splitlines() if line.strip()]
    if result["returncode"] or len(lines)!=2 or len(lines[1])<3 or not lines[1][2].isdigit(): raise RuntimeError("workspace-use evidence unavailable")
    return int(lines[1][2])

def _dependency_root_gate(name,request):
    roots=("node_modules","vendor","sandbox-cache")
    checks="; ".join(f"if [ -e {root} ] || [ -L {root} ]; then [ -d {root} ] && [ ! -L {root} ] || exit 41; fi" for root in roots)
    result=_run(["docker","exec","--workdir","/workspace",name,"sh","-eu","-c",checks],request,15)
    if result["returncode"]: raise RuntimeError("dependency or cache root is a symlink or special node")

def _remove_retry(command):
    failure=None
    for _attempt in range(2):
        try:
            result=provision.run_capped(command,timeout=60,limit=32768)
            if not result["returncode"]: return
            failure=result["stderr"]
        except Exception as exc: failure=f"{type(exc).__name__}: {exc}"
    raise RuntimeError(f"cleanup failed: {' '.join(command)}: {failure}")

def _cleanup_acquisition(context,name,force=False):
    failures=[]
    if context.supervisor is not None:
        if force: proxy_supervisor.mark_whole_container(context.supervisor)
        try: proxy_supervisor.abort(context.supervisor,lambda command,timeout:_control_run(command,timeout))
        except Exception as exc: failures.append((f"{context.proxy}:exec",str(exc)))
        finally:
            for event in context.supervisor.termination: context.ledger.record("termination",context.proxy,event)
    actions=(("container",context.proxy,["docker","rm","-f",context.proxy]),("container",name,["docker","network","disconnect"]+(["-f"] if force else [])+[context.internal,name]),("network",context.egress,["docker","network","rm",context.egress]),("network",context.internal,["docker","network","rm",context.internal]))
    for kind,resource,command in actions:
        if not context.ledger.needs_cleanup(kind,resource): continue
        try: _remove_retry(command); context.ledger.record(kind,resource,"removed" if kind=="network" or resource==context.proxy else "detached")
        except Exception as exc: failures.append((resource,str(exc))); context.ledger.record(kind,resource,"retained")
    lease_name=str(context.proxy_code.lease.root)
    if context.ledger.needs_cleanup("lease",lease_name):
        try: _release_proxy_code(context.proxy_code); context.ledger.record("lease",lease_name,"removed")
        except Exception as exc: failures.append((lease_name,str(exc))); context.ledger.record("lease",lease_name,"retained")
    if failures:
        retained=", ".join(name for name,_detail in failures)
        recovery=[]
        for resource,_detail in failures:
            if resource==context.proxy: recovery.append(f"docker rm -f {resource}")
            elif resource==name: recovery.append(f"docker network disconnect -f {context.internal} {name}")
            elif resource in {context.internal,context.egress}: recovery.append(f"docker network rm {resource}")
            elif resource==lease_name: recovery.append(f"manual verification required before removing run-owned proxy-code lease {resource}")
        suffix=f"; recovery: {'; '.join(recovery)}" if recovery else ""
        raise RuntimeError(f"acquisition cleanup retained: {retained}{suffix}")

def _acquire(name,request,profile,context,capability):
    _probe_versions(name,request,profile); sandbox_dns_guard.pre_acquisition(name,profile.kind,lambda command,timeout:_run(command,request,timeout)); _prepare_acquisition_paths(name,request,profile); context=_start_proxy(context,name,request,profile)
    deadline=context.supervisor.lifecycle_deadline
    health=lambda:proxy_supervisor.check(context.supervisor)
    result=_run_capped_process(["docker","exec","--workdir","/workspace","--",name,*_acquisition_argv(profile.kind,context.proxy_ip)],request,deadline=deadline,health_check=health)
    if result["returncode"]: raise RuntimeError(f"{profile.kind} acquisition failed")
    health(); _assert_package_process(name,request,deadline); health(); _wait_proxy_idle(context,request); _assert_proxy_process(context,request); proof=_verify_copy(name,request,exclude_dependencies=True,deadline=deadline)
    if proof.manifest!=request.staged.manifest or proof.path_kinds!=capability.path_kinds: raise RuntimeError("nondependency artifact changed during acquisition")
    return context

def _capture_identity(name,context,request,daemon_id,deadline=None):
    timeout=15 if deadline is None else _phase_timeout(deadline,15)
    result=_run(["docker","inspect",name,context.proxy],request,timeout)
    if result["returncode"]: raise RuntimeError("package identity inspection failed")
    timeout=15 if deadline is None else _phase_timeout(deadline,15)
    network=_control_run(["docker","network","inspect",context.internal,"--format","{{.Id}}"],timeout)
    if network["returncode"] or not re.fullmatch(r"[0-9a-f]{64}",network["stdout"].strip()): raise RuntimeError("owned network identity inspection failed")
    data,proxy=json.loads(result["stdout"])
    container_ids=(data.get("Id",""),proxy.get("Id","")); image_ids=(data.get("Image",""),proxy.get("Image",""))
    if any(not re.fullmatch(r"[0-9a-f]{64}",item) for item in container_ids) or any(not re.fullmatch(r"sha256:[0-9a-f]{64}",item) for item in image_ids): raise RuntimeError("container or observed image identity is malformed")
    return DetachedIdentity(data["Id"],data["State"]["StartedAt"],context.internal,daemon_id,network["stdout"].strip(),data["Image"],proxy["Id"],proxy["Image"])

def _runtime_identity(identity,request):
    package_limit=_memory_bytes(request.memory); admission=package_limit+request.workspace_bytes+PROXY_MEMORY_BYTES+HOST_RESERVE_BYTES
    return {"package_container_id":identity.container_id,"proxy_container_id":identity.proxy_container_id,"package_observed_image_id":identity.package_image_id,"proxy_observed_image_id":identity.proxy_image_id,"package_memory_limit_bytes":package_limit,"workspace_limit_bytes":request.workspace_bytes,"proxy_memory_limit_bytes":PROXY_MEMORY_BYTES,"host_reserve_bytes":HOST_RESERVE_BYTES,"admission_required_bytes":admission}

def _detach_acquisition(context,name,request):
    _remove_retry(["docker","rm",context.proxy]); context.ledger.record("container",context.proxy,"removed")
    _remove_retry(["docker","network","disconnect",context.internal,name]); context.ledger.record("container",name,"detached")
    context.ledger.record("network",context.egress,"detached"); context.ledger.record("network",context.internal,"detached")
    for network in (context.egress,context.internal):
        _remove_retry(["docker","network","rm",network]); context.ledger.record("network",network,"removed")
    _release_proxy_code(context.proxy_code); context.ledger.record("lease",str(context.proxy_code.lease.root),"removed")

def _workspace_quota_gate(name,request):
    script="df -Pk /workspace | tail -1; df -Pi /workspace | tail -1"
    result=_run(["docker","exec",name,"sh","-eu","-c",script],request,10)
    fields=[line.split() for line in result["stdout"].splitlines() if line.strip()]
    if result["returncode"] or len(fields)!=2 or any(len(line)<3 for line in fields): raise RuntimeError("detached workspace quota probe failed")
    blocks,inodes=int(fields[0][1]),int(fields[1][1])
    if blocks>(request.workspace_bytes+1023)//1024+1 or inodes>request.workspace_inodes+max(16,request.workspace_inodes//100): raise RuntimeError("detached workspace quota drift")

def _host_listener():
    listener=__import__("socket").socket(); listener.bind(("0.0.0.0",0)); listener.listen(1)
    probe=__import__("socket").socket(__import__("socket").AF_INET,__import__("socket").SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1",80)); address=probe.getsockname()[0]
    finally: probe.close()
    return listener,address,listener.getsockname()[1]

def _node_detached_script(context,host_ip,host_port):
    targets=[(context.proxy_ip,8080),(context.gateway_ip,80),("169.254.169.254",80),("10.0.0.1",80),("192.0.2.1",80),(host_ip,host_port),("fd00::1",80)]
    return """const f=require('fs'),o=require('os'),d=require('dns'),n=require('net');
const badIf=Object.entries(o.networkInterfaces()).some(([k,v])=>k!='lo'&&v.length);if(badIf)process.exit(10);
const r4=f.readFileSync('/proc/net/route','utf8').split('\\n').slice(1);if(r4.some(l=>l.trim()&&l.trim().split(/\\s+/)[0]!='lo'))process.exit(11);
const r6=f.readFileSync('/proc/net/ipv6_route','utf8').split('\\n');if(r6.some(l=>l.trim()&&l.trim().split(/\\s+/).at(-1)!='lo'))process.exit(11);
for(const p of ['/proc/net/tcp','/proc/net/tcp6']){if(f.readFileSync(p,'utf8').split('\\n').slice(1).some(l=>l.trim().split(/\\s+/)[3]=='01'))process.exit(12)}
let pending=2+TARGETS.length,failed=false;const done=()=>{if(!--pending)process.exit(failed?13:0)};
for(const h of ['proxy','registry.npmjs.org'])d.lookup(h,e=>{if(!e)failed=true;done()});
for(const [h,p] of TARGETS){const s=n.connect(p,h,()=>{failed=true;s.destroy();done()});s.setTimeout(1500,()=>{s.destroy();done()});s.on('error',done)}
setTimeout(()=>process.exit(14),1900);""".replace("TARGETS",json.dumps(targets))

def _php_detached_script(context,host_ip,host_port):
    targets=[(context.proxy_ip,8080),(context.gateway_ip,80),("169.254.169.254",80),("10.0.0.1",80),("192.0.2.1",80),(host_ip,host_port),("[fd00::1]",80)]
    encoded=json.dumps(targets,separators=(",",":"))
    return f'''$d=file('/proc/net/dev');foreach($d as $l){{if(str_contains($l,':')&&!str_starts_with(trim($l),'lo:'))exit(10);}}
foreach(array_slice(file('/proc/net/route'),1) as $l){{if(trim($l)&&preg_split('/\\s+/',trim($l))[0]!='lo')exit(11);}}
foreach(file('/proc/net/ipv6_route') as $l){{if(trim($l)&&array_slice(preg_split('/\\s+/',trim($l)),-1)[0]!='lo')exit(11);}}
foreach(['/proc/net/tcp','/proc/net/tcp6'] as $p){{foreach(array_slice(file($p),1) as $l){{if(isset(preg_split('/\\s+/',trim($l))[3])&&preg_split('/\\s+/',trim($l))[3]=='01')exit(12);}}}}
foreach(['proxy','registry.npmjs.org'] as $h){{$r=dns_get_record($h,DNS_A|DNS_AAAA);if($r!==false&&count($r))exit(13);}}
foreach(json_decode('{encoded}') as [$h,$p]){{$s=@fsockopen($h,$p,$e,$m,1);if($s){{fclose($s);exit(14);}}}}'''

def _detached_probe(name,request,profile,context):
    listener,host_ip,host_port=_host_listener()
    try:
        script=_node_detached_script(context,host_ip,host_port) if profile.kind=="npm" else _php_detached_script(context,host_ip,host_port)
        tool="node" if profile.kind=="npm" else "php"
        result=_run(["docker","exec",name,"timeout","2",tool,"-e" if tool=="node" else "-r",script],request,10)
        if result["returncode"]: raise RuntimeError("endpointless route, socket, DNS, or direct-connect denial failed")
    finally: listener.close()

def _endpointless_gate(name,request,profile,context,identity):
    started=time.monotonic(); result=_run(["docker","inspect",name],request,10)
    if result["returncode"]: raise RuntimeError("detached package inspection failed")
    data=json.loads(result["stdout"])[0]; host=data["HostConfig"]
    current_daemon=_run(["docker","info","--format","{{.ID}}"],request,10)
    if current_daemon["returncode"] or current_daemon["stdout"].strip()!=identity.daemon_id: raise RuntimeError("Docker daemon identity changed")
    if data["Id"]!=identity.container_id or data["State"]["StartedAt"]!=identity.started_at or data["RestartCount"]!=0 or not data["State"]["Running"]: raise RuntimeError("detached package identity drift")
    if host["NetworkMode"]!=identity.network_mode or data["NetworkSettings"]["Networks"] or host.get("Dns")!=["127.0.0.1"] or host.get("RestartPolicy")!={"Name":"no","MaximumRetryCount":0}: raise RuntimeError("endpointless namespace inspection failed")
    resolv=_run(["docker","exec",name,"cat","/etc/resolv.conf"],request,5)
    if resolv["returncode"] or "nameserver 127.0.0.11" not in resolv["stdout"] or "ExtServers: [127.0.0.1]" not in resolv["stdout"]: raise RuntimeError("detached DNS configuration drift")
    _assert_package_process(name,request); _workspace_quota_gate(name,request); _detached_probe(name,request,profile,context)
    if time.monotonic()-started>30: raise RuntimeError("complete detached-state gate exceeded 30 seconds")

def _create_started_container(request,name,capability,context,run_ledger):
    _reprove_artifact(capability); _barrier("artifact","pre_create",capability.source)
    command=_create_command(request,name,capability,context.internal if context else None,context.package_ip if context else None)
    ledger=context.ledger if context else run_ledger
    if ledger: ledger.record("container",name,"attempted")
    created=_run(command,request,120)
    if created["returncode"]: raise RuntimeError(f"container creation failed: {sandbox_network_policy.bounded_docker_error(created)}")
    if ledger: ledger.record("container",name,"created")
    if context: context.ledger.record("network",context.internal,"attached")
    _barrier("artifact","post_create_precheck",capability.source); _reprove_artifact(capability)
    _configured_mount_gate(name,request,capability.source,"/input"); _reprove_artifact(capability); _barrier("artifact","post_final_prestart",capability.source)
    deadline=time.monotonic()+120; started=_run(["docker","start",name],request,min(60,_remaining(deadline)))
    if started["returncode"]: raise RuntimeError(f"container start failed: {sandbox_network_policy.bounded_docker_error(started)}")
    return deadline

def _run_live(request,name,capability,profile=None,run_ledger=None):
    run_ledger=run_ledger or ResourceLedger()
    if (preflight:=_run(["docker","info","--format","{{.Architecture}}"],request,30))["returncode"]: return _blocked(request,name,"Docker is unavailable")
    server_arch=_normalize_server_arch(preflight["stdout"]); _validate_image(request,server_arch)
    _assert_local_image(request.image)
    proxy_image_id=_assert_local_image(_proxy_image(server_arch)) if profile else None
    context=None; acquisition_ledger=run_ledger if profile else None; acquisition_clean=False; follower=None; output=None; timings={}; metrics={}; runtime_identity=None; mark=time.monotonic()
    try:
        if profile:
            python_preflight.run(_control_run,_proxy_image(server_arch),proxy_image_id,request.user,name.removeprefix("wp-package-"),run_ledger)
            timings["proxy_interpreter_preflight"]=time.monotonic()-mark; mark=time.monotonic()
        if profile: context=_create_acquisition_context(request,server_arch,acquisition_ledger,name.removeprefix("wp-package-"),capability.budget); timings["acquisition_context_setup"]=time.monotonic()-mark
        mark=time.monotonic(); preparation_deadline=_create_started_container(request,name,capability,context,run_ledger)
        _inspect_boundary(name,request,capability,context,preparation_deadline); _prepare(name,request,capability,bool(context),preparation_deadline); timings["container_setup"]=time.monotonic()-mark
        if context:
            daemon=_run(["docker","info","--format","{{.ID}}"],request,15); mark=time.monotonic()
            if daemon["returncode"]: raise RuntimeError("Docker daemon identity unavailable")
            context=_acquire(name,request,profile,context,capability); timings["dependency_acquisition"]=time.monotonic()-mark
            lifecycle=context.supervisor.lifecycle_deadline
            metrics={"mem_available":context.memory_available,"proxy_memory_peak":_memory_peak(context.proxy,request,True,lifecycle)}; identity=_capture_identity(name,context,request,daemon["stdout"].strip(),lifecycle); runtime_identity=_runtime_identity(identity,request)
            mark=time.monotonic(); _stop_proxy(context,request); follower=docker_event_guard.start(identity.container_id)
            pre_label=f"wp-pre-{uuid.uuid4().hex}"; post_label=f"wp-post-{uuid.uuid4().hex}"
            docker_event_guard.sentinel(follower,name,pre_label); _detach_acquisition(context,name,request); acquisition_clean=True; timings["detach"]=time.monotonic()-mark
            docker_event_guard.await_disconnect(follower,identity.network_id)
            mark=time.monotonic(); _endpointless_gate(name,request,profile,context,identity); timings["detached_gate"]=time.monotonic()-mark
        mark=time.monotonic(); executed=_execute(name,request); timings["generated"]=time.monotonic()-mark; _assert_package_process(name,request)
        if follower:
            docker_event_guard.sentinel(follower,name,post_label); docker_event_guard.finish(follower,identity.network_id,pre_label,post_label); follower=None
        if executed["returncode"]:
            detail=sandbox_evidence.encode("fail",timings,metrics,"generated command failed")
            return SandboxResult("fail",executed["returncode"],executed["stdout"],executed["stderr"],None,detail,name,runtime_identity)
        _live_input_identity(name,request,capability); _reprove_artifact(capability)
        if context: metrics.update(package_memory_peak_pre_export=_memory_peak(name,request),workspace_bytes_used_pre_export=_workspace_used(name,request))
        mark=time.monotonic(); output=_import_output(name,request,bool(context)); timings["export"]=time.monotonic()-mark
        if context: metrics.update(package_memory_peak=_memory_peak(name,request),workspace_bytes_used=_workspace_used(name,request))
        detail=sandbox_evidence.encode("pass",timings,metrics)
        return SandboxResult("pass",0,executed["stdout"],executed["stderr"],output,detail,name,runtime_identity)
    except Exception as original:
        if output is not None: workspace_lease.cleanup(output.lease); output=None
        if follower:
            mark=time.monotonic()
            try: docker_event_guard.abort(follower); timings["event_follower_cleanup"]=time.monotonic()-mark
            except Exception as event_cleanup: original=RuntimeError(f"{original}; event follower cleanup failed: {event_cleanup}")
        if context and not acquisition_clean:
            mark=time.monotonic();
            try: _cleanup_acquisition(context,name,force=True); timings["acquisition_cleanup"]=time.monotonic()-mark
            except Exception as cleanup: original=RuntimeError(f"execution failed ({type(original).__name__}: {original}); cleanup also failed ({cleanup})")
        evidence_ledger=context.ledger if context else acquisition_ledger
        resources=_resource_events(evidence_ledger) if evidence_ledger else []; raise SandboxBoundaryError(f"{type(original).__name__}: {original}",timings,metrics,resources) from original

def _retry_container_cleanup(name):
    try: return provision.run_capped(["docker","rm","-f",name],timeout=60,limit=32768)["returncode"]==0
    except Exception: return False

def _cleanup_package_result(result,name,run_ledger,run_started):
    package_states=[item.state for item in run_ledger.events if item.kind=="container" and item.name==name]
    if not package_states or package_states[-1]=="removed": return replace(result,detail=sandbox_evidence.finalize(result.detail,end_to_end=time.monotonic()-run_started,resources=_resource_events(run_ledger)))
    cleanup_started=time.monotonic()
    try: cleanup=provision.run_capped(["docker","rm","-f",name],timeout=60,limit=32768)
    except Exception as exc:
        retained=not _retry_container_cleanup(name); run_ledger.record("container",name,"retained" if retained else "removed")
        if result.output is not None: workspace_lease.cleanup(result.output.lease)
        recovery=f"; retained {name}; recovery: docker rm -f {name}" if retained else "; retry completed"
        detail=sandbox_evidence.finalize(result.detail,outcome="blocked",error=f"container cleanup raised {type(exc).__name__}{recovery}",timing={"cleanup":time.monotonic()-cleanup_started},end_to_end=time.monotonic()-run_started,resources=_resource_events(run_ledger))
        return replace(result,status="blocked",returncode=None,output=None,detail=detail)
    if cleanup["returncode"]:
        retained=not _retry_container_cleanup(name); run_ledger.record("container",name,"retained" if retained else "removed")
        if result.output is not None: workspace_lease.cleanup(result.output.lease)
        recovery=f"retained {name}; recovery: docker rm -f {name}" if retained else "retry completed"
        detail=sandbox_evidence.finalize(result.detail,outcome="blocked",error=f"container cleanup initially failed; {recovery}",timing={"cleanup":time.monotonic()-cleanup_started},end_to_end=time.monotonic()-run_started,resources=_resource_events(run_ledger))
        return replace(result,status="blocked",returncode=None,output=None,detail=detail)
    run_ledger.record("container",name,"removed")
    detail=sandbox_evidence.finalize(result.detail,timing={"cleanup":time.monotonic()-cleanup_started},end_to_end=time.monotonic()-run_started,resources=_resource_events(run_ledger))
    return replace(result,detail=detail)

def run_sandbox(request:SandboxRequest)->SandboxResult:
    run_started=time.monotonic(); name=f"wp-package-{uuid.uuid4().hex[:16]}"; run_ledger=ResourceLedger()
    try: capability=_validate_request(request,retain=True)
    except Exception as exc:
        result=_blocked(request,name,str(exc)); return replace(result,detail=sandbox_evidence.finalize(result.detail,end_to_end=time.monotonic()-run_started))
    try: profile=_validate_acquisition(request,capability) if request.acquisition else None
    except Exception as exc:
        os.close(capability.root_fd); os.close(capability.lease_fd)
        result=_blocked(request,name,f"dependency preflight failed: {exc}"); return replace(result,detail=sandbox_evidence.finalize(result.detail,end_to_end=time.monotonic()-run_started))
    if platform.system()!="Linux":
        os.close(capability.root_fd); os.close(capability.lease_fd)
        result=_blocked(request,name,"live sandbox requires Linux Docker"); return replace(result,detail=sandbox_evidence.finalize(result.detail,end_to_end=time.monotonic()-run_started))
    try:
        try: result=_run_live(request,name,capability,profile,run_ledger)
        except SandboxBoundaryError as exc: result=_blocked(request,name,f"sandbox boundary failed: {exc}",exc.timings,exc.metrics)
        except Exception as exc: result=_blocked(request,name,f"sandbox boundary failed: {type(exc).__name__}: {exc}")
        return _cleanup_package_result(result,name,run_ledger,run_started)
    finally:
        os.close(capability.root_fd); os.close(capability.lease_fd)
