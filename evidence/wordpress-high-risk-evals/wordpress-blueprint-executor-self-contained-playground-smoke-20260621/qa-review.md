# WordPress Blueprint Self-contained Playground Smoke QA Review

- Review date: 2026-06-21
- Reviewed run: `wordpress-blueprint-executor-self-contained-playground-smoke-20260621`
- Related static run: `wordpress-blueprint-executor-self-contained-static-cert-20260621`
- Related preflight run: `wordpress-blueprint-executor-self-contained-launch-preflight-20260621`
- Review scope: one self-contained `wordpress-blueprint-executor` packet, its
  generated Blueprint, launch-readiness preflight, and observed WordPress
  Playground smoke.
- Review mode: main-agent QA review. A callable `qa-critic` or independent
  test-critic review was not run in this Codex session, so this artifact should
  be superseded if an independent QA/test-critic review is later run.

## Verdict

ACCEPT-WITH-RESERVATIONS for internal runtime-evidence and evidence-boundary
use.

REVISE before any public benchmark, release-readiness, VFS-backed Blueprint
runtime, broad Blueprint executor maturity, or WordPress version-support claim.

The run is useful because it crosses the browser/runtime boundary for one
self-contained Blueprint artifact: WordPress Playground returned HTTP `200`,
landed on the expected admin URL, rendered `Inline Blueprint Smoke Ready`, and
recorded no runtime errors. It is not broad enough to prove the Blueprint
executor handles VFS-backed packets, block/editor behavior, theme state,
external integrations, or supported-version matrices.

## Evidence Inspected

- `evals/suites/wordpress-blueprint-executor/examples/self-contained-plugin-launch-v1.materializable-packet.md`
- `evals/results/wordpress-blueprint-executor-self-contained-static-cert-20260621/scorecard.md`
- `evals/results/wordpress-blueprint-executor-self-contained-static-cert-20260621/certification-summary.json`
- `evals/results/wordpress-blueprint-executor-self-contained-static-cert-20260621/self-contained-plugin-launch-v1/generated-blueprint/blueprint.json`
- `evals/results/wordpress-blueprint-executor-self-contained-launch-preflight-20260621/scorecard.md`
- `evals/results/wordpress-blueprint-executor-self-contained-launch-preflight-20260621/launch-preflight-summary.json`
- `evals/results/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/scorecard.md`
- `evals/results/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/playground-smoke.json`
- `evals/harness/smoke_wordpress_blueprint_playground.py`
- `evals/harness/audit_wordpress_blueprint_launch_readiness.py`
- `evals/harness/certify_wordpress_executor_artifact.py`

## Findings

### Major: Runtime evidence is real, but narrow

The smoke run records status `pass`, response status `200`, landing seen
`true`, visible text found `true`, and observed landing URL
`https://playground.wordpress.net/scope:ambitious-sunny-valley/wp-admin/admin.php?page=acme-inline-blueprint-smoke`.
The captured frame text includes `Inline Blueprint Smoke Ready` and
`Self-contained Playground launch fixture loaded without VFS payloads.`

Impact: this closes the specific gap for one self-contained Playground launch
smoke. It does not close the VFS-backed packet gap or support a broad Blueprint
executor runtime claim.

### Major: VFS-backed Blueprint packets remain blocked

The self-contained packet succeeds by using `mkdir` and `writeFile` to inline a
disposable plugin. That is the right shape for a launchable smoke, but it is
different from the earlier focused Blueprint packets whose launch-readiness
preflight is blocked by missing local plugin/theme ZIP payloads.

Impact: accepted claims must distinguish self-contained runtime evidence from
VFS-backed runtime evidence. The VFS-backed packets still need supplied payloads
or redesigned self-contained fixtures before runtime claims are honest.

### Major: WordPress version evidence is not a support matrix

The Blueprint requested `preferredVersions.wp: latest`, and Playground emitted
the warning `Loaded WordPress version (7.0) differs from requested version
(latest).` The observed admin frame also reports `Version 7.0`.

Impact: this is acceptable for a disposable Playground smoke whose purpose is
to prove launch mechanics and a visible assertion. It is not evidence that the
artifact works across supported WordPress versions, and it should not be used
to claim compatibility with a specific production WordPress release.

### Moderate: Static and preflight gates are useful but not runtime substitutes

The static certification run passed packet, materialization, and static
artifact gates. The launch-readiness preflight recorded `ready_for_manual_launch`
with five Blueprint steps, zero VFS references, and zero missing payloads. Those
checks explain why the browser smoke was launchable, but they do not prove page
rendering by themselves.

Impact: keep the certification, preflight, and browser smoke as separate
evidence layers. Do not collapse static validity into runtime proof.

### Moderate: Evidence is textual, not a full reviewer artifact

The run captured JSON output, frame text, console messages, and runtime error
state. It did not capture a screenshot/video, repeat-run variance, manual
review notes from an owner, or independent QA/test-critic review.

Impact: this is enough for internal evidence-boundary use and standalone
staging review. It is not enough for public release certification or benchmark
claims.

### Low: Packet verification notes are now stale in one place

The saved packet's `Verification Notes` still say the Playground launch smoke
must be recorded. The recorded smoke now exists in the reviewed run directory.

Impact: this is not a result defect, but future readers should follow the run
artifacts rather than treating the packet's original handoff note as current
status.

## Accepted Uses

- State that one self-contained Blueprint packet launched in WordPress
  Playground and rendered the expected visible assertion.
- Bundle the static certification, launch-readiness preflight, browser smoke,
  and this QA review as internal evidence for the private `wp-meta-skills`
  staging review.
- Use the result to narrow the remaining Blueprint gap to VFS-backed packets,
  broader behavior, variance, and independent review.
- Keep the result in the high-risk evidence bundle as a launch-mechanics proof
  for `self-contained-plugin-launch-v1`.

## Rejected Uses

- Do not claim the Blueprint executor is benchmark mature.
- Do not claim VFS-backed packets launch successfully.
- Do not claim frontend, editor, block, theme, external-service, migration, or
  production deployment behavior from this admin-page smoke.
- Do not claim public release readiness, owner approval, or review approval.
- Do not claim WordPress version-support coverage or compatibility beyond this
  observed Playground session.
- Do not treat this main-agent QA review as an independent QA/test-critic
  review.

## Required Follow-Up

1. Add independent QA/test-critic or owner review before using this as public
   release-quality evidence.
2. Supply the missing VFS plugin/theme ZIP payloads or replace those fixtures
   with launchable self-contained packets before making VFS-backed runtime
   claims.
3. Repeat the browser smoke across pinned WordPress versions if version support
   matters.
4. Capture screenshot/video evidence if the release review wants a human
   inspection artifact rather than JSON and frame text only.
5. Keep PR #11 review/merge, standalone owner approval, public visibility
   approval, and cutover approval blocked until the assigned reviewers act.

## Boundary

This review accepts the self-contained Playground smoke as real but narrow
runtime evidence. It does not make the WordPress suite done, it does not replace
independent review, and it does not approve public release of the standalone
`wp-meta-skills` repository.
