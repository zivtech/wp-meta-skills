"""Sticky daemon-authenticated Docker control operations and retries."""
from __future__ import annotations

import time

import sandbox_none_network


def _remaining(deadline):
    value=deadline-time.monotonic()
    if value<=0: raise TimeoutError("daemon-bound Docker operation deadline exceeded")
    return value


def _taint(ledger):
    ledger.identity_tainted=True


def require(ledger,control,deadline):
    if ledger.identity_tainted: raise sandbox_none_network.DaemonIdentityError("Docker daemon identity was previously tainted")
    if not ledger.daemon_id: raise sandbox_none_network.DaemonIdentityError("Docker daemon identity was not authenticated")
    sandbox_none_network.require_daemon(control,ledger.daemon_id,deadline,lambda:_taint(ledger))


def run(ledger,command,timeout,control,deadline=None):
    deadline=deadline or time.monotonic()+timeout+60
    require(ledger,control,deadline)
    result=control(command,min(timeout,_remaining(deadline)))
    require(ledger,control,deadline)
    return result


def retry(ledger,command,control,deadline=None):
    deadline=deadline or time.monotonic()+180; failure="nonzero exit"
    for _attempt in range(2):
        try:
            result=run(ledger,command,60,control,deadline)
            if not result["returncode"]: return
        except sandbox_none_network.DaemonIdentityError: raise
        except Exception as exc: failure=type(exc).__name__
    raise RuntimeError(f"daemon-bound Docker cleanup failed ({failure})")


def periodic(ledger,control,deadline,interval=1.0):
    last=[0.0]
    def gate():
        now=time.monotonic()
        if now-last[0]>=interval: require(ledger,control,deadline); last[0]=now
    return gate
