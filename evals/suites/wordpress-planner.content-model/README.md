# wordpress-planner.content-model Smoke Eval

Smoke-tier evaluation scaffold for `wordpress-planner.content-model`. This suite provides one fixture, one rubric, and fair baselines so the skill has initial eval evidence without claiming full benchmark readiness.

Output contract oracle:

```bash
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-planner.content-model \
  --output <candidate-output.md>
```
