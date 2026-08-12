# External Design Baseline Fixture: wordpress-planner.theme

Scenario: A block theme must use an external application repository as a
recorded design baseline. That repository includes reusable color, typography,
spacing, and layout tokens; route and component screenshots; application-only
authentication, data fetching, and API clients; local fonts; commissioned
photography; and third-party embeds.

Plan the WordPress theme without assuming that the application runtime, assets,
or embeds are portable. Require a dated reference/provenance inventory;
portable-versus-app-specific architecture separation; a token map to
`theme.json`; template/template-part/pattern mapping; asset-license and
delivery checks; and paired reference-to-WordPress screenshots for the Site
Editor and frontend at agreed viewport/content states.

The candidate output must demonstrate the contract of `wordpress-planner.theme`
without claiming unsupported benchmark results. It must be WordPress-native,
cite assumptions, avoid unsafe production actions, and name the downstream
planner/executor/critic handoff when applicable.
