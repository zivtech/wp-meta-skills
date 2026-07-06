**Scope**

Review target: `acme_directory_get_cards()` with emphasis on WordPress option pressure, transient design, invalidation, and render-time performance risk.

This review does **not** claim confirmed site-wide impact, confirmed autoload behavior, or production capacity risk. Those require measurement against the actual WordPress version, database state, object cache configuration, traffic profile, and runtime behavior.

**WordPress-Specific Decisions**

The biggest concern is this line:

```php
update_option( 'acme_directory_last_payload', $cards );
```

`$cards` appears to be a remote API payload and could grow without a clear size limit. Storing it in `wp_options` creates option-table pressure, and the code does not explicitly decide whether this option should be autoloaded. That decision matters because large autoloaded options can increase memory use and bootstrap cost.

However, I would not state that this option **is** autoloaded without checking the active WordPress version and the actual `update_option()` behavior/site state. The review finding should be: “this stores a potentially large payload in options without an explicit autoload/storage decision,” not “this definitely autoloads a large payload.”

The transient is also incomplete:

```php
set_transient( 'acme_directory_cards', $cards );
```

No expiration is provided, so the cached payload can persist indefinitely depending on storage behavior. There is also no invalidation path when cards change, settings change, imports run, or the upstream API’s freshness boundary is reached.

A transient here is not a complete performance fix. It only avoids repeat remote calls after a successful cache write. It does not define freshness, failure behavior, cache invalidation, or payload limits.

**Risks**

1. Potential large option-table payload  
   `acme_directory_last_payload` stores the full card response in `wp_options`. If the payload grows, this can create database bloat and possibly autoload pressure depending on actual autoload behavior.

2. Unbounded cache lifetime  
   `set_transient()` has no expiration. The plugin has no stated freshness policy, so stale cards may remain indefinitely.

3. Missing invalidation  
   There are no hooks or explicit deletes for card updates, settings changes, imports, admin saves, or remote API version changes.

4. Render-time remote dependency  
   On cache miss, the function performs `wp_remote_get()` inline. If this runs during page rendering, the page can block on the remote API.

5. No HTTP safeguards  
   There is no timeout, error handling, status-code validation, JSON validation, retry boundary, or stale-cache fallback.

6. Unsafe assumptions about response shape  
   The code assumes `$settings['api_url']` exists and that the remote response body decodes into usable card data.

**Verification**

Before making site-wide performance claims, inspect the real environment.

Useful checks include:

```bash
wp option list --autoload=on
```

Option-size inspection, for example querying `wp_options` for large rows, should be used before claiming autoload or database pressure impact.

Object-cache metrics should be reviewed if a persistent object cache is active, because transient behavior differs materially between database-backed and object-cache-backed installs.

Also verify:

```php
get_option( 'acme_directory_last_payload' )
get_transient( 'acme_directory_cards' )
```

Confirm payload size, frequency of regeneration, cache hit rate, remote API latency, error rate, and whether this function runs during frontend render paths.

**Recommended Direction**

Use a bounded transient with an explicit TTL:

```php
set_transient( 'acme_directory_cards', $cards, HOUR_IN_SECONDS );
```

Avoid storing the full payload in an option unless there is a clear operational need. If keeping diagnostic data, store only metadata such as fetch timestamp, item count, checksum, or last error.

If a large payload must be persisted, make the storage decision explicit. Depending on needs, that may mean a non-autoloaded option, custom table, post/meta model, or cache-only storage.

Add invalidation on:

- directory settings update
- card import/update events
- manual refresh action
- upstream freshness/version change
- failed fetch recovery path

Add remote request protections:

- validate `api_url`
- set a short timeout
- check `is_wp_error()`
- validate HTTP status
- validate decoded JSON
- return stale cached data on fetch failure where acceptable
- avoid repeated failing fetches with a retry or circuit-breaker boundary

**Open Questions**

- Is `acme_directory_get_cards()` called during frontend rendering?
- How large can the card payload become?
- Is a persistent object cache enabled?
- What WordPress version is running?
- Does `acme_directory_last_payload` need the full payload, or would metadata be enough?
- What freshness SLA should directory cards follow?
- What events should invalidate the cache?