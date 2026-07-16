import copy
import json
import sys
import time
from pathlib import Path

import pytest

HARNESS=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(HARNESS))
import sandbox_none_network as policy
import sandbox_python_preflight as preflight

DAEMON="daemon-instance-1234567890abcdef"
NETWORK="a"*64
CONTAINER="b"*64
ENDPOINT="c"*64
NAME="wp-package-1234567890abcdef"


def networks():
    return {"none":{"IPAMConfig":None,"Links":None,"Aliases":None,"MacAddress":"","NetworkID":NETWORK,"EndpointID":ENDPOINT,"Gateway":"","IPAddress":"","IPPrefixLen":0,"IPv6Gateway":"","GlobalIPv6Address":"","GlobalIPv6PrefixLen":0,"DriverOpts":None,"DNSNames":None,"GwPriority":0}}


def container():
    return {"Id":CONTAINER,"Name":f"/{NAME}","NetworkSettings":{"Networks":networks()}}


def network(containers=None):
    record={"Name":NAME,"EndpointID":ENDPOINT,"MacAddress":"","IPv4Address":"","IPv6Address":""}
    return {"Name":"none","Id":NETWORK,"Driver":"null","Scope":"local","Containers":containers if containers is not None else {CONTAINER:record}}


def result(stdout="",returncode=0,stderr=""):
    return {"returncode":returncode,"stdout":stdout,"stderr":stderr}


def daemon_payload(value=DAEMON):
    return json.dumps(value,separators=(",",":"))+"\n"


def run_for(network_value=None,daemon_values=None):
    values=iter(daemon_values or [DAEMON,DAEMON]); observed=network_value or network()
    def run(command,_timeout):
        if command[:3]==["docker","info","--format"]: return result(daemon_payload(next(values)))
        if command[:3]==["docker","network","inspect"]: return result(json.dumps([observed])+"\n")
        raise AssertionError(command)
    return run


def test_running_none_endpoint_cross_binds_daemon_network_container_and_endpoint():
    assert policy.require_running(run_for(),container(),NAME,NETWORK,DAEMON,time.monotonic()+10)==ENDPOINT


@pytest.mark.parametrize("field,value",[
    ("NetworkID","d"*64),("EndpointID",""),("EndpointID","g"*64),("IPAddress","172.18.0.2"),
    ("Gateway","172.18.0.1"),("DNSNames",[NAME]),("IPPrefixLen",False),("GlobalIPv6PrefixLen",False),("GwPriority",False),("GwPriority",1),
])
def test_routable_malformed_and_wrong_identity_endpoint_fields_block(field,value):
    data=container(); data["NetworkSettings"]["Networks"]["none"][field]=value
    with pytest.raises(RuntimeError,match="running none-network endpoint drift"):
        policy.require_running(run_for(),data,NAME,NETWORK,DAEMON,time.monotonic()+10)


@pytest.mark.parametrize("mutation",["missing","extra-network","extra-field","wrong-container","wrong-name","network-record","extra-record-field"])
def test_missing_extra_and_cross_inspection_drift_blocks(mutation):
    data=container(); observed=network()
    if mutation=="missing": data["NetworkSettings"]["Networks"]={}
    elif mutation=="extra-network": data["NetworkSettings"]["Networks"]["bridge"]={}
    elif mutation=="extra-field": data["NetworkSettings"]["Networks"]["none"]["Future"]=None
    elif mutation=="wrong-container": data["Id"]="d"*64
    elif mutation=="wrong-name": data["Name"]="/other"
    elif mutation=="network-record": observed["Containers"][CONTAINER]["EndpointID"]="d"*64
    else: observed["Containers"][CONTAINER]["Future"]=None
    with pytest.raises(RuntimeError): policy.require_running(run_for(observed),data,NAME,NETWORK,DAEMON,time.monotonic()+10)


def test_daemon_swap_taints_and_blocks_cross_inspection():
    tainted=[]
    with pytest.raises(policy.DaemonIdentityError,match="changed"):
        policy.require_running(run_for(daemon_values=[DAEMON,"other-daemon-1234567890"]),container(),NAME,NETWORK,DAEMON,time.monotonic()+10,lambda:tainted.append(True))
    assert tainted==[True]


def test_admission_authenticates_exact_engine_daemon_and_none_network(monkeypatch):
    calls=[]; daemon_values=iter([DAEMON,DAEMON,DAEMON])
    engine_payload=json.dumps({"architecture":"amd64","client_version":"28.0.4","negotiated_api_version":"1.48","operating_system":"linux","server_version":"28.0.4"},sort_keys=True,separators=(",",":"))+"\n"
    def run(command,_timeout):
        calls.append(command[:3])
        if command[:3]==["docker","info","--format"]: return result(daemon_payload(next(daemon_values)))
        if command[:3]==["docker","network","inspect"]: return result(json.dumps([network({})])+"\n")
        if command[:3]==["docker","version","--format"]: return result(engine_payload)
        raise AssertionError(command)
    assert policy.admit(run,time.monotonic()+10)==(DAEMON,NETWORK,"amd64")
    assert calls==[["docker","info","--format"],["docker","network","inspect"],["docker","info","--format"],["docker","version","--format"],["docker","info","--format"]]


@pytest.mark.parametrize("key,value",[("Driver","bridge"),("Scope","swarm"),("Id","short")])
def test_admission_rejects_noncanonical_none_network(key,value):
    observed=network({}); observed[key]=value
    with pytest.raises(RuntimeError,match="none-network identity drift"):
        policy.admit(run_for(observed,[DAEMON]),time.monotonic()+10)
