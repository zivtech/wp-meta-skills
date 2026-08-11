# Review target: Acme Theme Block Templates

Review this WordPress block theme's template-part registration with
`wordpress-theme-critic`. Report any issues you find, with a file and line
reference and a concrete fix for each. If the setup is sound, say so
explicitly and note what you checked.

**theme.json** (excerpt)

```json
{
	"$schema": "https://schemas.wp.org/trunk/theme.json",
	"version": 3,
	"templateParts": [
		{
			"name": "header",
			"title": "Header",
			"area": "header"
		},
		{
			"name": "footer",
			"title": "Footer",
			"area": "footer"
		}
	]
}
```

**templates/index.html**

```html
<!-- wp:template-part {"slug":"header","theme":"acme-theme","tagName":"header"} /-->

<!-- wp:group {"tagName":"main","layout":{"type":"constrained"}} -->
<main class="wp-block-group">
	<!-- wp:post-content /-->
</main>
<!-- /wp:group -->

<!-- wp:template-part {"slug":"footer","theme":"acme-theme","tagName":"footer"} /-->
```

**parts/footer.html**

```html
<!-- wp:group {"layout":{"type":"constrained"}} -->
<div class="wp-block-group">
	<!-- wp:paragraph -->
	<p>&copy; 2026 Acme Co. All rights reserved.</p>
	<!-- /wp:paragraph -->
</div>
<!-- /wp:group -->
```

## Scope

Static review of the files shown. Name any Site Editor or front-end check
that would still be needed to confirm an assessment either way. Do not claim
the exact rendered wrapper tag without loading the page, and do not claim
editorial content or accessibility issues beyond what the files show.
