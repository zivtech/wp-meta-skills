# Second WPCS Profile — Measurement and Close-Out (2026-08-29)

## Bottom line

The proposal was to add a stricter third-party PHPCS ruleset as a second,
advisory profile, to test whether the `WPCS_REPAIR_HINTS` work generalizes or
was overfit to a looser standard.

**The measurement was run and it disproves the proposal's premise.** A second
ruleset can only test generalization if it is a *superset* of the first. The
available stricter rulesets are not supersets — they are different standards
with contrary opinions, and in at least one case their requirements are
logically incompatible with WordPress Coding Standards. No overfitting
conclusion can be drawn from them, in either direction.

This closes the item. It is recorded rather than retried.

## What was measured

Five generated plugin artifacts, each already passing static certification,
scanned twice with the pinned toolchain — PHP_CodeSniffer 3.13.5, WPCS 3.3.0,
PHPCSUtils 1.2.2, PHPCSExtra 1.5.0 — changing only `--standard`.

Baseline is the pinned default, `WordPress`. The stricter profile is
`Universal,NormalizedArrays,Modernize`, the three rulesets shipped by
PHPCSExtra, a package maintained by the PHP_CodeSniffer maintainers and
**already pinned in this repository's toolchain**. No dependency was added.

| Artifact | `WordPress` | `Universal,NormalizedArrays,Modernize` |
|---|---|---|
| `abilities-ai-surface-v1` | 0 errors, 2 warnings | 11 errors, 65 warnings |
| `mcp-adapter-wordpress-v1` | 0 errors, 0 warnings | 5 errors, 52 warnings |
| `phpunit-wordpress-v1` | 0 errors, 0 warnings | 7 errors, 49 warnings |
| `smoke-wordpress-v1` | 0 errors, 0 warnings | 1 error, 16 warnings |
| `ai-client-provider-wordpress-v1` | 0 errors, 0 warnings | 54 errors, 200 warnings |

460 violations in total, from seven sniffs:

| Sniff | Count | Nature |
|---|---:|---|
| `Universal` precision alignment found | 382 | Style opinion. Forbids space-alignment that WPCS permits. |
| `Universal` disallow `use` without alias | 27 | Style opinion. WPCS imposes no such requirement. |
| `NormalizedArrays` space after array opener | 15 | **Contradicts WPCS.** |
| `NormalizedArrays` space before array closer | 15 | **Contradicts WPCS.** |
| `Universal` require `exit`/`die` parentheses | 11 | Genuine, minor. |
| `Universal` disallow `final` class | 5 | Style opinion, and an unwelcome one. |
| `Universal` enforce curly-brace namespace syntax | 5 | Style opinion. |

## Why this is a contradiction, not a strictness gradient

`NormalizedArrays` reports `Expected no space after the array opener in a single
line array. Found: 1 space`. WPCS's `WordPress.Arrays.ArrayDeclarationSpacing`
requires exactly that space: `array( 'key' => 'value' )`.

The two requirements cannot both be satisfied. An artifact made clean under one
becomes dirty under the other, permanently, in both directions.

That single fact is enough to close the item. 397 of the 460 violations — the
two array sniffs plus precision alignment plus the alias and `final` rules — are
stylistic disagreements with WordPress, not latent defects the pinned standard
failed to catch. The residual signal, `exit`/`die` parentheses at 11
occurrences, is real but far too small and too narrow to support a claim about
whether repair hints generalize.

## The WordPress-family alternative, and why it is blocked

The measurement a superset *would* have provided is available in principle from
`automattic/vipwpcs` (`WordPressVIPMinimum`), which genuinely extends WPCS
rather than contradicting it.

It is blocked here on a version floor, not on preference. `automattic/vipwpcs`
requires `wp-coding-standards/wpcs ^3.4.1`, `phpcsstandards/phpcsextra ^1.5.1`,
and `phpcsstandards/phpcsutils ^1.2.3`. This repository pins `3.3.0`, `1.5.0`,
and `1.2.2`. Adding it would force an upgrade of the pinned default standard.

**That upgrade would destroy the comparison it was meant to enable.** Every
recorded WPCS result in this repository was produced against WPCS 3.3.0; moving
the default makes prior and future results incommensurable, which is precisely
the confound the measurement exists to avoid. Upgrading the toolchain is a
legitimate separate decision with its own re-baselining cost. It is not a
side-effect to absorb into an advisory-profile experiment.

Its license is also unresolved under this repository's own rule: GitHub reports
`NOASSERTION` for the repository while `composer.json` declares MIT. Per the
weak-license-evidence rule in `license-reuse-policy.md`, that is `Unknown` until
a person reads and classifies the license text.

## What was deliberately not built

**No `--phpcs-standard` selector was added.** The proposal called for one, and
building it now would mean shipping infrastructure whose only purpose is to
enable a profile this measurement just showed cannot serve its stated function.
`validate_wordpress_artifact.py` continues to pin `--standard=WordPress`.

If the toolchain is ever upgraded and `WordPressVIPMinimum` becomes available,
the selector becomes worth building at that point — with a real superset behind
it, and with re-baselining budgeted rather than discovered.

## What this does and does not license

**Licenses:** closing the second-profile item; the conclusion that a general-PHP
ruleset is not a valid advisory profile for WordPress code; and the decision not
to build the selector.

**Does not license** any claim that `WPCS_REPAIR_HINTS` generalize, or that they
are overfit. That question is untouched — the instrument selected to answer it
turned out to be incapable of answering it. Nor does it license a claim that
PHPCSExtra is a poor ruleset; it is a good ruleset for general PHP, aimed at a
different target.

## Reproducing

Requires the pinned toolchain fetched into `evals/harness/php-tools/vendor/`.
`<artifact>` is any certified plugin artifact directory.

```
evals/harness/php-tools/vendor/bin/phpcs \
  --runtime-set installed_paths \
  "$PWD/evals/harness/php-tools/vendor/wp-coding-standards/wpcs,$PWD/evals/harness/php-tools/vendor/phpcsstandards/phpcsutils,$PWD/evals/harness/php-tools/vendor/phpcsstandards/phpcsextra" \
  --standard=Universal,NormalizedArrays,Modernize --extensions=php --report=source <artifact>
```

Swap `--standard=WordPress` for the baseline. The artifacts were produced by
`evals/harness/certify_wordpress_executor_artifact.py --executor plugin` from
the packets in `evals/suites/wordpress-plugin-executor/examples/`.

The scan output itself is not committed: it is regenerated by the command above
in seconds, and writing it to gitignored `evals/results/` would have produced
exactly the dangling citation this repository has had to clean up before.
