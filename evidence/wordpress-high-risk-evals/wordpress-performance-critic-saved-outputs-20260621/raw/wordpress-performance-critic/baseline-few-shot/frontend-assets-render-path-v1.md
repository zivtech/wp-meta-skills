**Scope**

Review target: frontend asset loading, editor/frontend parity, and dynamic render-path performance for the `Acme Events Block` excerpt.

This review does **not** claim a Core Web Vitals failure. The fixture does not include field data, lab traces, page context, traffic volume, cache headers, or render timing.

**WordPress-Specific Decisions**

1. `wp_enqueue_script()` runs unconditionally during `init`.

   `acme-events-front` is enqueued for every request where WordPress initializes, regardless of whether the block appears on the page. That can add unnecessary frontend JavaScript cost site-wide.

   Better options:
   - Declare frontend assets in `block.json` with `viewScript` or `viewScriptModule`.
   - Conditionally enqueue only when the block is rendered.
   - Use block metadata asset handling so WordPress can load assets only when relevant.

2. The frontend script is registered with `false` for the footer argument.

   This loads the script in the document head, which can block parsing depending on the generated tag and browser behavior. If the script is not required before initial render, it should be loaded in the footer or with an appropriate loading strategy.

3. `jquery` is declared as a dependency without evidence.

   If `build/front.js` does not actually require jQuery, this pulls extra JavaScript into the render path. That should be verified from the built asset and removed if unused.

4. `editor_script` only covers editor loading.

   The block registration correctly identifies `acme-events-editor` as editor-only, but frontend behavior is handled separately through the unconditional enqueue. That creates editor/frontend confusion: frontend assets should be attached through block metadata or conditional frontend enqueue logic, not globally enqueued during block registration.

**Risks**

1. Render callback performs remote HTTP work on page render.

   ```php
   $response = wp_remote_get( 'https://example.invalid/events' );
   ```

   This makes page rendering dependent on a third-party network call. Risks include slow TTFB, request timeouts, outages, inconsistent page latency, and cascading frontend performance impact.

2. No timeout, error handling, or response validation.

   The code assumes the request succeeds and that the body decodes to an array. If the response fails, is slow, or returns malformed JSON, `count( $events )` may produce warnings or incorrect output.

3. No caching or stale fallback.

   Every render can trigger a remote fetch. A better design should define freshness requirements, cache successful responses with transients/object cache, and serve stale data when the remote source is unavailable.

4. Moving the HTTP call elsewhere is not enough.

   A cron job, preload step, or admin-triggered fetch only helps if it reduces user-facing render cost and has clear freshness, cache invalidation, and failure behavior. Otherwise it just moves the same cost to another request.

**Verification**

Minimum verification should include:

- Before/after browser performance trace for a page with the block.
- Synthetic page tests comparing pages with and without the block.
- Query Monitor, APM, or server timing around `acme_events_render_block()`.
- Remote HTTP timing, timeout behavior, cache hit/miss rate, and fallback path timing.
- Core Web Vitals only where field data or lab data exists; do not infer failure from code alone.

Specific checks:

- Confirm whether `front.js` is needed on every page.
- Confirm whether `front.js` uses jQuery.
- Confirm whether frontend assets load only when the block is present.
- Measure TTFB impact with cold cache, warm cache, remote timeout, and remote failure.
- Verify editor behavior still works after separating editor and frontend assets.

**Open Questions**

- How fresh must the event count be: seconds, minutes, hours, or manually refreshed?
- Is the block expected on high-traffic pages?
- Does `front.js` need to run before first paint?
- Does `front.js` actually depend on jQuery?
- Should failed remote requests show stale data, zero events, hidden output, or an error state?
- Is there an existing object cache, page cache, CDN, or APM layer available?

Primary finding: the current excerpt couples global frontend asset loading with render-time remote I/O. The performance fix should reduce unnecessary asset exposure and put the remote dependency behind measured caching, timeout, and fallback behavior.