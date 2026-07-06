**Scope**

This fixture should evaluate whether `wordpress-performance-critic` can review a WordPress performance task involving:

- Database query behavior
- Object/page caching assumptions
- Autoloaded options
- WP-Cron behavior
- Outbound HTTP calls
- Asset loading
- Measurement strategy

It should not produce fixes as if they were verified. The correct output is a performance review, not an implementation plan or benchmark report.

**WordPress-Specific Decisions**

A strong candidate response should stay WordPress-native:

- Use WordPress concepts like `WP_Query`, transients/object cache, autoloaded options, `wp_options`, `wp_cron`, enqueue APIs, REST/AJAX requests, and hooks.
- Recommend inspecting autoloaded options carefully, without deleting or mutating production rows.
- Treat WP-Cron as traffic-dependent unless a real system cron is confirmed.
- Discuss HTTP API calls through WordPress abstractions such as `wp_remote_get()` / `wp_remote_post()`.
- Review assets through enqueue/dependency strategy, conditional loading, and Core/Web Vitals impact.
- Separate cache layers: object cache, page cache, CDN/browser cache, and transients.

**Risks**

Key failure modes the critic should catch:

- Claiming benchmark improvements without data.
- Recommending unsafe production commands such as direct deletes from `wp_options`, cache flushes, or disabling cron without rollout planning.
- Treating all autoloaded options as bad instead of asking whether they are large, frequently used, or introduced by a plugin/theme.
- Assuming an object cache, page cache, CDN, or persistent cache exists.
- Blaming WordPress Core without isolating theme, plugin, query, hosting, and cache configuration factors.
- Flattening measurement into generic advice instead of naming specific WordPress observation points.

What I am not claiming: that any specific query, plugin, cron event, HTTP request, or asset is currently slow. The fixture does not provide runtime data.

**Verification**

The critic should ask for or recommend safe evidence gathering:

- Query Monitor or equivalent staging/local profiling
- Slow query logs or APM traces, if available
- Autoloaded option size report, read-only
- Cron event inventory and schedule review
- HTTP request timing and timeout review
- Asset waterfall / Lighthouse / WebPageTest results
- Cache headers and hit/miss evidence
- Before/after measurements only after controlled changes

Verification should be phrased as required before conclusions, not as proof already obtained.

**Open Questions**

- Is this single-site or multisite WordPress?
- Is there persistent object caching?
- Is WP-Cron disabled in favor of system cron?
- Which cache layers are active: page cache, CDN, browser cache, object cache?
- Are performance symptoms frontend, wp-admin, REST/AJAX, cron, or editor-specific?
- Is the environment production, staging, or local?
- What measurement baseline exists?

**Downstream Handoff**

If issues are confirmed, the correct chain would be:

`wordpress-performance-critic` → performance planner → WordPress executor → performance critic re-review.

The critic should identify risks and evidence gaps first, then hand off only scoped, verified work for planning and implementation.