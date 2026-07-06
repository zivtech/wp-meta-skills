**Scope**

Review target: `acme_directory_get_cards()` and its handling of WordPress options, transients, remote HTTP fetching, cache lifetime, and invalidation.

This review does **not** claim measured site-wide performance impact. That would require production traffic, object-cache behavior, database size, and autoload inspection data.

**WordPress-Specific Decisions**

- `set_transient( 'acme_directory_cards', $cards );` stores cached card data with no expiration.
  - That makes freshness entirely dependent on explicit invalidation.
  - No invalidation path is shown for card updates, settings changes, imports, API-side freshness windows, or manual cache clears.

- `update_option( 'acme_directory_last_payload', $cards );` stores the full payload as an option.
  - This is a growth risk if `$cards` can become large.
  - I am **not** claiming this option is autoloaded. Current WordPress behavior and the existing option row would need to be checked before making that claim.
  - The implementation should explicitly decide whether this data belongs in `wp_options` at all, and if so, whether autoload behavior should be controlled.

- `get_option( 'acme_directory_settings', array() )` assumes `api_url` exists.
  - Missing or malformed settings can produce notices or bad requests.
  - The API URL should be validated before use.

**Risks**

- **Render-time remote dependency:** On cache miss, rendering can block on `wp_remote_get()`. There is no timeout, no error handling, and no stale-cache fallback.

- **Transient is incomplete as a cache strategy:** A transient alone does not solve freshness or availability. Without an expiration, invalidation, and stale behavior, it can serve stale data indefinitely or stampede the remote API after deletion.

- **Large option pressure:** Persisting `$cards` into `acme_directory_last_payload` may add database and possibly autoload pressure depending on WordPress version, existing row state, and option metadata. The safer default is to avoid storing large payloads in options unless there is a clear operational need.

- **Invalid payload handling:** `json_decode()` may return `null` on invalid JSON, and the code stores that result without validation.

- **HTTP failure caching:** If the remote call fails or returns an error body, the function may cache or store invalid data.

**Verification**

Before claiming production impact, inspect actual data:

```bash
wp option list --autoload=on --fields=option_name,size_bytes
wp option get acme_directory_last_payload --format=json
wp transient get acme_directory_cards --format=json
```

Database-level inspection may also be useful in a non-production-safe read-only context:

```sql
SELECT option_name, autoload, LENGTH(option_value) AS bytes
FROM wp_options
WHERE option_name IN ('acme_directory_last_payload', '_transient_acme_directory_cards');
```

Also verify:

- WordPress version and `update_option()` behavior for new and existing options.
- Whether a persistent object cache is enabled.
- Object-cache hit/miss metrics for this transient.
- Remote API latency, error rate, and payload size.
- How often cards change and what event should invalidate the cache.

**Open Questions**

- Why is `acme_directory_last_payload` needed in addition to the transient?
- What is the expected maximum card payload size?
- Should cards expire after a fixed TTL, or only after explicit invalidation?
- What events update cards: admin edits, imports, webhooks, cron syncs, or remote API changes?
- Should stale data be served when the remote API fails?
- Is this function called during frontend rendering, REST responses, cron, or admin-only workflows?