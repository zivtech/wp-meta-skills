# wordpress-planner.block Focused Smoke Eval

Focused smoke-tier definition for `wordpress-planner.block`. Its single fixture
is pinned to the existing `acme/runtime-card` contract: exact block identity,
block-only assets, dynamic save/render behavior, compatibility decision, and
separate build, registration, editor, and frontend proof. It also checks the
routing boundary between custom-block definition and migration transformation.
The saved-output oracle uses one exact, duplicate-rejecting decision record per
owning section. Record values are enumerated by the fixture and skill; prose and
fenced examples are not authoritative contract evidence.

This suite defines fixture and rubric expectations. It is not a benchmark result,
does not establish model superiority, and does not turn a planning response into
runtime evidence.

Output contract oracle:

```bash
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-planner.block \
  --output <candidate-output.md>
```
