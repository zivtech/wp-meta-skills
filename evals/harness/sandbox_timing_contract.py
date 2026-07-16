"""Shared successful lifecycle timing contract for producer and evidence validator."""

RUNTIME_KEYS=frozenset({
    "proxy_interpreter_preflight","acquisition_context_setup","container_setup",
    "dependency_acquisition","detach","detached_gate","generated","export",
})
FINALIZATION_KEYS=frozenset({"cleanup","end_to_end"})
EVIDENCE_KEYS=RUNTIME_KEYS|FINALIZATION_KEYS


def require_runtime(timings):
    if type(timings) is not dict or set(timings)!=RUNTIME_KEYS:
        raise RuntimeError("successful acquisition timing contract drift")
