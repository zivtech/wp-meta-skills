# Eval Suite Quality Gaps

This file records eval-suite content that exists in the repository but is not yet trustworthy as scoreable benchmark material. Validators may use these entries to distinguish known quarantined quality debt from newly introduced structural drift.

Format for machine-readable entries:

```text
- suite=<suite-name> scope=<scope> status=<status> reason="<short reason>"
```

## Known Gaps

No suites in this repository are currently quarantined. Historical entries for
`dashboard-planner` and `proposal-critic` were removed on 2026-07-02 because
those suites belong to the `zivtech-meta-skills` monorepo and are not part of
this standalone package.
