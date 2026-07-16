# Focused Smoke Fixture: Repo-Owned Source-To-Block Migration

Plan a migration change in a repository that already owns
`src/Migration/ArticleImporter.php`. The importer must be revised in place; it
must not be regenerated as a new plugin or handed to `wordpress-plugin-executor`
for replacement.

## Exact Source Record

Source entry `article-42` contains this ordered Rich Text body:

1. `heading-2` with text `Migration brief`;
2. a paragraph with link text `Read the source record` and source href
   `/node/7`;
3. an `embedded-entry` targeting `promo-9`;
4. unsupported node `legacy-carousel` at source path
   `fields.body.content[3]`.

The destination already registers dynamic block `acme/promo-card`; no custom
block definition change is requested. Its migration-facing attribute contract is
`sourceId: string`, and its frontend oracle is selector
`.wp-block-acme-promo-card` with visible text `Promo nine`.

## Exact Destination Contract

- The stored top-level block order is `core/heading`, `core/paragraph`, then
  `acme/promo-card`.
- The heading has level 2 and exact text `Migration brief`.
- The paragraph preserves link text `Read the source record` and rewrites the
  href to `/guides/source-record/`.
- The custom block carries exact attribute `sourceId: promo-9` and is serialized
  through WordPress block APIs rather than hand-built comment JSON.
- The unsupported carousel produces one accounted row containing its source
  path, source type, and a `manual_required` disposition. It produces no raw
  source token and no non-whitespace freeform block residue.

## Required Migration Proof

- Emit the exact authoritative records required by the Gutenberg migration
  contract: `Gutenberg target: post_content`, `Block mapping: core+custom`,
  `Unsupported content: accounted`, `Serialization API: serialize_blocks`,
  `Rerun policy: idempotent`, `Block validation oracle: parse_blocks`,
  `Semantic oracle: required`,
  `Semantic oracle fields: text,href,attributes,unsupported,freeform`,
  `Editor oracle: required`,
  `Editor oracle method: playwright-clone-save-reload-restore`,
  `Frontend oracle: required`,
  `Frontend oracle method: playwright-selector-visible-text`, and
  `Fixture: required`, and `Fixture identity: article-42-rich-text`. Put each
  record at column zero, put explanation in the
  surrounding prose, and do not add detail to these enumerated values.
- Preserve stable identity `article-42`, use a dry run and rollback artifact,
  and define how relationship/link resolution is ordered.
- An unchanged second import performs zero body writes. A changed heading writes
  the owned post once. `wp_update_post( $args, true )` returning `WP_Error` or
  zero fails the run instead of reporting completion.
- Give each declared semantic property its own destination check: block order,
  heading level/text, rewritten link text/href, custom-block attribute,
  unsupported row, and absent freeform/raw source residue.
- Use a disposable cloned post for editor dirty/save/reload/restore proof, then
  compare its final database `post_content` hash with the baseline.
- Prove frontend selector `.wp-block-acme-promo-card` and text `Promo nine`
  independently of database parsing.

## Routing Boundary

The migration planner owns this mapping, serialization, unsupported accounting,
idempotence, rollback, and semantic/editor/frontend proof. Because
`acme/promo-card` already satisfies the required contract, do not invoke the
block planner or block executor. If its definition later changes, hand off only
that bounded block contract; the repository-owned importer still remains in its
own implementation lane.

Do not claim that this synthetic plan proves a completed migration, production
readiness, or benchmark superiority.
