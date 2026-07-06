# wordpress-planner.block Smoke Eval

Smoke-tier evaluation scaffold for `wordpress-planner.block`. This suite provides one fixture, one rubric, and fair baselines so the skill has initial eval evidence without claiming full benchmark readiness.

Output contract oracle:

```bash
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-planner.block \
  --output <candidate-output.md>
```
