# wordpress-theme-executor Smoke Eval

Smoke-tier evaluation scaffold for `wordpress-theme-executor`. This suite provides one fixture, one rubric, and fair baselines so the skill has initial eval evidence without claiming full benchmark readiness.

Output contract oracle:

```bash
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-theme-executor \
  --output <candidate-output.md>
```

Generated artifact oracle:

```bash
python3 evals/harness/validate_wordpress_artifact.py \
  --artifact-type theme \
  --path <generated-theme-dir>
```

Static theme validation proves metadata shape only. Site Editor, template-resolution, viewport, and keyboard/focus evidence require runtime smoke records.
