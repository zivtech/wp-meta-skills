# Critic Corpus Provenance Manifest (recommendation 09)

Covers the fixture corpus across the four critic suites. Every corpus fixture carries a
`fixtures/<id>.provenance.yaml` sidecar with `tranche`, `provenance`, `license`, and `source`;
this manifest summarizes the sources and the licensing posture. The pre-existing smoke/focused
fixtures (no sidecar) are out of scope here and are covered by the candidate-eval provenance
manifest and the eval-suite integrity validator.

## Provenance labels

- **`authored`** — clean-room Zivtech-written WordPress code and answer keys. No upstream skill
  or fixture text is copied. This is the bulk of tranches J and C.
- **`tool`** — tranche-T fixtures reproducing a defect that a named WPCS/VIPCS sniff catches.
  The *label* is tool-derived (the sniff + line); the code is minimal clean-room PHP written to
  trigger that sniff, not copied from WPCS `.inc` files (which carry `// Bad.` markers that
  would leak the answer). `source` records the sniff, e.g. `wpcs-sniff:WordPress.Security.EscapeOutput`.
- **`researcher`** — tranche-J fixtures seeded from a real CVE by diffing the vulnerable and
  patched plugin versions (`evals/harness/build_cve_fixtures.py`). Staged as `status: draft`
  under `fixtures/_drafts/` until the human verification gate promotes them. `source` records
  `cve:<id> plugin=<slug> vulnerable=<v> patched=<v>`.

## Licensing posture

- All fixture code is GPL-compatible: `authored` and `tool` fixtures are GPL-2.0-or-later
  clean-room; `researcher` fixtures derive from GPL plugin code. This is fine in this
  GPL-3.0 repository.
- CVE seeds come from CVWP (`github.com/david-prv/vulnerable-wordpress-plugins`, GPL) or, if
  used, the Wordfence Intelligence feed (attribution required, commercial use permitted).
- **The WPScan database (CC BY-NC-SA, non-commercial) is never used.** The integrity guard
  (`test_source_is_not_a_noncommercial_feed`) fails any fixture whose `source` references it.

## Answer-key origin

Answer keys (`rubrics/<id>.rubric.yaml` `domain_signals` + the sidecar `grounding`) are written
by the fixture author for `authored`/`tool` fixtures, and by the human verification gate for
`researcher` fixtures (the CVE record supplies the CWE; the defect lines and `must_detect`
descriptions are confirmed by a person, since a CVE patch often carries ride-along refactors).
No answer-key content appears in the review-target `.md` — enforced by
`test_critic_corpus_integrity.py`.

## Tool-invisibility evidence

Each tranche-J sidecar's `tool_invisibility` block records the WPCS/PHPStan result that proves
the defect is not statically catchable. The evidence is reproducible via
`python3 evals/harness/verify_critic_tool_invisibility.py` (requires the pinned PHPCS/WPCS/PHPStan
stack in `evals/harness/php-tools/vendor`, installed with `composer install`).

Until 2026-08-13 this page overstated the gate: it named the PHPStan stack, but the script ran
WPCS only, so the PHPStan half of every sidecar's `tool_invisibility` claim was unexecuted. The
script now runs both, default-deny on unrecognised PHPStan identifiers, and runs in CI rather
than by hand. All nine PHP-bearing J fixtures pass both. See `corpus-prereg.md` §5 for the
result and for the excerpt-versus-plugin limitation that remains.
