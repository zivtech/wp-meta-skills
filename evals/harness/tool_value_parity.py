"""Deterministic tool-output equivalence check (design §2.5).

Purpose (verbatim from the design): establish that the eight in-scope
tools, called through the real MCP endpoint, return the same thing against
Lane H's stack as against a real Local site with the same golden and the
same seeded fault. This is what licenses the word "Local" in any
conclusion (design §9.3).

This module implements the DETERMINISTIC half: normalization (step 4) and
record comparison (step 5) — pure string/data logic, fully unit-testable
with no MCP server anywhere (see
evals/harness/tests/test_tool_value_parity.py). The two things that
actually need a live endpoint — issuing the `tools/list` + 15-call sequence
against Lane H's headless server, and the same sequence against a real
Local install's add-on server — are marked `# SEAM(headless-entrypoint):`
and `# SEAM(stack):` respectively, below and in
evals/harness/tool_value_live_backend.py.

CI self-parity (design §2.5 "CI half"): the Lane H side runs against two
independently built stack containers to catch the normalizer's own
flakiness, not to compare H against L. That is the same `compare_records`
function called twice with two Lane-H-shaped fetches instead of one H and
one L fetch — see `self_parity_report()`.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# The 16-step call sequence (design §2.5 step 3), named so both a live
# fetcher and a test double can be keyed the same way.
# ---------------------------------------------------------------------------
PARITY_STEPS: tuple[str, ...] = (
    "tools_list",
    "read_error_log_default",
    "read_error_log_filtered",
    "read_access_log",
    "read_wp_config_before",
    "wp_cli_plugin_list",
    "wp_cli_option_get_home",
    "wp_cli_eval_refused",
    "get_site_info",
    "site_health_check",
    "wp_debug_toggle_on",
    "read_wp_config_after_on",
    "wp_debug_toggle_off",
    "read_wp_config_after_round_trip",
    "edit_wp_config",
    "read_wp_config_after_edit",
)

EXPECTED_TOOL_COUNT = 13


# ---------------------------------------------------------------------------
# Normalization (design §2.5 step 4)
# ---------------------------------------------------------------------------

_SITE_ROOT_PATTERNS = (
    re.compile(r"/srv/sites/[^/\s\"]+"),
    re.compile(r"/Users/[^/\s\"]+/Local Sites/[^/\s\"]+"),
)
_RUN_DIR_PATTERNS = (
    re.compile(r"/srv/run/[^/\s\"]+"),
    re.compile(r"[^\s\"]*Library/Application Support/Local/run/[^/\s\"]+"),
)
_BINARY_PREFIX_PATTERNS = (
    re.compile(r"/srv/local-app/extraResources/bin/wp-cli/wp-cli\.phar"),
    re.compile(r"/srv/local-app/lightning-services/[^\s\"]*?/bin/[^\s\"]*"),
    re.compile(r"/Applications/Local\.app/Contents/Resources/extraResources/[^\s\"]*"),
)
_LOG_TIMESTAMP_RE = re.compile(r"\[\d{1,2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2} [A-Za-z0-9+\-:]+\]")
_HOSTNAME_RE = re.compile(r"\b[a-z0-9-]+\.local\b", re.IGNORECASE)
_SIZE_FIELD_RE = re.compile(r'("(?:sizeKb|totalLines)"\s*:\s*)-?\d+(\.\d+)?')


def normalize(text: str) -> str:
    """Applies every normalization design §2.5 step 4 names, in order."""
    normalized = text
    for pattern in _SITE_ROOT_PATTERNS:
        normalized = pattern.sub("<SITE>", normalized)
    for pattern in _RUN_DIR_PATTERNS:
        normalized = pattern.sub("<RUN>", normalized)
    for pattern in _BINARY_PREFIX_PATTERNS:
        normalized = pattern.sub("<BIN>", normalized)
    normalized = _LOG_TIMESTAMP_RE.sub("[TS]", normalized)
    normalized = _SIZE_FIELD_RE.sub(r"\1<N>", normalized)
    normalized = _HOSTNAME_RE.sub("<HOST>", normalized)
    return normalized


def normalize_json_value(value: Any) -> Any:
    """Recursively applies `normalize` to every string leaf in a JSON-ish
    value (dict/list/str), leaving other scalar types untouched."""
    if isinstance(value, str):
        return normalize(value)
    if isinstance(value, list):
        return [normalize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_json_value(item) for key, item in value.items()}
    return value


# ---------------------------------------------------------------------------
# Record comparison (design §2.5 step 5)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StepRecord:
    step: str
    tool: str
    args: dict[str, Any]
    response: Any  # JSON-ish: dict, list, or str


@dataclass
class StepResult:
    step: str
    tool: str
    args: dict[str, Any]
    lane_h: Any
    lane_l: Any
    equal: bool
    diff: str | None = None


@dataclass
class ParityReport:
    results: list[StepResult] = field(default_factory=list)
    fork_commit: str = ""
    local_version: str = ""
    stack_image_digest: str = ""
    date: str = ""

    @property
    def status(self) -> str:
        return "equivalent" if all(r.equal for r in self.results) else "divergent"

    @property
    def divergent_tools(self) -> list[str]:
        return sorted({r.tool for r in self.results if not r.equal})

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fork_commit": self.fork_commit,
            "local_version": self.local_version,
            "stack_image_digest": self.stack_image_digest,
            "date": self.date,
            "results": [
                {
                    "step": r.step, "tool": r.tool, "args": r.args,
                    "lane_H": r.lane_h, "lane_L": r.lane_l, "equal": r.equal, "diff": r.diff,
                }
                for r in self.results
            ],
        }


def _diff_summary(a: Any, b: Any) -> str:
    a_text = json.dumps(a, sort_keys=True) if not isinstance(a, str) else a
    b_text = json.dumps(b, sort_keys=True) if not isinstance(b, str) else b
    return f"lane_H={a_text!r} lane_L={b_text!r}"


def missing_canonical_steps(records: dict[str, StepRecord]) -> list[str]:
    """Names any of the fixed PARITY_STEPS a fetcher failed to populate —
    a real run should call this on both lanes' records before comparing;
    an empty result confirms full step coverage (design §2.5 step 3's
    16-call sequence), separately from whether the *values* match."""
    return [step for step in PARITY_STEPS if step not in records]


def compare_records(
    lane_h_records: dict[str, StepRecord], lane_l_records: dict[str, StepRecord],
    *, fork_commit: str = "", local_version: str = "", stack_image_digest: str = "", date: str = "",
) -> ParityReport:
    """Pairs Lane H and Lane L records by step name and compares the
    normalized values. Iterates the UNION of steps present on either side
    (not blindly the full canonical list) so a single-step comparison can
    be tested in isolation; a step missing from only one side is still a
    divergence (recorded with the missing side as None) — never silently
    skipped. Call `missing_canonical_steps` separately to assert full
    16-step coverage from a real fetch."""
    report = ParityReport(
        fork_commit=fork_commit, local_version=local_version,
        stack_image_digest=stack_image_digest, date=date,
    )
    provided_steps = set(lane_h_records) | set(lane_l_records)
    ordered_steps = [step for step in PARITY_STEPS if step in provided_steps]
    ordered_steps += sorted(provided_steps - set(PARITY_STEPS))
    for step in ordered_steps:
        h_record = lane_h_records.get(step)
        l_record = lane_l_records.get(step)
        tool = (h_record or l_record).tool if (h_record or l_record) else "unknown"
        args = (h_record or l_record).args if (h_record or l_record) else {}
        h_value = normalize_json_value(h_record.response) if h_record else None
        l_value = normalize_json_value(l_record.response) if l_record else None
        equal = h_record is not None and l_record is not None and h_value == l_value
        diff = None if equal else _diff_summary(h_value, l_value)
        report.results.append(StepResult(step, tool, args, h_value, l_value, equal, diff))
    return report


def self_parity_report(
    fetch_a: dict[str, StepRecord], fetch_b: dict[str, StepRecord], **metadata: str,
) -> ParityReport:
    """CI self-parity (design §2.5 "CI half"): compares two independently
    built Lane H stacks against each other with the identical logic used
    for the real H-vs-L comparison, to catch the normalizer's own
    flakiness rather than a real product divergence."""
    return compare_records(fetch_a, fetch_b, **metadata)


def assert_tools_list_count(records: dict[str, StepRecord], expected: int = EXPECTED_TOOL_COUNT) -> bool:
    """MCP tool-contract smoke (design §8): tools/list must return exactly
    `expected` names. Pinned to the fork commit under test (78c87ea)."""
    record = records.get("tools_list")
    if record is None:
        return False
    response = record.response
    if isinstance(response, dict) and "tools" in response:
        response = response["tools"]
    return isinstance(response, list) and len(response) == expected


# ---------------------------------------------------------------------------
# Live fetchers — SEAM(headless-entrypoint) / SEAM(stack)
# ---------------------------------------------------------------------------

# The design §2.5 step-3 table, keyed by PARITY_STEPS name: (tool name or
# the literal method "tools/list", MCP tool arguments). Order matters — the
# wp_debug_toggle round trip is order-sensitive — and `dict` preserves
# insertion order, so iterating this dict IS the call sequence.
_PARITY_CALLS: dict[str, tuple[str, dict[str, Any]]] = {
    "tools_list": ("tools/list", {}),
    "read_error_log_default": ("read_error_log", {}),
    "read_error_log_filtered": ("read_error_log", {"lines": 5, "filter": "Fatal"}),
    "read_access_log": ("read_access_log", {"lines": 5}),
    "read_wp_config_before": ("read_wp_config", {}),
    "wp_cli_plugin_list": ("wp_cli", {"args": "plugin list --format=json"}),
    "wp_cli_option_get_home": ("wp_cli", {"args": "option get home"}),
    "wp_cli_eval_refused": ("wp_cli", {"args": "eval 'echo 1;'"}),
    "get_site_info": ("get_site_info", {}),
    "site_health_check": ("site_health_check", {}),
    "wp_debug_toggle_on": ("wp_debug_toggle", {"enable": True}),
    "read_wp_config_after_on": ("read_wp_config", {}),
    "wp_debug_toggle_off": ("wp_debug_toggle", {"enable": False}),
    "read_wp_config_after_round_trip": ("read_wp_config", {}),
    "edit_wp_config": ("edit_wp_config", {"name": "ACME_PARITY", "value": "'1'"}),
    "read_wp_config_after_edit": ("read_wp_config", {}),
}
assert tuple(_PARITY_CALLS) == PARITY_STEPS  # keep the table and the canonical step list in lockstep


class _McpJsonRpcSession:
    """Minimal MCP-over-streamable-HTTP JSON-RPC client — stdlib only
    (`urllib`), mirroring the shape every other live call site in this
    harness uses (tool_value_live_backend.py's `_request`). Proven against a
    real headless server 2026-09-03 (fixture
    fatal-undefined-function-page-scoped's end-to-end run): `initialize`
    first to obtain the `mcp-session-id` the SDK's StreamableHTTPServerTransport
    requires on every subsequent call, then plain `tools/list` /
    `tools/call` requests carrying that header alongside the bearer token.
    """

    def __init__(self, base_url: str, token: str, *, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.session_id: str | None = None
        self._next_id = 1

    def _post(self, method: str, params: dict[str, Any]) -> Any:
        body = json.dumps({
            "jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params,
        }).encode("utf-8")
        self._next_id += 1
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        request = urllib.request.Request(self.base_url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            if not self.session_id:
                self.session_id = response.headers.get("mcp-session-id")
            raw = response.read().decode("utf-8", errors="replace")
        # The transport may frame a response as SSE ("event: message\ndata:
        # {...}\n\n") depending on Accept negotiation; unwrap if so, else the
        # body is already a bare JSON object.
        match = re.search(r"data:\s*(\{.*\})", raw, re.S)
        payload = json.loads(match.group(1) if match else raw)
        if "error" in payload:
            raise RuntimeError(f"MCP error calling {method}: {payload['error']}")
        return payload["result"]

    def initialize(self, *, client_name: str = "tool-value-parity", client_version: str = "0") -> None:
        self._post("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": client_name, "version": client_version},
        })

    def tools_list(self) -> Any:
        return self._post("tools/list", {})

    def tools_call(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self._post("tools/call", {"name": name, "arguments": arguments})
        # Unwrap the standard single-text-block tool result shape into the
        # bare value (JSON, if the tool's text happens to be JSON, else the
        # raw string) so records compare like-for-like with `tools/list`'s
        # already-structured result.
        content = result.get("content") if isinstance(result, dict) else None
        if isinstance(content, list) and len(content) == 1 and content[0].get("type") == "text":
            text = content[0]["text"]
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return result


def fetch_lane_h_records(base_url: str, token: str, site_id: str) -> dict[str, StepRecord]:
    """Issues the design §2.5 step-3 call sequence over JSON-RPC against a
    running headless server (`http://127.0.0.1:<port>/sites/<siteId>/mcp`),
    in order (the toggles are order-sensitive). `site_id` is accepted for
    signature symmetry with `fetch_lane_l_records` and interface stability
    (a future multi-site headless server would need it to pick a session)
    but the URL path already names the site; the running fork's headless
    entrypoint (`src/headless.ts`, branch eval/headless-harness) only ever
    registers one.

    Proven against a live container 2026-09-03 (see this session's report):
    `curl`-equivalent `initialize` -> `tools/list` -> the 15 tool calls all
    returned real data from a real seeded WordPress site.
    """
    del site_id  # see docstring — the URL path, not this parameter, selects the site
    session = _McpJsonRpcSession(base_url, token)
    session.initialize()
    records: dict[str, StepRecord] = {}
    for step, (tool, args) in _PARITY_CALLS.items():
        response = session.tools_list() if tool == "tools/list" else session.tools_call(tool, args)
        records[step] = StepRecord(step=step, tool=tool, args=args, response=response)
    return records


def fetch_lane_l_records(port_file: str, token_file: str, site_id: str) -> dict[str, StepRecord]:
    """# SEAM(stack): issues the same call sequence against a real Local
    install's add-on server, with port/token read from
    ~/.local-agent-tools/{port,token} (design §2.5 step 2). Requires a
    machine with Local installed, which this repository's environment does
    not have (design §2.1) — this is Lane L, run once per (fork commit,
    Local version) on the Local machine (design §2.5 "CI half").
    """
    raise NotImplementedError(
        "SEAM(stack): requires a machine with a real Local install; see design §2.5."
    )
