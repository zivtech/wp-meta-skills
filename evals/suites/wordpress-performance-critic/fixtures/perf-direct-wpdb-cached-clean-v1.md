# Review target: Acme Order Insights

Review this WordPress plugin file with `wordpress-performance-critic`. Report
any performance risks you find, with a `file:line` reference and a concrete
fix for each. If the code is sound, say so explicitly and note what you
checked.

```php
<?php
/**
 * Plugin Name: Acme Order Insights
 * Description: Summarize order totals per product for the insights dashboard widget.
 */

function acme_get_top_products_by_revenue( $limit = 10 ) {
	global $wpdb;

	$limit     = absint( $limit );
	$cache_key = 'acme_top_products_' . $limit;
	$rows      = wp_cache_get( $cache_key, 'acme_insights' );

	if ( false !== $rows ) {
		return $rows;
	}

	$rows = $wpdb->get_results(
		$wpdb->prepare(
			"SELECT oi.product_id, p.post_title AS product_name, SUM(oi.line_total) AS revenue
			 FROM {$wpdb->prefix}acme_order_items oi
			 INNER JOIN {$wpdb->posts} p ON p.ID = oi.product_id
			 WHERE oi.status = %s
			 GROUP BY oi.product_id, p.post_title
			 ORDER BY revenue DESC
			 LIMIT %d",
			'completed',
			$limit
		)
	);

	wp_cache_set( $cache_key, $rows, 'acme_insights', 5 * MINUTE_IN_SECONDS );

	return $rows;
}
```

## Scope

Static review of the code shown. Name any measurement (Query Monitor, a
slow-query log, or a cache hit-rate check) that would still be needed to
confirm an assessment either way. Do not claim production latency or
capacity impact without real traffic or database data.
