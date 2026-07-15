"""WordPress-native, route-denial, resource, and browser runtime oracles."""
from __future__ import annotations

import ipaddress
import hashlib
import json
import re
import time
import unicodedata

import isolated_runtime_contract as contract
import runtime_image_provision as transport
import wp_runtime_inspection as inspection
import wp_runtime_network as runtime_network
import wp_runtime_topology as topology
from wp_runtime_evidence import RuntimeDeadline, docker_absence_proved, scrub_tail
from wp_runtime_types import BlockRuntimeAssertion

OUTPUT_LIMIT = 65536
BROWSER_ORIGIN = "http://gateway-frontend:8081"
REST_OUTPUT_URL = (
    f"{BROWSER_ORIGIN}/?rest_route=%2Fwp-runtime-canary%2Fv1%2Foutput"
)
MUTABLE_PATHS = tuple(
    (service, path)
    for service in topology.WRITABLE_PATHS
    for path in sorted(topology.WRITABLE_PATHS[service])
)


class OracleFailure(RuntimeError):
    def __init__(self, step, cause, checks):
        super().__init__(f"{step}: {cause}")
        self.step = step
        self.checks = tuple(checks)


def _run(command, deadline, cap):
    result = transport.run_capped(
        command, timeout=deadline.remaining(cap), limit=OUTPUT_LIMIT,
    )
    if result["returncode"]:
        detail = scrub_tail((result.get("stderr") or "") + (result.get("stdout") or ""))
        raise RuntimeError(f"isolated runtime oracle failed rc={result['returncode']}: {detail}")
    return result


def _raw(command, deadline, cap, limit=OUTPUT_LIMIT):
    return transport.run_capped(command, timeout=deadline.remaining(cap), limit=limit)


def _cleanup_raw(command, deadline, cap, limit=OUTPUT_LIMIT):
    return transport.run_capped(
        command, timeout=deadline.remaining(cap, cleanup=True), limit=limit,
    )


def _expect_exit_code(command, deadline, cap, check_id, expected):
    result = _raw(command, deadline, cap)
    if result["returncode"] != expected:
        raise RuntimeError(
            f"{check_id} expected causal exit {expected}, got {result['returncode']}"
        )
    return {"id": check_id, "status": "pass", "required": True,
            "returncode": result["returncode"]}


def _expect_output_ceiling(command, deadline, check_id, stream):
    expected = f"{stream} output limit exceeded"
    opposite = "stderr" if stream == "stdout" else "stdout"
    try:
        result = _raw(command, deadline, 15, 4096)
    except RuntimeError as exc:
        detail = str(exc)
        if expected in detail and f"{opposite} output limit exceeded" not in detail and "cleanup" not in detail:
            return {"id": check_id, "status": "pass", "required": True, "stream": stream}
        raise
    detail = scrub_tail(
        (result.get("stderr") or "") + (result.get("stdout") or ""), 500,
    )
    raise RuntimeError(
        f"{check_id} did not reach the {stream} host capture ceiling; "
        f"rc={result['returncode']}: {detail}"
    )


def _start_named_canary(base, service, name, deadline):
    _run(
        base + ["run", "--detach", "--name", name, "--no-deps",
                "--entrypoint", "sleep", service, "infinity"],
        deadline, 30,
    )
    return inspection.inspect_named_canary(base, service, name, deadline)


def _named_output_ceiling(base, service, payload, deadline, check_id, stream, name):
    try:
        profile = _start_named_canary(base, service, name, deadline)
        check = _expect_output_ceiling(
            ["docker", "exec", name, *payload], deadline, check_id, stream,
        )
        check.update({"canary": name, "sandbox_profile": profile,
                      "termination": "forced removal and absence proved"})
        return check
    finally:
        _remove_named_canary(name, deadline)


def _activation(base, slug, deadline):
    shell = (
        "set -eu; i=0; until php -r 'mysqli_report(MYSQLI_REPORT_OFF);"
        "$m=@new mysqli(\"database\",\"wordpress\",\"wordpress-canary\",\"wordpress\",3306);"
        "exit($m->connect_errno?1:0);'; do i=$((i+1)); test $i -lt 60; sleep 1; done; "
        f"wp core install --path=/var/www/html --url={BROWSER_ORIGIN} --title=Sandbox "
        "--admin_user=sandbox --admin_password=not-a-secret-canary "
        "--admin_email=sandbox@example.invalid --skip-email; "
        f"wp plugin activate --path=/var/www/html {slug}; "
        "wp core is-installed --path=/var/www/html; "
        f"test \"$(wp option get siteurl --path=/var/www/html)\" = {BROWSER_ORIGIN}; "
        f"wp plugin is-active --path=/var/www/html {slug}"
    )
    _run(base + ["exec", "-T", "cli", "sh", "-c", shell], deadline, 90)
    return {"id": "wp_cli_activation", "status": "pass", "required": True}


def _plugin_check(base, slug, deadline):
    command = (
        "set -eu; wp plugin activate plugin-check --path=/var/www/html; "
        f"wp plugin check {slug} --path=/var/www/html --format=json "
        "--require=./wp-content/plugins/plugin-check/cli.php"
    )
    _run(base + ["exec", "-T", "cli", "sh", "-c", command], deadline, 120)
    return {"id": "plugin_check", "status": "pass", "required": True,
            "version": "2.0.0"}


def _block_registration(base, assertion, deadline):
    encoded=json.dumps(assertion.block_name)
    code=(f"$n={encoded};$b=WP_Block_Type_Registry::get_instance()->get_registered($n);"
          "if(!$b||$b->name!==$n)exit(41);echo $b->name;")
    result=_run(base+["exec","-T","cli","wp","eval",code,
                      "--path=/var/www/html"],deadline,30)
    if result["stdout"].strip()!=assertion.block_name:
        raise RuntimeError("registered block name mismatch")
    return {"id":"block_registration","status":"pass","required":True,
            "block_name":assertion.block_name}


def _create_disposable_block_post(base, deadline):
    result=_run(base+["exec","-T","cli","wp","post","create",
        "--path=/var/www/html","--post_type=post","--post_status=draft",
        "--post_title=Runtime Block Smoke","--porcelain"],deadline,30)
    value=result["stdout"].strip()
    if re.fullmatch(r"[1-9][0-9]{0,9}",value) is None:
        raise RuntimeError("disposable block post ID is malformed")
    return int(value)


def _container_manifest(base, slug, expected, deadline):
    root = f"/var/www/html/wp-content/plugins/{slug}"
    code = (
        "$r=$argv[1];$a=[];$i=new RecursiveIteratorIterator("
        "new RecursiveDirectoryIterator($r,FilesystemIterator::SKIP_DOTS));"
        "foreach($i as $f){if(!$f->isFile()||$f->isLink())exit(41);"
        "$p=str_replace('\\\\','/',substr($f->getPathname(),strlen($r)+1));"
        "$a[]=json_encode(['path'=>$p,'sha256'=>hash_file('sha256',$f->getPathname()),"
        "'size'=>$f->getSize()],JSON_UNESCAPED_SLASHES);}sort($a,SORT_STRING);"
        "echo hash('sha256',implode(\"\\n\",$a).(count($a)?\"\\n\":\"\"));"
    )
    result = _run(base + ["exec", "-T", "cli", "php", "-r", code, "--", root], deadline, 30)
    if result["stdout"].strip() != expected:
        raise RuntimeError("in-container runtime artifact manifest mismatch")
    return {"id": "container_artifact_manifest", "status": "pass", "required": True,
            "digest": expected}


def _php_denials(base, deadline):
    code = "echo wp_runtime_adversarial_route_canary();"
    result = _run(
        base + ["exec", "-T", "wordpress", "timeout", "12", "wp", "eval", code,
                "--path=/var/www/html"], deadline, 15,
    )
    if result["stdout"].strip() != "generated-route-canary":
        raise RuntimeError("generated PHP reached a forbidden route")
    return {"id": "php_route_denials", "status": "pass", "required": True,
            "canaries": ["loopback", "rfc1918", "metadata", "public_ip", "public_dns"]}


def _browser_network_denials(base, deadline):
    script = (
        "const t=['http://127.0.0.1','http://10.0.0.1','http://169.254.169.254',"
        "'http://93.184.216.34'];Promise.all(t.map(u=>fetch(u,{signal:AbortSignal.timeout(1500)})"
        ".then(()=>{throw Error('escape')},()=>true))).then(()=>new Promise((ok,bad)=>{"
        "const s=require('net').connect(3306,'database',()=>bad(Error('database peer reachable')));"
        "s.on('error',ok);setTimeout(()=>{s.destroy();ok()},1500)})).then(()=>"
        "require('dns').promises.resolve4('example.com').then(()=>process.exit(42),"
        "()=>process.exit(0)),()=>process.exit(41))"
    )
    _run(base + ["exec", "-T", "browser", "node", "-e", script], deadline, 12)
    return {"id": "browser_network_denials", "status": "pass", "required": True,
            "canaries": ["loopback", "rfc1918", "metadata", "public_ip",
                         "public_dns", "database_peer"]}


def _isolated_networks(base, service, deadline):
    container = _run(
        base + ["ps", "-q", "--all", service], deadline, 10,
    )["stdout"].strip()
    if not container:
        raise RuntimeError(f"{service} container is missing for gateway canary")
    result = _run(
        ["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", container],
        deadline, 15,
    )
    try:
        networks = json.loads(result["stdout"])
        if not networks or any(item.get("Gateway") or item.get("IPv6Gateway")
                               for item in networks.values()):
            raise ValueError("container endpoint exposes a gateway")
        for name in networks:
            payload=_run(
                ["docker","network","inspect","--format","{{json .}}",name],
                deadline,15,
            )
            network=json.loads(payload["stdout"])
            configs=network.get("IPAM",{}).get("Config") or []
            options=network.get("Options") or {}
            subnet=ipaddress.ip_network(configs[0]["Subnet"]) if len(configs)==1 else None
            if (network.get("Driver")!="bridge" or network.get("Internal") is not True
                    or network.get("EnableIPv6") is not False
                    or options!=topology.ISOLATED_BRIDGE_OPTIONS or len(configs)!=1
                    or set(configs[0])!={"Subnet"}
                    or not isinstance(subnet,ipaddress.IPv4Network) or not subnet.is_private):
                raise ValueError("network is not an isolated bridge")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{service} live isolated-network evidence is malformed") from exc
    return tuple(sorted(networks))


def _default_route_absence(base,service,deadline):
    result=_run(base+["exec","-T",service,"cat","/proc/net/route"],deadline,10)
    lines=[line.split() for line in result["stdout"].splitlines() if line.strip()]
    rows=lines[1:]
    if (not lines or lines[0][:3] != ["Iface","Destination","Gateway"] or not rows
            or any(len(row)<3 or not re.fullmatch(r"[0-9A-Fa-f]{8}",row[1])
                   or not re.fullmatch(r"[0-9A-Fa-f]{8}",row[2]) for row in rows)
            or any(row[1]=="00000000" for row in rows)):
        raise RuntimeError(f"{service} live default route is present or malformed")
    return len(rows)


def _network_address(base, service, network_suffix, deadline):
    container = _run(
        base + ["ps", "-q", "--all", service], deadline, 10,
    )["stdout"].strip()
    result = _run(
        ["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", container],
        deadline, 15,
    )
    networks = json.loads(result["stdout"])
    matches = [
        item.get("IPAddress") for name, item in networks.items()
        if name.endswith(f"_{network_suffix}") and item.get("IPAddress")
    ]
    if len(matches) != 1:
        raise RuntimeError(f"{service} {network_suffix} address evidence is malformed")
    return matches[0]


def _php_gateway_probe(base, gateways, port, deadline, generated):
    encoded = json.dumps(list(gateways), separators=(",", ":"))
    if generated:
        code = (
            f"$r=wp_runtime_adversarial_php_canary(json_decode('{encoded}',true),{port});"
            "if($r!=='generated-php-canary')exit(41);echo $r;"
        )
        command = base + ["exec", "-T", "wordpress", "wp", "eval", code,
                          "--path=/var/www/html"]
    else:
        code = (
            f"$t=json_decode('{encoded}',true);foreach($t as $h){{"
            f"$s=@fsockopen($h,{port},$e,$m,1);if($s){{fclose($s);exit(41);}}}}"
        )
        command = base + ["exec", "-T", "wordpress", "php", "-r", code]
    return _run(command, deadline, 20)


def _browser_host_probe(base,target,port,deadline):
    script=(
        f"const net=require('net'),s=net.connect({port},{json.dumps(target)},()=>process.exit(41));"
        "s.once('error',()=>process.exit(0));setTimeout(()=>{s.destroy();process.exit(0)},1500)"
    )
    return _run(base+["exec","-T","browser","node","-e",script],deadline,20)


def _gateway_denials(base, deadline, generated):
    isolated={service:_isolated_networks(base,service,deadline)
              for service in ("wordpress","cli","browser")}
    gateway_application = _network_address(base, "gateway", "application", deadline)
    try:
        peer_result = _php_gateway_probe(
            base, (gateway_application,), 8081, deadline, generated,
        )
    except RuntimeError as exc:
        raise RuntimeError(f"generated_php_gateway_peer_denial: {exc}") from exc
    route_rows={service:_default_route_absence(base,service,deadline) for service in isolated}
    with runtime_network.controlled_host_listener() as (server,target,port):
        try: host_result=_php_gateway_probe(base,(target,),port,deadline,generated)
        except RuntimeError as exc:
            raise RuntimeError(f"generated_php_host_listener_denial: {exc}") from exc
        try: _browser_host_probe(base,target,port,deadline)
        except RuntimeError as exc:
            raise RuntimeError(f"browser_host_listener_denial: {exc}") from exc
        runtime_network.assert_listener_unreached(server)
    checks = [{"id": "runtime_gateway_denials", "status": "pass", "required": True,
               "isolated_networks": {key:list(value) for key,value in isolated.items()},
               "gateway_application_peer": gateway_application,
               "host_bridge_gateways": [],"default_routes":False,"route_rows":route_rows,
               "controlled_host_listener":True,"listener_target_class":"host_primary_ipv4"}]
    if generated:
        if (peer_result["stdout"].strip()!="generated-php-canary"
                or host_result["stdout"].strip()!="generated-php-canary"):
            raise RuntimeError("generated PHP canary evidence mismatch")
        checks.append({"id": "generated_php_canary", "status": "pass", "required": True})
    return tuple(checks)


def _browser_policy_command(profile, slug, target, assertion, post_id):
    command = ["node", "/opt/wp-runtime/browser-policy.js", profile,
               BROWSER_ORIGIN, slug, target]
    if assertion is not None:
        command.extend([
            assertion.block_name, assertion.frontend_selector,
            assertion.expected_frontend_text, str(post_id),
        ])
    return command


def _browser_policy_evidence(
    base, deadline, profile, slug, assertion=None, post_id=None,
):
    target=""
    if profile==contract.ADVERSARIAL_PROFILE:
        with runtime_network.controlled_host_listener() as (server,address,port):
            target=f"http://{address}:{port}"
            result=_run(base+["exec","-T","browser",*_browser_policy_command(
                profile,slug,target,assertion,post_id,
            )],deadline,60)
            runtime_network.assert_listener_unreached(server)
    else:
        result=_run(base+["exec","-T","browser",*_browser_policy_command(
            profile,slug,target,assertion,post_id,
        )],deadline,60)
    try:
        evidence = json.loads(result["stdout"].splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise RuntimeError("browser policy evidence is malformed") from exc
    common = {"same_origin", "external_http", "external_navigation", "websocket",
              "webrtc", "service_worker", "download", "popup"}
    generated = {"generated_frontend_js", "generated_editor_js"}
    required = common | (generated if profile == contract.ADVERSARIAL_PROFILE else set())
    if evidence.get("profile") != profile:
        raise RuntimeError("browser policy profile mismatch")
    observed = evidence.get("canaries", {})
    if not isinstance(observed, dict) or set(observed) != required:
        raise RuntimeError("browser policy named canary inventory mismatch")
    failed = sorted(name for name in required if observed.get(name) is not True)
    if failed:
        raise RuntimeError(f"browser policy failed named canaries: {','.join(failed)}")
    return evidence, common, generated


def _generated_browser_check(evidence, generated):
    denial_keys = {
        "loopback", "rfc1918", "metadata", "public_ip", "public_dns",
        "database_peer", "host_gateway", "host_listener", "websocket", "webrtc",
        "service_worker", "external_navigation", "download", "popup",
    }
    generated_denials = evidence.get("generated_denials")
    navigation = evidence.get("generated_navigation_denials")
    expected_navigation = [
        "/generated-navigation-editor", "/generated-navigation-frontend",
    ]
    if not isinstance(generated_denials, dict):
        raise RuntimeError("generated browser JavaScript denial evidence is malformed")
    invalid_contexts = sorted(
        context for context, item in generated_denials.items()
        if not isinstance(item, dict)
        or set(item) != denial_keys
        or not all(value is True for value in item.values())
    )
    navigation_values = navigation if isinstance(navigation, list) else []
    missing = sorted(set(expected_navigation) - set(navigation_values))
    if (set(generated_denials) != {"frontend", "editor"} or invalid_contexts
            or navigation != expected_navigation):
        detail = ",".join(
            [*(f"invalid:{item}" for item in invalid_contexts),
             *(f"missing:{item.rsplit('-', 1)[-1]}" for item in missing),
             f"navigation_count:{len(navigation_values)}"],
        )
        raise RuntimeError(
            f"generated browser JavaScript denial evidence is incomplete ({detail})"
        )
    return {"id": "generated_browser_editor_js", "status": "pass", "required": True,
            "canaries": {name: evidence["canaries"][name] for name in sorted(generated)},
            "generated_denials": generated_denials}


def _normalized_block_text(value):
    normalized=unicodedata.normalize("NFC",value)
    return re.sub(r"\s+"," ",normalized).strip()


def _block_frontend_check(evidence, assertion):
    proof=evidence.get("block_editor_frontend")
    keys={"status","block_name","frontend_selector","expected_text_sha256",
          "observed_text_sha256","match_count","visible","normalization"}
    expected_hash=hashlib.sha256(
        _normalized_block_text(assertion.expected_frontend_text).encode("utf-8")
    ).hexdigest()
    valid=(isinstance(proof,dict) and set(proof)==keys
           and proof.get("status")=="pass"
           and proof.get("block_name")==assertion.block_name
           and proof.get("frontend_selector")==assertion.frontend_selector
           and proof.get("expected_text_sha256")==expected_hash
           and proof.get("observed_text_sha256")==expected_hash
           and proof.get("match_count")==1 and proof.get("visible") is True
           and proof.get("normalization")=="unicode-nfc-whitespace-collapse-trim")
    if not valid: raise RuntimeError("block editor/frontend proof is malformed or mismatched")
    return {"id":"block_editor_frontend","status":"pass","required":True,
            "proof":proof}


def _browser_policy(base, deadline, profile, slug, assertion=None, post_id=None):
    evidence, common, generated = _browser_policy_evidence(
        base, deadline, profile, slug, assertion, post_id,
    )
    checks = [{"id": "container_browser", "status": "pass", "required": True,
               "canaries": {name: evidence["canaries"][name] for name in sorted(common)}}]
    if profile == contract.ADVERSARIAL_PROFILE:
        checks.append(_generated_browser_check(evidence, generated))
    if profile == contract.BLOCK_PROFILE:
        if not isinstance(assertion,BlockRuntimeAssertion):
            raise RuntimeError("block browser policy lacks an immutable assertion")
        checks.append(_block_frontend_check(evidence,assertion))
    return tuple(checks)


def _generated_js_script(slug, body):
    url = f"{BROWSER_ORIGIN}/wp-content/plugins/{slug}/wp-runtime-adversarial.js"
    return (
        "(async()=>{const response=await fetch(" + json.dumps(url) + ");"
        "if(!response.ok)throw Error('generated JavaScript unavailable');"
        "(0,eval)(await response.text());" + body + "})()"
        ".then(()=>process.exit(0),error=>{console.error(String(error).slice(0,500));process.exit(41)})"
    )


def _generated_js_command(base, slug, body):
    return base + [
        "exec", "-T", "browser", "node", "-e", _generated_js_script(slug, body),
    ]


def _tmpfs_script(kind):
    if kind == "bytes":
        return (
            "set -eu; r=$1; d=$r/.wp-runtime-byte-canary; rm -rf $d; mkdir $d; "
            "a=$(df -Pk $r|awk 'NR==2{print $4}'); n=$((a>64?a-64:1)); "
            "dd if=/dev/zero of=$d/fill bs=1024 count=$n 2>/dev/null; set +e; "
            "dd if=/dev/zero of=$d/over bs=1024 count=1024 2>/dev/null; x=$?; set -e; "
            "test $x -ne 0; rm -rf $d; mkdir $d; echo recovered > $d/probe; "
            "test -s $d/probe; rm -rf $d"
        )
    return (
        "set -eu; r=$1; d=$r/.wp-runtime-inode-canary; rm -rf $d; mkdir $d; "
        "i=0; failed=0; while [ $i -lt 20000 ]; do touch $d/$i 2>/dev/null || "
        "{ failed=1; break; }; i=$((i+1)); done; test $failed -eq 1; "
        "rm -rf $d; mkdir $d; touch $d/recovered; test -f $d/recovered; rm -rf $d"
    )


def _mount_profile(base, service, path, deadline):
    script = (
        "set -eu; p=$1; awk -v p=$p '$2==p {print $3 \"|\" $4; found=1} "
        "END{if(!found)exit 41}' /proc/mounts; "
        "df -Pk $p | awk 'NR==2{print $2}'; df -Pi $p | awk 'NR==2{print $2}'; "
        "stat -c '%u:%g:%a' $p; id -u; id -g"
    )
    lines = _run(
        base + ["exec", "-T", service, "sh", "-c", script, "--", path],
        deadline, 20,
    )["stdout"].splitlines()
    if len(lines) != 6 or not lines[0].startswith("tmpfs|"):
        raise RuntimeError(f"{service}:{path} live mount profile is malformed")
    options = set(lines[0].split("|", 1)[1].split(","))
    if not {"rw", "nosuid", "nodev", "noexec"} <= options:
        raise RuntimeError(f"{service}:{path} live mount flags drift")
    size, inodes = topology.WRITABLE_LIMITS[service][path]
    try:
        blocks, observed_inodes = int(lines[1]), int(lines[2])
    except ValueError as exc:
        raise RuntimeError(f"{service}:{path} live mount capacity is malformed") from exc
    inode_limit = inodes + max(16, (inodes + 99) // 100)
    if blocks > (size + 1023) // 1024 + 1 or observed_inodes > inode_limit:
        raise RuntimeError(f"{service}:{path} live mount capacity exceeds policy")
    identity = lines[3]
    if identity != f"{lines[4]}:{lines[5]}:700":
        raise RuntimeError(f"{service}:{path} live mount ownership mode drift")
    return {"path": f"{service}:{path}", "blocks_1k": blocks,
            "inodes": observed_inodes, "identity_mode": identity}


def _service_recovery(base, service, deadline):
    commands = {
        "database": ["sh", "-c", "mariadb-admin --socket=/run/mysqld/mysqld.sock ping >/dev/null"],
        "wordpress": ["php", "-r", "echo 'recovered';"],
        "cli": ["wp", "core", "is-installed", "--path=/var/www/html"],
        "browser": ["node", "-e", "process.stdout.write('recovered')"],
        "gateway": ["node", "-e", "process.stdout.write('recovered')"],
    }
    _run(base + ["exec", "-T", service, *commands[service]], deadline, 20)


def _tmpfs_probe(base, deadline, kind, slug):
    evidence = []; generated = []; exhausted = []; profiles = []
    profile_only = {("database", "/var/lib/mysql"), ("database", "/run/mysqld")}
    for service, path in MUTABLE_PATHS:
        if kind == "bytes":
            profiles.append(_mount_profile(base, service, path, deadline))
        evidence.append(f"{service}:{path}")
        if (service, path) in profile_only:
            continue
        if service in {"wordpress", "cli"}:
            code = (
                f"exit(wp_runtime_adversarial_storage({json.dumps(path)},"
                f"{json.dumps(kind)})?0:41);"
            )
            command = base + ["exec", "-T", service, "wp", "eval", code,
                              "--path=/var/www/html"]
            generated.append(f"{service}:{path}")
        elif service == "browser":
            body = (
                f"if(!globalThis.wpRuntimeAdversarialStorage({json.dumps(path)},"
                f"{json.dumps(kind)}))throw Error('storage ceiling absent');"
            )
            command = _generated_js_command(base, slug, body)
            generated.append(f"{service}:{path}")
        else:
            command = base + [
                "exec", "-T", service, "sh", "-c", _tmpfs_script(kind), "--", path,
            ]
        _run(command, deadline, 120)
        _service_recovery(base, service, deadline)
        exhausted.append(f"{service}:{path}")
    check_id = "runtime_storage_ceiling" if kind == "bytes" else "runtime_inode_ceiling"
    return {"id": check_id, "status": "pass", "required": True,
            "paths": evidence, "generated_paths": generated,
            "exhausted_paths": exhausted, "mount_profiles": profiles,
            "profile_only_paths": [f"{service}:{path}" for service,path in sorted(profile_only)],
            "recovery": "verified"}


def _fd_probe(base, deadline, slug):
    php = "exit(wp_runtime_adversarial_fd()?0:41);"
    _run(base + ["exec", "-T", "wordpress", "wp", "eval", php,
                 "--path=/var/www/html"], deadline, 20)
    _run(_generated_js_command(
        base, slug, "if(!globalThis.wpRuntimeAdversarialFd())throw Error('fd ceiling absent');",
    ), deadline, 20)
    _service_recovery(base, "wordpress", deadline)
    _service_recovery(base, "browser", deadline)
    return {"id": "runtime_fd_ceiling", "status": "pass", "required": True,
            "canaries": ["generated_php", "generated_browser_javascript"]}


def _process_probe(base, deadline, slug):
    before_php = _cgroup_counter(base, "wordpress", "pids.events", "max", deadline)
    php = "exit(wp_runtime_adversarial_process()?0:41);"
    _run(base + ["exec", "-T", "wordpress", "wp", "eval", php,
                 "--path=/var/www/html"], deadline, 30)
    after_php = _cgroup_counter(base, "wordpress", "pids.events", "max", deadline)
    if after_php <= before_php:
        raise RuntimeError("PHP fork canary did not increment pids.events max")
    before_browser = _cgroup_counter(base, "browser", "pids.events", "max", deadline)
    _run(_generated_js_command(
        base, slug,
        "if(!await globalThis.wpRuntimeAdversarialProcess())throw Error('PID ceiling absent');",
    ), deadline, 15)
    after_browser = _cgroup_counter(base, "browser", "pids.events", "max", deadline)
    if after_browser <= before_browser:
        raise RuntimeError("browser fork canary did not increment pids.events max")
    _service_recovery(base, "wordpress", deadline)
    _service_recovery(base, "browser", deadline)
    return {"id": "runtime_pid_fork_ceiling", "status": "pass", "required": True,
            "canaries": ["generated_php_proc_open", "generated_browser_spawn"],
            "cgroup": "pids.events max incremented"}


def _cgroup_counter(base, service, filename, key, deadline):
    output = _run(
        base + ["exec", "-T", service, "cat", f"/sys/fs/cgroup/{filename}"],
        deadline, 10,
    )["stdout"]
    values = dict(line.split(None, 1) for line in output.splitlines() if line.strip())
    try:
        return int(values[key])
    except (KeyError, ValueError) as exc:
        raise RuntimeError(f"{service} cgroup {filename} evidence is malformed") from exc


def _hang_probe(base, deadline, slug):
    exits = {}
    for service, command in (
        ("wordpress", ["wp", "eval", "wp_runtime_adversarial_cpu();",
                       "--path=/var/www/html"]),
        ("browser", ["node", "-e", _generated_js_script(
            slug, "globalThis.wpRuntimeAdversarialCpu();",
        )]),
    ):
        quota = _run(base + ["exec", "-T", service, "cat", "/sys/fs/cgroup/cpu.max"],
                     deadline, 10)["stdout"].strip()
        if quota != "50000 100000":
            raise RuntimeError(f"{service} live CPU quota canary drift: {quota!r}")
        before = _cgroup_counter(base, service, "cpu.stat", "nr_throttled", deadline)
        probe = _expect_exit_code(
            base + ["exec", "-T", service, "timeout", "--signal=TERM", "--kill-after=1",
                    "2", *command], deadline, 8, f"{service}_cpu_timeout", 124,
        )
        after = _cgroup_counter(base, service, "cpu.stat", "nr_throttled", deadline)
        if after <= before:
            raise RuntimeError(f"{service} CPU canary did not increment nr_throttled")
        _service_recovery(base, service, deadline)
        exits[service] = probe["returncode"]
    return {"id": "runtime_cpu_hang_ceiling", "status": "pass", "required": True,
            "cpu_max": "50000 100000", "timeout_exit_codes": exits,
            "throttling": "nr_throttled incremented"}


def _project_name(base):
    try:
        return base[base.index("-p") + 1]
    except (ValueError, IndexError) as exc:
        raise RuntimeError("Compose project identity is missing") from exc


def _remove_named_canary(name, deadline):
    _cleanup_raw(["docker", "rm", "-f", name], deadline, 30)
    probe = _cleanup_raw(
        ["docker", "inspect", "--format", "{{.Id}}", name], deadline, 10,
    )
    if probe["returncode"] == 0:
        raise RuntimeError(f"named canary {name} survived forced removal")
    if not docker_absence_proved(probe, "container"):
        raise RuntimeError(f"named canary {name} absence could not be proved")


def _oom_evidence(name, deadline):
    template = "{{.State.OOMKilled}} {{.State.ExitCode}} {{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}"
    output = _run(
        ["docker", "inspect", "--format", template, name], deadline, 15,
    )["stdout"].strip()
    if output != "true 137 536870912 536870912":
        raise RuntimeError(f"named canary {name} did not prove the exact OOM ceiling")
    return output


def _memory_probe(base, deadline, kind, slug):
    name = f"{_project_name(base)}-{kind}-oom"
    if kind == "php":
        service = "cli"
        payload = ["wp",
            "eval", "wp_runtime_adversarial_memory();", "--path=/var/www/html",
        ]
    else:
        service = "browser"
        payload = ["node",
            "--max-old-space-size=1024", "-e", _generated_js_script(
                slug, "globalThis.wpRuntimeAdversarialMemory();",
            ),
        ]
    try:
        script = "while [ ! -f /tmp/wp-runtime-go ]; do sleep 0.05; done; exec \"$@\""
        _run(
            base + ["run", "--detach", "--name", name, "--no-deps",
                    "--entrypoint", "sh", service, "-c", script, "--", *payload],
            deadline, 30,
        )
        profile = inspection.inspect_named_canary(base, service, name, deadline)
        _run(["docker", "exec", name, "touch", "/tmp/wp-runtime-go"], deadline, 10)
        waited = _run(["docker", "wait", name], deadline, 60)["stdout"].strip()
        if waited != "137":
            raise RuntimeError(f"runtime_{kind}_memory_ceiling expected causal exit 137, got {waited!r}")
        return {"id": f"runtime_{kind}_memory_ceiling", "status": "pass",
                "required": True, "returncode": 137,
                "oom_evidence": _oom_evidence(name, deadline), "canary": name,
                "sandbox_profile": profile}
    finally:
        _remove_named_canary(name, deadline)


def _php_output_probes(base, deadline):
    project = _project_name(base)
    stdout_name = f"{project}-php-stdout"
    stderr_name = f"{project}-php-stderr"
    stdout = _named_output_ceiling(
        base, "cli", ["wp", "eval", "wp_runtime_adversarial_output('stdout');",
                        "--path=/var/www/html"],
        deadline, "runtime_php_stdout_ceiling", "stdout", stdout_name,
    )
    stderr = _named_output_ceiling(
        base, "cli", ["wp", "eval", "wp_runtime_adversarial_output('stderr');",
                        "--path=/var/www/html"],
        deadline, "runtime_php_log_ceiling", "stderr", stderr_name,
    )
    return stdout, stderr


def _browser_output_probe(base, deadline, slug):
    name = f"{_project_name(base)}-browser-console"
    return _named_output_ceiling(
        base, "browser", ["node", "-e", _generated_js_script(
                    slug, "globalThis.wpRuntimeAdversarialConsole();",
                )],
        deadline, "runtime_browser_console_ceiling", "stderr", name,
    )


def _http_response_probe(base, deadline):
    name = f"{_project_name(base)}-http-response"
    script = (
        f"fetch('{REST_OUTPUT_URL}')"
        ".then(async response=>{if(!response.ok)throw Error('HTTP canary failed');"
        "process.stdout.write(await response.text())})"
        ".catch(error=>{console.error(String(error));process.exit(41)})"
    )
    return _named_output_ceiling(
        base, "browser", ["node", "-e", script],
        deadline, "runtime_http_response_ceiling", "stdout", name,
    )


def _database_probe(base, deadline):
    code = "echo wp_json_encode(wp_runtime_adversarial_database());"
    result = _run(
        base + ["exec", "-T", "wordpress", "wp", "eval", code,
                "--path=/var/www/html"], deadline, 90,
    )
    try:
        evidence = json.loads(result["stdout"].splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        detail = scrub_tail(
            (result.get("stdout") or "") + (result.get("stderr") or ""), 500,
        )
        raise RuntimeError(f"database ceiling evidence is malformed: {detail}") from exc
    error = str(evidence.get("error", ""))
    quota_inserts = int(evidence.get("quota_inserts", -1))
    if (evidence.get("created") is not True or int(evidence.get("inserted", 0)) != 4
            or quota_inserts not in set(range(16))
            or evidence.get("failed") is not True
            or evidence.get("recovered") is not True
            or not re.search(r"(?:error\s*28|disk|full|space)", error, re.IGNORECASE)):
        raise RuntimeError("database ceiling was not caused by bounded storage exhaustion")
    return {"id": "runtime_database_ceiling", "status": "pass", "required": True,
            "inserted_rows": evidence["inserted"], "quota_inserts": quota_inserts,
            "error": scrub_tail(error, 300),
            "path": "database:/var/lib/mysql", "ordinary_table": True,
            "recovery": "drop-and-query"}


def _daemon_log_stress_script():
    return (
        f"(async()=>{{for(let i=0;i<256;i++){{const r=await fetch('{BROWSER_ORIGIN}/',"
        "{signal:AbortSignal.timeout(5000)});if(!r.ok)process.exit(41);}"
        "process.exit(0);})().catch(()=>process.exit(42));"
    )


def _log_policy_probe(base, deadline):
    evidence = {}
    for service in topology.SERVICE_NETWORKS:
        container = _run(
            base + ["ps", "-q", "--all", service], deadline, 10,
        )["stdout"].strip()
        policy = _run(
            ["docker", "inspect", "--format",
             "{{.HostConfig.LogConfig.Type}}|{{.LogPath}}", container],
            deadline, 10,
        )["stdout"].strip()
        if policy != "none|":
            raise RuntimeError(f"{service} daemon log policy is not an exact disabled sink")
        evidence[service] = policy
    script = _daemon_log_stress_script()
    _run(base + ["exec", "-T", "browser", "node", "-e", script], deadline, 30)
    return {"id": "runtime_daemon_log_ceiling", "status": "pass", "required": True,
            "driver": "none", "requests": 256, "services": sorted(evidence)}


def _standard_oracles(base, slug, deadline):
    steps=(
        ("wp_cli_activation",lambda:(_activation(base,slug,deadline),)),
        ("plugin_check",lambda:(_plugin_check(base,slug,deadline),)),
        ("container_browser",lambda:_browser_policy(
            base,deadline,contract.STANDARD_PROFILE,slug,
        )),
    )
    return _run_steps(steps)


def _block_oracles(base, slug, deadline, assertion):
    if not isinstance(assertion,BlockRuntimeAssertion):
        raise RuntimeError("block runtime profile requires an immutable assertion")
    first=_run_steps((
        ("wp_cli_activation",lambda:(_activation(base,slug,deadline),)),
        ("plugin_check",lambda:(_plugin_check(base,slug,deadline),)),
        ("block_registration",lambda:(_block_registration(base,assertion,deadline),)),
    ))
    post_id=_create_disposable_block_post(base,deadline)
    browser=_run_steps((("container_browser",lambda:_browser_policy(
        base,deadline,contract.BLOCK_PROFILE,slug,assertion,post_id,
    )),))
    return (*first,*browser)


def _run_steps(steps):
    checks=[]
    for name,step in steps:
        started = time.monotonic()
        try:
            produced = step()
            elapsed = round(time.monotonic() - started, 3)
            for check in produced:
                check.setdefault("duration_sec", elapsed)
            checks.extend(produced)
        except Exception as exc:
            raise OracleFailure(name, exc, checks) from exc
    return tuple(checks)


def _adversarial_oracles(base, slug, deadline, artifact_digest):
    steps=(
        ("container_artifact_manifest",lambda:(_container_manifest(base,slug,artifact_digest,deadline),)),
        ("wp_cli_activation",lambda:(_activation(base,slug,deadline),)),
        ("php_route_denials",lambda:(_php_denials(base,deadline),)),
        ("browser_network_denials",lambda:(_browser_network_denials(base,deadline),)),
        ("runtime_gateway_denials",lambda:_gateway_denials(base,deadline,True)),
        ("container_browser",lambda:_browser_policy(base,deadline,contract.ADVERSARIAL_PROFILE,slug)),
        ("runtime_database_ceiling",lambda:(_database_probe(base,deadline),)),
        ("runtime_storage_ceiling",lambda:(_tmpfs_probe(base,deadline,"bytes",slug),)),
        ("runtime_inode_ceiling",lambda:(_tmpfs_probe(base,deadline,"inodes",slug),)),
        ("runtime_fd_ceiling",lambda:(_fd_probe(base,deadline,slug),)),
        ("runtime_pid_fork_ceiling",lambda:(_process_probe(base,deadline,slug),)),
        ("runtime_cpu_hang_ceiling",lambda:(_hang_probe(base,deadline,slug),)),
        ("runtime_php_memory_ceiling",lambda:(_memory_probe(base,deadline,"php",slug),)),
        ("runtime_browser_memory_ceiling",lambda:(_memory_probe(base,deadline,"browser",slug),)),
        ("runtime_php_output_ceilings",lambda:_php_output_probes(base,deadline)),
        ("runtime_browser_console_ceiling",lambda:(_browser_output_probe(base,deadline,slug),)),
        ("runtime_http_response_ceiling",lambda:(_http_response_probe(base,deadline),)),
        ("runtime_daemon_log_ceiling",lambda:(_log_policy_probe(base,deadline),)),
    )
    return _run_steps(steps)


def run_oracles(
    base, slug, deadline, requested, artifact_digest, block_assertion=None,
):
    if not isinstance(deadline, RuntimeDeadline):
        deadline = RuntimeDeadline.start(deadline)
    try:
        profile = contract.profile_for_requested(tuple(requested))
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    if profile == contract.STANDARD_PROFILE:
        checks = _standard_oracles(base, slug, deadline)
    elif profile == contract.BLOCK_PROFILE:
        checks = _block_oracles(base,slug,deadline,block_assertion)
    else:
        checks = _adversarial_oracles(base, slug, deadline, artifact_digest)
    contract.require_exact_profile_checks(profile, checks)
    return checks
