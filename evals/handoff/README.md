# Converged Artifact Handoff

This directory carries executor packets that converged locally on every
macOS-reachable gate and are handed to the no-secrets Linux CI lane for the
gates a laptop cannot run by design.

## Why this exists

The repair loop's runtime profile splits across the sandbox boundary:

- **macOS-reachable:** packet contract, materialization, static artifact
  heuristics, and the pinned-toolchain `phpcs_wpcs` scan (with the
  deterministic phpcbf autofix stage).
- **Linux-only by design:** `wp_cli_activation`, `plugin_check`, and
  `container_browser` execute generated code, so they run only inside the
  no-secrets isolated Docker runtime (`host_fallback: false`). CI provides
  that boundary; a local macOS run reports them blocked.

A locally converged packet is therefore not fully certified until the
`converged-artifact-handoff` CI job re-certifies it on Linux.

## Layout

```
evals/handoff/<handoff-id>/
  packet.md          # the converged executor packet, byte-exact
  provenance.json    # identity binding and source-run record
```

`provenance.json` (schema_version 1) records: `handoff_id`, `executor`,
`profile`, `packet_sha256`, and a `source` block naming the producing run id,
provider, model, suite, fixture, condition, iteration, and date, plus the
local gate summary at convergence. The CI job refuses re-certification when
the committed packet does not hash to `packet_sha256`.

## How CI treats this directory

For every `evals/handoff/*/provenance.json`, the
`converged-artifact-handoff` job in `validate.yml` runs
`evals/harness/recertify_wordpress_executor_packet.py` — the exact
`make_certify` composition the repair loop used (static certifier plus
isolated runtime smoke), with no LLM involved — and requires a green verdict.
The `recertification.json` evidence is published to the job step summary.
When this directory holds no artifacts the job detects that and skips its
heavy steps.

## What a green re-certification does and does not claim

Green means the committed packet materializes deterministically and passes
the full runtime profile — including activation, Plugin Check, and the
container browser oracle — inside the reviewed isolation boundary. It does
not claim benchmark superiority, release readiness, or that generated
application behavior is benign beyond the tested oracles (see the runtime
oracle runbook's negative space).

## Generated-code provenance

Packets here are model-generated evaluation artifacts produced by the repair
loop against repository-owned fixtures. The producing model and run are
recorded in `provenance.json`; the committed text is treated as
repository-owned evaluation evidence under the root license, consistent with
`docs/wordpress/provenance-policy.md`.
