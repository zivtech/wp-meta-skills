# wordpress-planner.theme Smoke Eval

Smoke-tier evaluation scaffold for `wordpress-planner.theme`. It keeps a
generic WordPress-native smoke fixture and a separate external-design-baseline
fixture/rubric, so the baseline translation contract does not replace normal
theme planning coverage. Both remain scaffolds, not benchmark evidence.

Output contract oracle:

```bash
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-planner.theme \
  --output <candidate-output.md>
```
