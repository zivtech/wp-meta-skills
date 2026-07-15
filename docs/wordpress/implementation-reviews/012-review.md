Plan: 012
Plan base SHA: b7f396b74cebbacf11a29610f702c258fd6f600e
Reviewed code tip SHA: 6f58b96d7e636b151f6aa04d245cb17f1c9846d5
Implementation/fix commits: 6f58b96d7e636b151f6aa04d245cb17f1c9846d5
Verdict: ACCEPT

# Plan 012 Implementation Review

## Scope and architecture

The reviewed range removes query-string Gemini authentication and time-sensitive
Ollama/Gemini model defaults from the repair loop. Both external provider lanes
now require an explicit model and complete exact-model metadata preflight before
generation, packet creation, materialization, or certification. The repair loop
persists only an immutable seven-field preflight receipt and stops with a bounded
code when preflight fails.

`provider_preflight.py` owns the fixed provider origins and paths, canonical
model validation, credential alias precedence, provider response parsing, error
classification, and sanitized receipt construction. `safe_curl.py` owns only
the bounded transport: a fixed root-owned curl 8.4.0 or newer, first option
`--disable`, minimal child environment, exact caller-supplied origin/path policy,
no redirects or ambient proxy/CA/HOME/PATH/config, request/response/time bounds,
and anonymous header-FD delivery. Gemini permits only the fixed Google HTTPS
origin and model paths. Ollama permits only exact loopback HTTP `/api/show` and
`/api/generate` paths. Arbitrary HTTP is rejected.

Credentials are read from both supported environment aliases, validated as
bounded visible ASCII, and checked against the requested model before any URL,
transport, diagnostic, or receipt is built. The selected key exists only in the
Python process, bounded header bytes, anonymous pipe, and inherited read FD. The
child receives no caller environment and the pipe writer closes before request
stdin is communicated. Timeout and broken-pipe paths kill, drain, wait when
needed, close process streams, and close every parent descriptor.

## Review history and dispositions

The pre-implementation drift review accepted separating provider policy from
transport because the existing repair-loop and test modules were already near
the repository size ceiling. Cold review first rejected contradictory generic
HTTPS/loopback HTTP wording, stale drift and secret-scan ownership, an overbroad
repair-loop refactor statement, missing immutability/function-size constraints,
PATH-based curl discovery, an unsupported provider-key grammar claim, path
segment ambiguity, redirect wording, and metadata overclaiming. The ignored
plan was amended before code to define the three exact policies, fixed trusted
curl provenance, single-segment Gemini IDs, alias/header safety, narrow module
ownership, and metadata-only negative space; general and security cold reviews
then accepted implementation.

Regression tests were written first and initially failed collection because the
two planned modules did not exist. The first implementation pass exposed one
test-fixture defect: a five-second total timeout paired with a ten-second connect
timeout. The fixture was corrected rather than weakening transport validation.

Final adversarial review found five substantive defects. A secondary
`GEMINI_API_KEY` could be mistaken for a model when `GOOGLE_API_KEY` had
precedence, leaking the secondary alias into URL argv and the receipt; every
supported nonempty alias is now checked before preflight and generation. Curl
before 8.4.0 could buffer an unbounded unknown-length response despite
`--max-filesize`; trusted-curl discovery now blocks older versions. Wrong-typed
Gemini candidate/content/parts/text fields could raise `TypeError`; strict shape
parsing now returns `malformed_response`. Ollama's structured missing-model form
was flattened to `provider_error`; bounded token classification now returns
`model_not_found` without retaining the body. Finally, the live test could be
selected accidentally or pass by skipping prerequisites; pytest now excludes
it by default, an independent authorization sentinel is required, and missing
authorization/model/credential fails an explicitly selected manual gate.

Lifecycle review also required stronger proof. Added tests count parent FDs,
use a real helper child that must read header EOF before stdin, exercise a second
timeout through kill/wait/stream closure, and prove a spawned child is killed and
drained after header-pipe failure. General and security critics accepted the
staged reviewed tip with no unresolved Critical, Major, or Minor findings.

## Verification

- Focused final transport/provider/repair-loop gate: `97 passed, 1 deselected`.
- Cumulative ordinary harness gate: `1788 passed, 3 skipped, 41 deselected in 51.77s`.
- Default provider-test invocation: `27 passed, 1 deselected`; the credentialed
  marker is excluded without relying on operator convention.
- Unauthorized explicit live selection returned nonzero before transport. The
  authorized metadata-only gate with
  `WP_META_SKILLS_LIVE_PROVIDER_AUTHORIZED=1` and operator-selected
  `gemini-3.5-flash` returned `1 passed, 27 deselected in 0.20s` with no skip,
  credential, or provider body in output.
- Sanitized live receipt from the reviewed code tip:
  `{"schema_version":1,"provider":"gemini","model":"gemini-3.5-flash","timestamp":"2026-07-15T22:34:00Z","status":"pass","endpoint_class":"google_models_api","error_code":"none"}`.
- The live receipt proves exact metadata name visibility and advertised
  `generateContent` for that request. No generation request was made.
- Installer manifest verification, agent/skill frontmatter validation,
  WordPress Exact API validation, strict eval-suite integrity validation,
  workflow YAML parsing, changed Python compilation, and `git diff --check`:
  passed.
- Executable query-key scan: zero matches. Credential-flow scan found only the
  two environment reads and the two reviewed in-memory `x-goog-api-key` header
  constructions.
- All new source/test files are below 800 lines; new source functions are below
  50 lines and request/result/receipt records are frozen.
- Gitleaks scanned the complete staged implementation/fix diff immediately
  before commit and found no leaks.

## Negative space

This packet does not claim generation success, usable quota, billing
authorization, model quality, model superiority, or future provider/model
availability. Metadata advertising `generateContent` is not a content-generation
call. The operator-selected model is evidence for this smoke, not a repository
default or recommendation.

The boundary is POSIX `/dev/fd` plus a root-owned system curl 8.4.0 or newer;
unsupported platforms, older curl, missing trusted curl, or TLS failure are
blocked without an urllib, query-auth, temp-file, inherited-config, or insecure
fallback. Normal compiled/OS trust is preserved, but this packet does not
independently audit the operating system trust store. Root, a sufficiently
privileged debugger, or same-user memory inspection is outside the process-list
claim. The code prevents supported environment credentials from being reused as
the model; it cannot identify arbitrary secret material an operator supplies
under an unrelated name.

Provider bodies and prompts remain in bounded process memory only long enough to
parse or generate; they are not receipt or diagnostic fields. The Ollama error
classifier recognizes bounded missing-model phrases but is not a universal
provider-error ontology. This plan changes provider transport and preflight only;
it does not add providers, credential storage, a model-selection policy, or live
provider calls to ordinary CI.
