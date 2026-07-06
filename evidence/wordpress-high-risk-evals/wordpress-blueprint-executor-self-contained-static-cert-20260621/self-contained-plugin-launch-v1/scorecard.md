# WordPress Executor Artifact Certification

- Executor: `blueprint`
- Status: `pass`
- Packet: `evals/suites/wordpress-blueprint-executor/examples/self-contained-plugin-launch-v1.materializable-packet.md`
- Output directory: `evals/results/wordpress-blueprint-executor-self-contained-static-cert-20260621/self-contained-plugin-launch-v1/generated-blueprint`
- Artifact path: `evals/results/wordpress-blueprint-executor-self-contained-static-cert-20260621/self-contained-plugin-launch-v1/generated-blueprint/blueprint.json`
- Profile: `static`
- Required tools: `none`

## Gates

- Packet gate: `pass`
- Materialization gate: `pass`
- Artifact gate: `pass`

## Negative Space

- This certifies only the supplied saved executor packet, not model quality or variance.
- Static profile passes do not prove WPCS, Plugin Check, PHPUnit, wp-env, browser, editor, or frontend behavior.
- Runtime profile results are environment-specific and report missing required tools as blocked.
