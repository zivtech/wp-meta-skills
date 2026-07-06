# WordPress V1 Coverage Matrix

## Drupal-Equivalent Lifecycle Coverage

| Lifecycle Need | Drupal Analogue | WordPress V1 Surface |
|---|---|---|
| Main architecture planning | `drupal-planner` | `/wordpress-planner` |
| Content model planning | `drupal-planner.content-model` | `/wordpress-planner.content-model` |
| Theme planning | `drupal-planner.theme` | `/wordpress-planner.theme` |
| Migration planning | `drupal-migration-planner` | `/wordpress-planner.migration` |
| Config/artifact generation | `drupal-config-executor` | `/wordpress-blueprint-executor`, `/wordpress-plugin-executor`, `/wordpress-block-executor`, `/wordpress-theme-executor` |
| General review | `drupal-critic` | `/wordpress-critic` |
| Theme review | `drupal-theme-critic` | `/wordpress-theme-critic` |
| Security/performance focused review | companion critics | `/wordpress-security-critic`, `/wordpress-performance-critic` |

## WordPress-Native Coverage

| Domain | Planner | Executor | Critic |
|---|---|---|---|
| Project triage and routing | `/wordpress-planner` | `/wordpress-blueprint-executor` for repro envs | `/wordpress-critic` |
| CPTs, taxonomies, meta, ACF | `/wordpress-planner.content-model` | `/wordpress-plugin-executor` or `/wordpress-theme-executor` | `/wordpress-critic` |
| Plugin architecture | `/wordpress-planner.plugin` | `/wordpress-plugin-executor` | `/wordpress-security-critic`, `/wordpress-critic` |
| Block Editor blocks | `/wordpress-planner.block` | `/wordpress-block-executor` | `/wordpress-critic`, `/wordpress-performance-critic` |
| Block themes/theme.json | `/wordpress-planner.theme` | `/wordpress-theme-executor` | `/wordpress-theme-critic` |
| REST, Abilities, Interactivity APIs | `/wordpress-planner.plugin`, `/wordpress-planner.block` | `/wordpress-plugin-executor`, `/wordpress-block-executor` | `/wordpress-security-critic`, `/wordpress-performance-critic` |
| Performance and operations | `/wordpress-planner` | `/wordpress-blueprint-executor` for repro | `/wordpress-performance-critic` |
| Migration/page-builder conversion | `/wordpress-planner.migration` | `/wordpress-plugin-executor` or external migration tooling packet | `/wordpress-critic` |
| Release/plugin directory readiness | `/wordpress-planner.plugin` | `/wordpress-plugin-executor` | `/wordpress-security-critic`, `/wordpress-critic` |

## Known V1 Limits

- No dedicated WooCommerce critic yet; route WooCommerce work through `/wordpress-planner.plugin`, `/wordpress-security-critic`, and `/wordpress-performance-critic`.
- No dedicated accessibility critic yet; route frontend accessibility-heavy work through existing `a11y-critic` plus `/wordpress-theme-critic`.
- No live WP-CLI or Playground runner is bundled; executors produce packets and verification commands.
