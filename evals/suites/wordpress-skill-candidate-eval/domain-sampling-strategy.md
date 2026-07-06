# Domain Sampling Strategy

The suite uses 9 WordPress domains with 3 tiers each: clean control, has-risk, and ambiguous tradeoff. Each fixture includes a concrete WordPress artifact, target platform constraints, expected strong behavior, expected weak behavior, and rubric-level domain signals.

The design intentionally tests quality dimensions: WordPress specificity, severity calibration, remediation specificity, assumptions/evidence separation, provenance/safety, and false-positive resistance.

The goal is discrimination, not presence checking. If a zero-shot baseline and a strong candidate score within 0.2 on the pilot fixture, absolute scoring is considered saturated and the evaluation must switch to blind pairwise preference.
