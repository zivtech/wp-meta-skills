# Focused Fixture: URL, Redirect, And Permalink Preservation

Plan the URL preservation part of a migration into WordPress. The client has
provided:

- A crawl of 12,000 current URLs with status codes.
- A CSV of 8,200 canonical content URLs from the legacy CMS.
- A WordPress target model with posts, landing pages, and staff profiles.
- A required permalink structure of `/insights/%postname%/` for articles and
  `/people/%slug%/` for staff profiles.
- SEO metadata export is still pending.
- The launch team wants "all redirects handled" but has not defined acceptance
  criteria for redirect coverage, chain limits, query strings, or 404 sampling.

## Expected Planning Focus

- Define a redirect-map creation and validation process with acceptance
  criteria, not just "set up redirects."
- Separate permalink model design from redirect implementation.
- Include canonical URL decisions, query-string handling, attachments/media
  URLs, chain prevention, 404 sampling, and crawl comparison.
- Name WordPress surfaces and commands such as `wp rewrite flush`,
  `wp search-replace`, `wp option get permalink_structure`, redirect plugin
  import/export commands where applicable, and crawl tooling.
- Preserve uncertainty around missing SEO metadata and unknown legacy aliases.

## Required Boundaries

Do not claim search-equity preservation without a validated redirect map,
pre/post-launch crawl comparison, and stakeholder-approved acceptance criteria.
