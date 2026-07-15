"""Repository-owned final Compose canary; never consumes wp-env Compose."""
from __future__ import annotations
import json, os, platform, shutil, tempfile
import re
from pathlib import Path
import artifact_staging
import isolated_runtime_contract as runtime_contract
import runtime_image_provision as provision
import materialize_wordpress_executor_packet as materializer
import wp_runtime_lifecycle
import wp_runtime_provisioning
import wp_runtime_export
import workspace_lease
from wp_runtime_types import RuntimeRequest, RuntimeResult
from wp_runtime_evidence import RuntimeDeadline, failure_evidence
COPY_INPUT_COMMAND="cp -R /input/. /work/"
PREPARE_WORK_ENV="mkdir -p /work/home /work/.npm-cache /work/.composer; export HOME=/work/home npm_config_cache=/work/.npm-cache COMPOSER_HOME=/work/.composer"
TRUSTED_RUNNER_LIMITS={
    "browser-runner":{"memory":"1g","size":536870912,"inodes":50000},
    "wp-env-runner":{"memory":"3g","size":2147483648,"inodes":200000},
}
BLOCK_BUILD_COMMANDS={
    "smoke":"node node_modules/@wordpress/scripts/bin/wp-scripts.js build blocks/runtime-card/index.js --output-path=blocks/runtime-card/build",
    "interactivity":"node node_modules/@wordpress/scripts/bin/wp-scripts.js build --source-path=blocks/interactive-counter --output-path=blocks/interactive-counter/build --experimental-modules",
    "deprecation":"node node_modules/@wordpress/scripts/bin/wp-scripts.js build --source-path=blocks/deprecated-card --output-path=blocks/deprecated-card/build",
}
PHPUNIT_COMMAND="php vendor/bin/phpunit"
TEMP_TMPFS="/tmp:size=67108864,nr_inodes=4096,mode=0700,noexec,nosuid,nodev"
FIXTURE_PHASE_ORDER=("create","start","install","disconnect","execute")
RUNTIME_EVIDENCE_ID=re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
RUNTIME_DIGEST=re.compile(r"[0-9a-f]{64}")
RUNTIME_SLUG=re.compile(r"[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?")

def _blocked_runtime(request,reason):
    return RuntimeResult("blocked",request.evidence_id,request.input_artifact_digest,None,reason=reason)

def _validate_runtime_request(request):
    if not isinstance(request,RuntimeRequest): raise TypeError("runtime request must be a RuntimeRequest")
    if not artifact_staging.has_stage_authority(request.staged,artifact_staging.StageRole.SYNTHESIZED_RUNTIME): raise ValueError("runtime requires a factory-authentic SYNTHESIZED_RUNTIME stage")
    if not RUNTIME_EVIDENCE_ID.fullmatch(request.evidence_id): raise ValueError("runtime evidence ID is missing or invalid")
    if not RUNTIME_DIGEST.fullmatch(request.input_artifact_digest) or not RUNTIME_DIGEST.fullmatch(request.expected_input_artifact_digest): raise ValueError("runtime input artifact digest is invalid")
    if request.input_artifact_digest != request.expected_input_artifact_digest: raise ValueError("runtime input artifact digest mismatch")
    if not RUNTIME_SLUG.fullmatch(request.plugin_slug): raise ValueError("runtime plugin slug is unsafe")
    if request.timeout_sec<30 or request.timeout_sec>1800: raise ValueError("runtime timeout is outside the reviewed range")
    try: profile=runtime_contract.profile_for_requested(request.requested_oracles)
    except ValueError as exc: raise ValueError(str(exc)) from exc
    if profile==runtime_contract.BLOCK_PROFILE and request.block_assertion is None:
        raise ValueError("block runtime profile requires an immutable assertion")
    if profile!=runtime_contract.BLOCK_PROFILE and request.block_assertion is not None:
        raise ValueError("block runtime assertion is forbidden for this runtime profile")
    prefix=request.plugin_slug+"/"
    if not request.staged.manifest or any(not item.path.startswith(prefix) for item in request.staged.manifest): raise ValueError("synthesized runtime is not rooted at the declared plugin slug")
    return request.staged.manifest

def _runtime_project(work):
    return "wpisolated"+__import__("hashlib").sha256(str(work).encode()).hexdigest()[:12]

def _execute_staged_runtime(request,lease,held,deadline):
    runtime=None; export=None; lifecycle=None
    image_cleanup={"component":"runtime_images","state":"not_created","error":None}
    export_cleanup={"component":"runtime_export","state":"not_created","error":None}
    try:
        runtime=wp_runtime_provisioning.provision_runtime(lease.root,deadline)
        project=_runtime_project(lease.root)
        export=wp_runtime_export.materialize_export(
            held,lease.root,request.plugin_slug,runtime,deadline,project,
        )
        seal=wp_runtime_export.seal_export(export,runtime,deadline)
        lifecycle=wp_runtime_lifecycle.execute_runtime(
            lease.root,project,runtime,export.image,request.plugin_slug,
            deadline,request.requested_oracles,export.digest,request.block_assertion,
        )
        lifecycle.setdefault("inspection",{})["artifact_seal"]=seal
    except Exception as exc:
        if isinstance(exc,wp_runtime_export.RuntimeExportCleanupError):
            export_cleanup=exc.cleanup
        if isinstance(exc,wp_runtime_provisioning.RuntimeProvisionError):
            image_cleanup=exc.cleanup
        lifecycle={"status":"blocked","primary":failure_evidence(exc),"reason":failure_evidence(exc)["detail"],
                   "checks":(),"inspection":{},"cleanup":{"component":"compose","state":"not_created"}}
    finally:
        if runtime is not None:
            compose_removed=lifecycle and lifecycle.get("cleanup",{}).get("state") in {"removed","not_created"}
            try:
                if not compose_removed: raise RuntimeError("compose resources remain; images retained for recovery")
                if export is not None: export_cleanup=wp_runtime_export.release_export(export,runtime,deadline)
                if export_cleanup.get("state")=="retained": raise RuntimeError("runtime export remains sealed")
                image_cleanup=wp_runtime_provisioning.cleanup_images(runtime,deadline)
            except Exception as exc: image_cleanup={"component":"runtime_images","state":"retained","error":type(exc).__name__}
    return lifecycle,image_cleanup,export_cleanup

def run_staged_runtime(request:RuntimeRequest)->RuntimeResult:
    """Execute a synthesized artifact only in the inspected internal runtime."""
    _validate_runtime_request(request)
    deadline=RuntimeDeadline.start(request.timeout_sec)
    if platform.system()!="Linux": return _blocked_runtime(request,"isolated generated runtime requires Linux")
    if shutil.which("docker") is None: return _blocked_runtime(request,"Docker is unavailable; host fallback is forbidden")
    lease=workspace_lease.create_ephemeral(request.result_parent,workspace_lease.WorkspacePurpose.ARTIFACT_EXECUTION)
    workspace_cleanup={"component":"runtime_workspace","state":"removed","error":None}
    export_cleanup={"component":"runtime_export","state":"not_created","error":None}
    lifecycle={"status":"blocked","reason":"runtime did not start","checks":(),"inspection":{},"cleanup":{}}
    image_cleanup={"component":"runtime_images","state":"not_created","error":None}
    post_digest=None
    try:
        with artifact_staging.hold_staged_tree(request.staged,proof_deadline=deadline.end) as held:
            lifecycle,image_cleanup,export_cleanup=_execute_staged_runtime(request,lease,held,deadline)
            post_digest=artifact_staging.manifest_sha256(held.proof.manifest)
    finally:
        compose_state=lifecycle.get("cleanup",{}).get("state")
        if compose_state in {"removed","not_created"}:
            try: workspace_lease.cleanup(lease)
            except Exception as exc: workspace_cleanup={"component":"runtime_workspace","state":"retained","error":type(exc).__name__,"recovery":str(lease.root)}
        else:
            export_cleanup={"component":"runtime_export","state":"retained","error":"compose resources remain","recovery":str(lease.root/"runtime-artifact")}
            workspace_cleanup={"component":"runtime_workspace","state":"retained","error":"compose resources remain","recovery":str(lease.root)}
    cleanup={"compose":lifecycle.get("cleanup",{}),"images":image_cleanup,"export":export_cleanup,"workspace":workspace_cleanup}
    status=lifecycle["status"]
    compose_cleanup=lifecycle.get("cleanup",{})
    if any(item.get("state")=="retained" for item in (compose_cleanup,image_cleanup,export_cleanup,workspace_cleanup)): status="blocked"
    return RuntimeResult(status,request.evidence_id,request.input_artifact_digest,post_digest,
        tuple(lifecycle.get("checks",())),lifecycle.get("inspection",{}),cleanup,lifecycle.get("reason"))

def executable_work_tmpfs(size, inodes):
    return f"/work:size={size},nr_inodes={inodes},mode=0700,exec,nosuid,nodev"

def compatibility_failure(name, phase, result, state=None):
    tail=(result.get("stderr") or result.get("stdout") or "")[-2000:].replace("\x00", "")
    state_tail=(state or "")[-1000:].replace("\x00", "")
    return RuntimeError(f"{name} {phase} failed with return code {result.get('returncode')}; state={state_tail}: {tail}")

def execute_failure_diagnostic(container, runtime):
    commands={
      "state":["docker","inspect","--format","{{json .State}}",container],
      "limits":["docker","inspect","--format","{{json .HostConfig.Resources}}",container],
      "stats":["docker","stats","--no-stream","--format","{{json .}}",container],
      "processes":["docker","top",container,"-eo","pid,ppid,stat,comm"],
      "filesystem":["docker","exec",container,"sh","-c","id; ulimit -a; df -Pk /work /tmp; df -Pi /work /tmp; cat /proc/self/cgroup; grep -E ' /work | /tmp ' /proc/mounts || true; for f in /sys/fs/cgroup/memory.events /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.max /sys/fs/cgroup/pids.events /sys/fs/cgroup/pids.current /sys/fs/cgroup/pids.max; do test ! -r $f || { echo $f; cat $f; }; done; stat -c '%A %U:%G %s %n' /work /tmp"],
      "runtime":["docker","exec",container,"sh","-c",("node --version; npm --version; test -x /work/node_modules/.bin/wp-scripts; stat -c '%A %U:%G %s %n' /work/node_modules/.bin/wp-scripts" if runtime=="node" else "php --version; php -r 'echo PHP_BINARY, PHP_EOL;'; test -x /work/vendor/bin/phpunit; stat -c '%A %U:%G %s %n' /work/vendor/bin/phpunit")],
    }
    evidence={"container":container,"runtime":runtime}
    for name,command in commands.items():
        try: evidence[name]=provision.run_capped(command,timeout=15,limit=32768)
        except Exception as exc: evidence[name]={"diagnostic_error":type(exc).__name__}
    return evidence

def compose_start_failure_diagnostic(base):
    try:
        ids=provision.run_capped(base+["ps","-aq"],timeout=15,limit=4096)
    except Exception as exc:
        return {"stage":"container_ids","error":type(exc).__name__}
    containers=ids.get("stdout","").split()
    if ids.get("returncode") or not containers:
        return {"container_ids":ids,"inspection":None}
    template=('{"name":{{json .Name}},"state":{"status":{{json .State.Status}},'
              '"running":{{json .State.Running}},"paused":{{json .State.Paused}},'
              '"restarting":{{json .State.Restarting}},"oom_killed":{{json .State.OOMKilled}},'
              '"dead":{{json .State.Dead}},"pid":{{json .State.Pid}},'
              '"exit_code":{{json .State.ExitCode}},"error":{{json .State.Error}},'
              '"started_at":{{json .State.StartedAt}},"finished_at":{{json .State.FinishedAt}}},'
              '"networks":{{json .NetworkSettings.Networks}}}')
    try:
        inspected=provision.run_capped(
            ["docker","inspect","--format",template,*containers],timeout=15,limit=32768,
        )
    except Exception as exc:
        inspected={"stage":"inspection","error":type(exc).__name__}
    return {"container_ids":{"returncode":0,"count":len(containers)},"inspection":inspected}

def compose_start_failure(result,base):
    try:
        diagnostic=compose_start_failure_diagnostic(base)
    except Exception as exc:
        diagnostic={"stage":"diagnostic","error":type(exc).__name__}
    return RuntimeError(f"{result['stderr']}; diagnostic={json.dumps(diagnostic,sort_keys=True)}")

WRITABLE_PATHS={"database":{"/var/lib/mysql","/run/mysqld","/tmp"},"wordpress":{"/tmp","/var/www/html/wp-content/uploads"},"cli":{"/tmp"},"browser":{"/tmp"}}
SERVICE_NETWORKS={
    "database":["wp_db"],
    "wordpress":{"wp_db":{},"browser_wp":{"aliases":["wordpress-application"]}},
    "cli":["wp_db"],
    "browser":["browser_wp"],
}
WORDPRESS_IMAGE_ACTIVE_CONFIG={
  "User":"www-data",
  "ExposedPorts":{"8080/tcp":{}},
  "Env":["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin","PHP_INI_DIR=/usr/local/etc/php","APACHE_CONFDIR=/etc/apache2","APACHE_ENVVARS=/etc/apache2/envvars"],
  "WorkingDir":"/var/www/html",
  "Entrypoint":["/usr/local/bin/wp-sandbox-entrypoint"],
  "StopSignal":"SIGWINCH",
}

def validate_wordpress_image_config(config):
    if config.get("Volumes") not in (None,{}): raise RuntimeError("WordPress image inherited writable volume metadata")
    active={key:value for key,value in config.items() if value not in (None,False,"",[],{})}
    if active != WORDPRESS_IMAGE_ACTIVE_CONFIG: raise RuntimeError("WordPress image active metadata drift")
    return True

def validate_live_tmpfs_inventory(inspected, service, expected):
    if inspected.get("Mounts"): raise RuntimeError(f"{service} live non-tmpfs mount detected")
    actual={path:set(options.split(",")) for path,options in inspected["HostConfig"].get("Tmpfs",{}).items()}
    if set(actual) != WRITABLE_PATHS[service] or actual != expected: raise RuntimeError(f"{service} live tmpfs options mismatch")
    return actual

def parse_tag_manifest(payload, arch):
    resolved=json.loads(payload)
    children={item["platform"]["architecture"]:item["digest"] for item in resolved.get("manifests",[]) if item.get("platform",{}).get("os")=="linux"}
    if not resolved.get("digest") or arch not in children: raise RuntimeError("registry manifest output is incomplete")
    return resolved["digest"],children[arch]

def verify_wp_cli_result(result, expected):
    if result["returncode"] or not result["stdout"].split() or result["stdout"].split()[0] != expected: raise RuntimeError("built WP-CLI SHA-256 mismatch")

def validate_df_profile(output, size_bytes, nr_inodes):
    lines=[line.split() for line in output.splitlines() if line.strip()]
    if len(lines) != 2 or any(len(line)<3 for line in lines): raise RuntimeError("missing or unparsed tmpfs df profile")
    try: blocks=int(lines[0][1]); inodes=int(lines[1][1])
    except ValueError as exc: raise RuntimeError("missing or unparsed tmpfs df profile") from exc
    block_limit=(size_bytes+1023)//1024+1
    inode_limit=nr_inodes+max(16,(nr_inodes+99)//100)
    if blocks<=0 or inodes<=0 or blocks>block_limit or inodes>inode_limit: raise RuntimeError("tmpfs df profile exceeds reviewed limit")
    return {"blocks_1k":blocks,"inodes":inodes,"reviewed_size_bytes":size_bytes,"reviewed_nr_inodes":nr_inodes,"block_rounding_tolerance":1,"inode_rounding_tolerance":inode_limit-nr_inodes}

def runtime_probe_specs(base):
    browser=lambda script:base+["exec","-T","browser","node","-e",script]
    cli=lambda *args:base+["exec","-T","cli",*args]
    db_ready="test $(id -u) != 0; wp --info; i=0; until php -r 'mysqli_report(MYSQLI_REPORT_OFF);$m=@new mysqli(\"database\",\"wordpress\",\"wordpress-canary\",\"wordpress\",3306);exit($m->connect_errno?1:0);'; do i=$((i+1)); test $i -lt 60; sleep 1; done; wp core install --url=http://wordpress-application:8080 --title='Sandbox Canary' --admin_user=sandbox --admin_password=not-a-secret-canary --admin_email=sandbox@example.invalid --skip-email; test \"$(wp option get siteurl)\" = http://wordpress-application:8080"
    return (
      {"name":"cli-db-ready","command":cli("sh","-c",db_ready),"timeout":70},
      {"name":"browser-wordpress-http","network":True,"self_timeout":True,"command":browser("fetch('http://wordpress-application:8080',{signal:AbortSignal.timeout(5000)}).then(r=>process.exit(r.ok?0:1),()=>process.exit(1))"),"timeout":10},
      {"name":"browser-public-http-denied","network":True,"self_timeout":True,"command":browser("fetch('https://example.com',{signal:AbortSignal.timeout(3000)}).then(()=>process.exit(1),()=>process.exit(0))"),"timeout":8},
      {"name":"browser-private-http-denied","network":True,"self_timeout":True,"command":browser("const t=['http://host.docker.internal','http://169.254.169.254','http://10.0.0.1','http://127.0.0.1'];Promise.all(t.map(u=>fetch(u,{signal:AbortSignal.timeout(2000)}).then(()=>{throw Error('escaped')},()=>true))).then(()=>process.exit(0),()=>process.exit(1))"),"timeout":8},
      {"name":"browser-public-dns-denied","network":True,"self_timeout":True,"command":browser("const {Resolver}=require('dns');const r=new Resolver({timeout:1000,tries:1});const t=setTimeout(()=>process.exit(0),2500);r.resolve4('example.com',e=>{clearTimeout(t);process.exit(e?0:1)})"),"timeout":6},
      {"name":"browser-database-peer-denied","network":True,"self_timeout":True,"command":browser("const n=require('net');const s=n.connect(3306,'database',()=>process.exit(1));s.on('error',()=>process.exit(0));setTimeout(()=>{s.destroy();process.exit(0)},2000)"),"timeout":6},
      {"name":"browser-public-websocket-denied","network":True,"self_timeout":True,"command":browser("const w=new WebSocket('ws://example.com');w.onopen=()=>process.exit(1);w.onerror=()=>process.exit(0);setTimeout(()=>{w.close();process.exit(0)},2500)"),"timeout":6},
      {"name":"php-routes-denied","network":True,"self_timeout":True,"command":cli("php","-r","foreach (array('93.184.216.34','169.254.169.254','10.0.0.1','127.0.0.1') as $h) { $s=@fsockopen($h,80,$e,$m,1); if ($s) exit(1); }"),"timeout":8},
      {"name":"php-public-dns-denied","network":True,"self_timeout":True,"allowed":{0,124},"command":cli("sh","-c","timeout 5 php -r \"exit(dns_get_record('example.com') ? 1 : 0);\""),"timeout":8},
      {"name":"browser-byte-quota","command":browser("const f=require('fs');f.writeFileSync('/tmp/quota',Buffer.alloc(60*1024*1024));try{f.appendFileSync('/tmp/quota',Buffer.alloc(8*1024*1024));process.exit(1)}catch(e){f.unlinkSync('/tmp/quota')}"),"timeout":15},
      {"name":"browser-inode-quota","command":browser("const f=require('fs');let failed=false,i=0;for(;i<5000;i++){try{f.writeFileSync('/tmp/i'+i,'')}catch(e){failed=true;break}}if(!failed)process.exit(1);for(let j=0;j<i;j++)f.unlinkSync('/tmp/i'+j);f.writeFileSync('/tmp/.inode-recovered','');f.unlinkSync('/tmp/.inode-recovered')"),"timeout":30},
    )

def run_named_probe(spec):
    try: result=provision.run_capped(spec["command"],timeout=spec["timeout"],limit=32768)
    except Exception as exc: raise RuntimeError(f"probe {spec['name']} raised {type(exc).__name__}") from exc
    if result["returncode"] not in spec.get("allowed",{0}):
        tail=((result.get("stderr") or "")+(result.get("stdout") or ""))[-2000:].replace("\x00","")
        raise RuntimeError(f"probe {spec['name']} failed rc={result['returncode']}: {tail}")
    return result

def prove_fixture_locks(work, inv, arch):
    suites=Path(__file__).parent.parent/"suites"; fixtures=work/"fixtures"; fixtures.mkdir()
    node_image=f"node@{provision.platform_digest(inv['node'],arch)}"
    for runner in ("browser-runner","wp-env-runner"):
        source=Path(__file__).parent/runner
        limits=TRUSTED_RUNNER_LIMITS[runner]
        work_tmpfs=executable_work_tmpfs(limits["size"],limits["inodes"])
        command=["docker","run","--rm","--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","--pids-limit","256","--memory",limits["memory"],"--tmpfs",work_tmpfs,"--tmpfs",TEMP_TMPFS,"--mount",f"type=bind,src={source},dst=/input,readonly",node_image,"sh","-eu","-c",f"{COPY_INPUT_COMMAND}; {PREPARE_WORK_ENV}; cd /work; npm ci --ignore-scripts --no-audit --no-fund"]
        result=provision.run_capped(command,timeout=900,limit=1048576)
        if result["returncode"]: raise RuntimeError(f"trusted {runner} lock failed: {result['stderr']}")
    packets=(("smoke","block","wordpress-block-executor/examples/smoke-wordpress-v1.materializable-packet.md"),("interactivity","block","wordpress-block-executor/examples/interactivity-wordpress-v1.materializable-packet.md"),("deprecation","block","wordpress-block-executor/examples/deprecation-wordpress-v1.materializable-packet.md"),("phpunit","plugin","wordpress-plugin-executor/examples/phpunit-wordpress-v1.materializable-packet.md"))
    for name,executor,relative in packets:
        target=fixtures/name; result=materializer.materialize_packet(executor,(suites/relative).read_text(),target)
        if not result["pass"]: raise RuntimeError(f"fixture materialization failed: {name}")
        source=target/("acme-runtime-tested" if name=="phpunit" else "")
        if name=="phpunit":
            image=f"composer@{provision.platform_digest(inv['composer'],arch)}"; install="PATH=/usr/local/bin:/bin php /usr/bin/composer install --no-interaction --no-progress --no-scripts --no-plugins --prefer-dist"; execute=PHPUNIT_COMMAND
        else:
            image=f"node@{provision.platform_digest(inv['node'],arch)}"; install="npm ci --ignore-scripts --no-audit --no-fund"; execute=BLOCK_BUILD_COMMANDS[name]
        container=f"wp-step0-fixture-{name}-{__import__('hashlib').sha256(str(work).encode()).hexdigest()[:8]}"
        create=["docker","create","--name",container,"--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","--pids-limit","256","--memory","2g","--tmpfs",executable_work_tmpfs(1073741824,100000),"--tmpfs",TEMP_TMPFS,"--mount",f"type=bind,src={source},dst=/input,readonly","--entrypoint","sh",image,"-c","sleep infinity"]
        try:
            phases=(
                ("create",create),
                ("start",["docker","start",container]),
                ("install",["docker","exec",container,"sh","-eu","-c",f"{COPY_INPUT_COMMAND}; {PREPARE_WORK_ENV}; cd /work; {install}"]),
                ("disconnect",["docker","network","disconnect","bridge",container]),
                ("execute",["docker","exec",container,"sh","-eu","-c",f"{PREPARE_WORK_ENV}; cd /work; {execute}"]),
            )
            if tuple(phase for phase,_command in phases) != FIXTURE_PHASE_ORDER: raise RuntimeError("fixture phase order drift")
            for phase,command in phases:
                result=provision.run_capped(command,timeout=900,limit=1048576)
                if result["returncode"]:
                    if phase=="execute":
                        diagnostic=execute_failure_diagnostic(container,"composer" if name=="phpunit" else "node")
                        raise RuntimeError(f"{name} execute failed with return code {result['returncode']}; diagnostic={json.dumps(diagnostic,sort_keys=True)}")
                    state=provision.run_capped(["docker","inspect",container,"--format","{{json .State}}"],timeout=30,limit=4096)
                    raise compatibility_failure(name,phase,result,state.get("stdout") or state.get("stderr"))
        finally: provision.run_capped(["docker","rm","-f",container],timeout=120)

def canary_compose(built_images=None, identities=None):
    inv=provision.inventory()["images"]; arch=platform.machine()
    image=lambda key:f"{inv[key]['tag'].split(':')[0]}@{provision.platform_digest(inv[key],arch)}"
    built_images=built_images or {"database":"sha256:"+"0"*64,"wordpress":"sha256:"+"0"*64}
    identities=identities or {"database":"999:999","wordpress":"33:33","browser":"1000:1000"}
    limits={"security_opt":["no-new-privileges:true"],"pids_limit":128,"mem_limit":"512m","cpus":"1.0","ulimits":{"nofile":{"soft":1024,"hard":1024}},"logging":{"driver":"none"}}
    return {"services":{
      "database":{**limits,"image":built_images["database"],"read_only":True,"cap_drop":["ALL"],"user":identities["database"],"networks":["wp_db"],"tmpfs":[f"/var/lib/mysql:uid={identities['database'].split(':')[0]},gid={identities['database'].split(':')[1]},mode=0700,size=134217728,nr_inodes=8192",f"/run/mysqld:uid={identities['database'].split(':')[0]},gid={identities['database'].split(':')[1]},mode=0700,size=8388608,nr_inodes=512",f"/tmp:uid={identities['database'].split(':')[0]},gid={identities['database'].split(':')[1]},mode=0700,size=16777216,nr_inodes=1024"]},
      "wordpress":{**limits,"image":built_images["wordpress"],"read_only":True,"cap_drop":["ALL"],"user":identities["wordpress"],"networks":{"wp_db":{},"browser_wp":{"aliases":["wordpress-application"]}},"tmpfs":[f"/tmp:uid={identities['wordpress'].split(':')[0]},gid={identities['wordpress'].split(':')[1]},mode=0700,size=33554432,nr_inodes=2048",f"/var/www/html/wp-content/uploads:uid={identities['wordpress'].split(':')[0]},gid={identities['wordpress'].split(':')[1]},mode=0700,size=33554432,nr_inodes=2048"]},
      "cli":{**limits,"image":built_images["wordpress"],"read_only":True,"cap_drop":["ALL"],"user":identities["wordpress"],"entrypoint":["sleep"],"command":["infinity"],"networks":["wp_db"],"tmpfs":[f"/tmp:uid={identities['wordpress'].split(':')[0]},gid={identities['wordpress'].split(':')[1]},mode=0700,size=16777216,nr_inodes=1024"]},
      "browser":{**limits,"image":image("playwright"),"read_only":True,"cap_drop":["ALL"],"user":identities["browser"],"command":["sleep","infinity"],"networks":["browser_wp"],"tmpfs":[f"/tmp:uid={identities['browser'].split(':')[0]},gid={identities['browser'].split(':')[1]},mode=0700,size=67108864,nr_inodes=4096"]}},
      "networks":{"wp_db":{"internal":True},"browser_wp":{"internal":True}}}

def validate_compose(spec):
    if set(spec) != {"services","networks"}: raise RuntimeError("unknown top-level Compose field")
    allowed={"database","wordpress","cli","browser"}
    if set(spec.get("services",{})) != allowed: raise RuntimeError("unlisted final service")
    if spec.get("networks") != {"wp_db":{"internal":True},"browser_wp":{"internal":True}}: raise RuntimeError("network schema drift")
    base={"image","read_only","cap_drop","user","networks","tmpfs","security_opt","pids_limit","mem_limit","cpus","ulimits","logging"}
    extras={"database":set(),"wordpress":set(),"cli":{"entrypoint","command"},"browser":{"command"}}
    for name,service in spec["services"].items():
        if set(service) != base|extras[name]: raise RuntimeError(f"unknown or missing {name} service field")
        if service["networks"] != SERVICE_NETWORKS[name]: raise RuntimeError(f"network attachment drift: {name}")
        if name == "cli" and (service["entrypoint"] != ["sleep"] or service["command"] != ["infinity"]): raise RuntimeError("CLI command drift")
        if name == "browser" and service["command"] != ["sleep","infinity"]: raise RuntimeError("browser command drift")
        if not service.get("read_only") or service.get("cap_drop") != ["ALL"] or service.get("security_opt") != ["no-new-privileges:true"]: raise RuntimeError(f"unsafe {name} service")
        if not re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*",service.get("user","")): raise RuntimeError(f"non-numeric {name} user")
        if service["pids_limit"] != 128 or service["mem_limit"] != "512m" or service["cpus"] != "1.0" or service["ulimits"] != {"nofile":{"soft":1024,"hard":1024}} or service["logging"] != {"driver":"none"}: raise RuntimeError(f"resource drift: {name}")
        image=service.get("image","")
        if "@sha256:" not in image and not image.startswith("sha256:"): raise RuntimeError(f"unpinned {name} image")
        for mount in service.get("tmpfs",[]):
            if ":" not in mount: raise RuntimeError("unbounded tmpfs")
            options=dict(item.split("=",1) for item in mount.split(":",1)[1].split(","))
            if set(options) != {"uid","gid","mode","size","nr_inodes"} or options["mode"] != "0700" or options["uid"] != service["user"].split(":")[0] or options["gid"] != service["user"].split(":")[1]: raise RuntimeError("invalid tmpfs options")
        if {mount.split(":",1)[0] for mount in service.get("tmpfs",[])} != WRITABLE_PATHS[name]: raise RuntimeError(f"writable path inventory mismatch: {name}")
    if not all(n.get("internal") is True for n in spec["networks"].values()): raise RuntimeError("egress-capable network")
    return True

def write_canary(path, built_images=None, identities=None):
    spec=canary_compose(built_images,identities); validate_compose(spec); path.write_text(json.dumps(spec,indent=2)+"\n",encoding="utf-8"); return spec

def run_linux_canary(work, result_path=None):
    if platform.system() != "Linux": return {"status":"blocked","reason":"live Docker boundary requires Linux"}
    commit_sha=os.environ.get("CANARY_COMMIT_SHA","")
    if os.environ.get("GITHUB_ACTIONS")=="true" and not re.fullmatch(r"[0-9a-f]{40}",commit_sha): raise RuntimeError("exact canary commit SHA is missing")
    requested=Path(work)
    lease=workspace_lease.create_named(requested.parent,requested.name,workspace_lease.WorkspacePurpose.ARTIFACT_EXECUTION)
    run_id=__import__("hashlib").sha256(str(lease.root).encode()).hexdigest()[:12]
    try:
        result=_run_linux_canary(lease.root)
        result["commit_sha"]=commit_sha
        result["workflow_url"]=(f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}" if all(key in os.environ for key in ("GITHUB_SERVER_URL","GITHUB_REPOSITORY","GITHUB_RUN_ID")) else "")
        result["inventory_sha256"]=__import__("hashlib").sha256(provision.INVENTORY.read_bytes()).hexdigest()
        if result_path is not None: Path(result_path).write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        return result
    finally:
        active_error=__import__("sys").exc_info()[0] is not None
        cleanup_error=None
        try: provision.run_capped(["docker","image","rm","-f",f"wp-sandbox-wordpress:{run_id}",f"wp-sandbox-database:{run_id}"],timeout=120)
        except Exception as exc: cleanup_error=exc
        try: workspace_lease.cleanup(lease)
        except Exception as exc: cleanup_error=cleanup_error or exc
        if cleanup_error is not None and not active_error: raise cleanup_error

def _review_upstream_images(inv,arch):
    arch_key=provision.normalize_arch(arch)
    engine_arch=provision.run_capped(["docker","info","--format","{{.Architecture}}"])["stdout"].strip()
    if provision.normalize_arch(engine_arch) != arch_key: raise RuntimeError("Docker engine architecture mismatch")
    upstream={key:f"{item['tag'].split(':')[0]}@{provision.platform_digest(item,arch)}" for key,item in inv.items()}
    for key,reference in upstream.items():
        manifest=provision.run_capped(["docker","buildx","imagetools","inspect",inv[key]["tag"],"--format","{{json .Manifest}}"],timeout=300,limit=1048576)
        if manifest["returncode"]: raise RuntimeError(f"tag inspection failed: {inv[key]['tag']}")
        index_digest,child_digest=parse_tag_manifest(manifest["stdout"],arch_key)
        if index_digest != inv[key]["index"] or child_digest != provision.platform_digest(inv[key],arch): raise RuntimeError(f"reviewed tag provenance drift: {key}")
        result=provision.run_capped(["docker","pull",reference],timeout=900,limit=1048576)
        if result["returncode"]: raise RuntimeError(f"reviewed image pull failed: {reference}: {result['stderr']}")
        inspected=json.loads(provision.run_capped(["docker","image","inspect",reference])["stdout"])[0]
        if not inspected["Id"].startswith("sha256:") or not any(value.endswith(provision.platform_digest(inv[key],arch)) for value in inspected.get("RepoDigests",[])): raise RuntimeError(f"pulled child provenance mismatch: {key}")
    return upstream


def _build_canary_images(work,inventory,inv,arch,wp_tag,db_tag):
    wpctx,dbctx,_browserctx=wp_runtime_provisioning.prepare_build_contexts(work,inventory)
    commands=[
      ["docker","build","--network=none","--pull=false","-t",wp_tag,"--build-arg",f"WORDPRESS_BASE=wordpress@{provision.platform_digest(inv['wordpress'],arch)}","--build-arg",f"CLI_BASE=wordpress@{provision.platform_digest(inv['wordpress_cli'],arch)}","--build-arg",f"WP_CLI_SHA256={inventory['wp_cli_binary']['sha256']}","--build-arg",f"PLUGIN_CHECK_SHA256={inventory['plugin_check']['sha256']}",str(wpctx)],
      ["docker","build","--network=none","--pull=false","-t",db_tag,"--build-arg",f"DATABASE_BASE=mariadb@{provision.platform_digest(inv['database'],arch)}",str(dbctx)]]
    for command in commands:
        result=provision.run_capped(command,timeout=900)
        if result["returncode"]: raise RuntimeError(result["stderr"])
    built={key:provision.run_capped(["docker","image","inspect",tag,"--format","{{.Id}}"])["stdout"].strip() for key,tag in (("wordpress",wp_tag),("database",db_tag))}
    if not all(value.startswith("sha256:") for value in built.values()): raise RuntimeError("missing built image ID")
    wordpress_config=json.loads(provision.run_capped(["docker","image","inspect",built["wordpress"]])["stdout"])[0]["Config"]
    validate_wordpress_image_config(wordpress_config)
    wp_cli=provision.run_capped(["docker","run","--rm","--entrypoint","sha256sum",built["wordpress"],"/usr/local/bin/wp"])
    verify_wp_cli_result(wp_cli,inventory["wp_cli_binary"]["sha256"])
    return built


def _image_identity(image,user):
    result=provision.run_capped(["docker","run","--rm","--entrypoint","sh",image,"-c",f"id -u {user}; id -g {user}"])
    if result["returncode"]: raise RuntimeError(result["stderr"])
    uid,gid=result["stdout"].splitlines()
    return f"{uid}:{gid}"


def _prepare_canary_compose(work,built,inv,arch):
    playwright=f"{inv['playwright']['tag'].split(':')[0]}@{provision.platform_digest(inv['playwright'],arch)}"
    identities={"wordpress":_image_identity(built["wordpress"],"www-data"),
                "database":_image_identity(built["database"],"mysql"),
                "browser":_image_identity(playwright,"pwuser")}
    compose=work/"compose.json"
    write_canary(compose,built,identities)
    return compose,identities,playwright


def _inspect_tmpfs_profiles(cid,service,built,identities):
    profiles=[]; targets={"size":{},"inodes":{}}
    mounts=canary_compose(built,identities)["services"][service]["tmpfs"]
    mount_specs={entry.split(":",1)[0]:dict(item.split("=",1) for item in entry.split(":",1)[1].split(",")) for entry in mounts}
    for path,options in mount_specs.items():
        writable=provision.run_capped(["docker","exec",cid,"sh","-eu","-c",f"test -w {path}; touch {path}/.wp-step0-write; rm {path}/.wp-step0-write; ! touch /.wp-step0-forbidden; df -Pk {path} | tail -1; df -Pi {path} | tail -1"])
        if writable["returncode"]: raise RuntimeError(f"{service} writable ownership/quota profile failed")
        profile=validate_df_profile(writable["stdout"],int(options["size"]),int(options["nr_inodes"]))
        profile.update(service=service,path=path); profiles.append(profile)
        targets["size"].setdefault(int(options["size"]),(cid,path))
        targets["inodes"].setdefault(int(options["nr_inodes"]),(cid,path))
    return profiles,targets


def _inspect_canary_service(base,service,image_tag,built,identities):
    expected=provision.run_capped(["docker","image","inspect",image_tag,"--format","{{.Id}}"])["stdout"].strip()
    cid=provision.run_capped(base+["ps","-q",service])["stdout"].strip()
    live=provision.run_capped(["docker","inspect",cid,"--format","{{.Image}}"])["stdout"].strip()
    if not expected or live != expected: raise RuntimeError(f"{service} live image ID mismatch")
    inspected=json.loads(provision.run_capped(["docker","inspect",cid])["stdout"])[0]
    host=inspected["HostConfig"]
    if not host["ReadonlyRootfs"] or host["CapDrop"] != ["ALL"] or host["PidsLimit"] != 128 or host["Memory"] != 536870912 or host["NanoCpus"] != 1000000000: raise RuntimeError(f"{service} live resource policy mismatch")
    if host["SecurityOpt"] != ["no-new-privileges:true"] or host["LogConfig"]["Type"] != "none": raise RuntimeError(f"{service} live security/default-seccomp policy mismatch")
    if host["Privileged"] or host.get("Binds") or host.get("Devices") or host.get("PortBindings") or host.get("ExtraHosts") or host.get("Dns") or host.get("DnsSearch"): raise RuntimeError(f"{service} live forbidden host surface")
    if host.get("Ulimits") != [{"Name":"nofile","Hard":1024,"Soft":1024}]: raise RuntimeError(f"{service} live nofile drift")
    if any(item.split("=",1)[0].lower().endswith("proxy") for item in inspected["Config"].get("Env",[])): raise RuntimeError(f"{service} inherited proxy environment")
    expected_tmpfs={entry.split(":",1)[0]:set(entry.split(":",1)[1].split(",")) for entry in canary_compose(built,identities)["services"][service]["tmpfs"]}
    validate_live_tmpfs_inventory(inspected,service,expected_tmpfs)
    if not inspected["Config"]["User"].split(":")[0].isdigit(): raise RuntimeError(f"{service} live user is not numeric")
    networks={name.rsplit("_",1)[-1] for name in inspected["NetworkSettings"]["Networks"]}
    expected_networks={"database":{"db"},"cli":{"db"},"wordpress":{"db","wp"},"browser":{"wp"}}[service]
    if networks != expected_networks: raise RuntimeError(f"{service} live network inventory mismatch")
    gateways={value["Gateway"] for value in inspected["NetworkSettings"]["Networks"].values() if value.get("Gateway")}
    return live,cid,gateways,_inspect_tmpfs_profiles(cid,service,built,identities)


def _inspect_canary_services(base,built,identities,wp_tag,db_tag,playwright):
    live_ids={}; gateways=set(); profiles=[]; targets={"size":{},"inodes":{}}
    services=(("wordpress",wp_tag),("cli",wp_tag),("database",db_tag),("browser",playwright))
    for service,image_tag in services:
        live,_cid,found,storage=_inspect_canary_service(base,service,image_tag,built,identities)
        live_ids[service]=live; gateways.update(found); profiles.extend(storage[0])
        for kind in targets:
            for limit,target in storage[1][kind].items(): targets[kind].setdefault(limit,target)
    return live_ids,gateways,profiles,targets


def _prove_quota_exhaustion(targets):
    exhaustion=[]
    for size,(cid,path) in targets["size"].items():
        script=f"set -eu; a=$(df -Pk {path}|tail -1|awk '{{print $4}}'); n=$((a>16?a-8:1)); dd if=/dev/zero of={path}/.byte-fill bs=1024 count=$n 2>/dev/null; if dd if=/dev/zero of={path}/.byte-over bs=1024 count=16 2>/dev/null; then exit 1; fi; rm -f {path}/.byte-fill {path}/.byte-over; touch {path}/.byte-recovered; rm {path}/.byte-recovered"
        result=provision.run_capped(["docker","exec",cid,"sh","-c",script],timeout=180)
        if result["returncode"]: raise RuntimeError(f"byte exhaustion/recovery failed for profile {size}")
        exhaustion.append({"kind":"bytes","reviewed":size,"contained":True,"recovered":True})
    for count,(cid,path) in targets["inodes"].items():
        limit=count+max(16,(count+99)//100)
        script=f"set -eu; i=0; while touch {path}/.inode-$i 2>/dev/null; do i=$((i+1)); test $i -le {limit}; done; test $i -le {limit}; rm -f {path}/.inode-*; touch {path}/.inode-recovered; rm {path}/.inode-recovered"
        result=provision.run_capped(["docker","exec",cid,"sh","-c",script],timeout=180)
        if result["returncode"]: raise RuntimeError(f"inode exhaustion/recovery failed for profile {count}")
        exhaustion.append({"kind":"inodes","reviewed":count,"contained":True,"recovered":True})
    return exhaustion


def _prove_gateway_and_cpu(base,gateways):
    browser_cid=provision.run_capped(base+["ps","-q","browser"])["stdout"].strip()
    script="const t="+json.dumps(sorted(gateways))+";Promise.all(t.map(h=>fetch('http://'+h,{signal:AbortSignal.timeout(2000)}).then(()=>{throw Error('gateway escaped')},()=>true))).then(()=>process.exit(0),()=>process.exit(1))"
    result=provision.run_capped(["docker","exec",browser_cid,"node","-e",script],timeout=10)
    if result["returncode"]: raise RuntimeError("browser reached a network gateway")
    provision.run_capped(["docker","exec","-d",browser_cid,"node","-e","const end=Date.now()+5000;while(Date.now()<end){}"])
    __import__("time").sleep(1)
    cpu=float(provision.run_capped(["docker","stats","--no-stream","--format","{{.CPUPerc}}",browser_cid])["stdout"].strip().rstrip("%"))
    if cpu > 110.0: raise RuntimeError("browser CPU quota exceeded")


def _provenance_chain(inv,upstream,arch):
    chain={}
    for key in inv:
        repo=provision.run_capped(["docker","image","inspect",upstream[key],"--format","{{json .RepoDigests}}"])["stdout"].strip()
        chain[key]={"index":inv[key]["index"],"platform_child":provision.platform_digest(inv[key],arch),"pulled_repo_digests":json.loads(repo)}
    return chain


def _execute_canary(base,inventory,inv,arch,upstream,built,identities,tags,playwright):
    result=provision.run_capped(base+["config","--images"],timeout=300)
    if result["returncode"]: raise RuntimeError(result["stderr"])
    if set(result["stdout"].splitlines()) != {built["wordpress"],built["database"],playwright}: raise RuntimeError("final Compose image inventory mismatch")
    result=provision.run_capped(base+["up","-d","--wait"],timeout=300)
    if result["returncode"]: raise compose_start_failure(result,base)
    for probe in runtime_probe_specs(base): run_named_probe(probe)
    live,gateways,profiles,targets=_inspect_canary_services(base,built,identities,*tags,playwright)
    exhaustion=_prove_quota_exhaustion(targets); _prove_gateway_and_cpu(base,gateways)
    return {"status":"pass","platform":arch,"core_sha256":inventory["wordpress_core"]["sha256"],
            "built_image_ids":built,"live_image_ids":live,
            "provenance":_provenance_chain(inv,upstream,arch),
            "observed_tmpfs_profiles":profiles,"quota_exhaustion":exhaustion}


def _cleanup_canary(base,tags):
    active_error=__import__("sys").exc_info()[0] is not None
    cleanup_error=None
    if base is not None:
        try: provision.run_capped(base+["down","-v","--remove-orphans"],timeout=120)
        except Exception as exc: cleanup_error=exc
    try: provision.run_capped(["docker","image","rm","-f",*tags],timeout=120)
    except Exception as exc: cleanup_error=cleanup_error or exc
    if cleanup_error is not None and not active_error: raise cleanup_error


def _run_linux_canary(work):
    inventory=provision.inventory(); inv=inventory["images"]; arch=platform.machine()
    run_id=__import__("hashlib").sha256(str(work).encode()).hexdigest()[:12]
    tags=(f"wp-sandbox-wordpress:{run_id}",f"wp-sandbox-database:{run_id}")
    base=None
    try:
        upstream=_review_upstream_images(inv,arch); prove_fixture_locks(work,inv,arch)
        built=_build_canary_images(work,inventory,inv,arch,*tags)
        compose,identities,playwright=_prepare_canary_compose(work,built,inv,arch)
        base=["docker","compose","-p",f"wpstep0{run_id}","-f",str(compose)]
        return _execute_canary(base,inventory,inv,arch,upstream,built,identities,tags,playwright)
    finally:
        _cleanup_canary(base,tags)
