# WordPress High-Risk Saved-Output Summary

Run ID: `wordpress-security-critic-saved-outputs-20260621`
Suite: `wordpress-security-critic`
Skill: `wordpress-security-critic`
Run directory: `evals/results/wordpress-security-critic-saved-outputs-20260621`

## Contract Evidence

- Generation OK: `12/12`
- Contract pass: `3/12`
- All generation OK: `true`
- All contracts pass: `false`

## Conditions

| Condition | Outputs | Generation OK | Contract Pass |
| --- | ---: | ---: | ---: |
| `baseline-few-shot` | 4 | 4 | 0 |
| `baseline-zero-shot` | 4 | 4 | 0 |
| `skill` | 4 | 4 | 3 |

## Focused Fixture Subset

The focused subset excludes legacy smoke fixtures and is the subset relevant
to the high-risk maturation plan's three-fixture minimum.

- Focused skill contracts pass: `3/3`
- All focused skill contracts pass: `true`

## Boundary

Saved-output contract evidence only. This is not answer-key scoring, human review, variance measurement, or public benchmark evidence.

Contract failures on baseline lanes can be useful evidence about contract adherence,
but they are not a quality benchmark by themselves.
