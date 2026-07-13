import platform
from types import SimpleNamespace

import pytest

import artifact_staging
import runtime_image_provision
import sandbox_mount_policy as policy
import sandboxed_package_runner as runner
import workspace_lease


def staged(tmp_path):
    source=tmp_path/"source"; source.mkdir(); (source/"input.txt").write_text("safe")
    return artifact_staging.stage_tree(source,tmp_path/"leases")


def request(tree):
    item=runtime_image_provision.inventory()["images"]["node"]
    image=f"node@{runtime_image_provision.platform_digest(item,platform.machine())}"
    return runner.SandboxRequest(tree,image,("node","-e","process.exit(0)"))


def configured(source="/staged/source",target="/input"):
    return [{
        "Type":"bind","Source":source,"Target":target,"ReadOnly":True,
        "BindOptions":{"Propagation":"rprivate"},
    }]


def live(source="/staged/source",target="/input"):
    return [{
        "Type":"bind","Source":source,"Destination":target,"RW":False,
        "Propagation":"rprivate",
    }]


def test_bind_spec_and_artifact_command_are_exact(tmp_path):
    tree=staged(tmp_path)
    try:
        req=request(tree); command=runner._create_command(req,"package")
        index=command.index("--mount")
        assert command[index+1]==f"type=bind,src={tree.root},dst=/input,readonly,bind-propagation=rprivate"
        assert command.count("--mount")==1
    finally: workspace_lease.cleanup(tree.lease)


def test_proxy_command_has_exact_rprivate_bind(tmp_path):
    tree=staged(tmp_path)
    try:
        req=request(tree); ledger=runner.ResourceLedger(); ledger.bind("internal","b"*64)
        context=SimpleNamespace(
            proxy="proxy",internal="internal",proxy_ip="172.28.0.3",
            proxy_code=SimpleNamespace(source="/lease/proxy.py"),proxy_image="python@sha256:"+"a"*64,ledger=ledger,
        )
        command=runner._proxy_create_command(context,frozenset({"registry.test"}),req)
        assert command[command.index("--network")+1]=="b"*64
        index=command.index("--mount")
        assert command[index+1]=="type=bind,src=/lease/proxy.py,dst=/proxy.py,readonly,bind-propagation=rprivate"
        assert command.count("--mount")==1
    finally: workspace_lease.cleanup(tree.lease)


@pytest.mark.parametrize("live_gate",[False,True])
def test_exact_configured_and_live_mounts_pass(live_gate):
    mounts=live() if live_gate else configured()
    gate=policy.require_live if live_gate else policy.require_configured
    gate(mounts,"/staged/source","/input","bind")


@pytest.mark.parametrize("value",[None,"","shared","slave","private","rshared","rslave"])
@pytest.mark.parametrize("live_gate",[False,True])
def test_omitted_and_alternate_propagation_fail(value,live_gate):
    mounts=live() if live_gate else configured()
    container=mounts[0] if live_gate else mounts[0]["BindOptions"]
    if value is None: container.pop("Propagation")
    else: container["Propagation"]=value
    gate=policy.require_live if live_gate else policy.require_configured
    with pytest.raises(RuntimeError,match='"propagation":"(?:absent|other)"'):
        gate(mounts,"/staged/source","/input","bind")


@pytest.mark.parametrize("mutation",["source","target","readonly","count","type"])
@pytest.mark.parametrize("live_gate",[False,True])
def test_every_retained_bind_dimension_fails_with_sanitized_shape(mutation,live_gate):
    secret="/private/host/SENTINEL"; mounts=live(secret) if live_gate else configured(secret)
    mount=mounts[0]
    if mutation=="source": mount["Source"]="/other/SENSITIVE"
    elif mutation=="target": mount["Destination" if live_gate else "Target"]="/other/target"
    elif mutation=="readonly": mount["RW" if live_gate else "ReadOnly"]=True if live_gate else False
    elif mutation=="count": mounts.append(dict(mount))
    else: mount["Type"]="volume"
    gate=policy.require_live if live_gate else policy.require_configured
    with pytest.raises(RuntimeError) as caught:
        gate(mounts,secret,"/input","bind")
    message=str(caught.value)
    assert len(message)<=policy.DETAIL_LIMIT+32
    assert "SENTINEL" not in message and "SENSITIVE" not in message and "/other/target" not in message
    assert '"source_matches"' in message and '"target_matches"' in message
