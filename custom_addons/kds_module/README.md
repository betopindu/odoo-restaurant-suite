# Restaurant KDS

Odoo 17 Community addon for the existing Restaurant KDS screen and workflow.

## Production-staging controls

- POS persistence remains authoritative. KDS projects the persisted
  `pos.order.last_order_preparation_change` snapshot after `create_from_ui`.
- A database-unique projection ledger keyed by POS order and canonical source
  hash makes reconnect, payment resend, and concurrent delivery idempotent.
- The POS row is locked while deltas are calculated. KDS writes run in a
  savepoint, so partial projections roll back without losing a successful POS
  response.
- Failed projections remain auditable and can be explicitly recovered by a KDS
  manager with `kitchen.order.projection.action_recover()`. There is no
  automatic historical backfill.
- `KDS User / Kitchen Operator` can view and advance kitchen work. `KDS Manager`
  administers KDS records and failed recovery. Company record rules and POS
  configuration checks apply.
- Mutable display routes use Odoo session authentication and standard CSRF.

## Staging checklist

Install or upgrade only `kds_module` after taking a database backup. Validate an
existing Restaurant POS with an initial order, quantity increase, reduction,
payment/resend, reconnect, multiple terminals/configurations, workflow through
the delivered lane, browser polling and sound, then inject and recover one KDS
projection failure. Confirm other custom `create_from_ui` overrides call
`super()` and do not reorder persisted preparation state.

Uninstall is not a complete rollback because it discards KDS audit/history.
Prefer restoring the pre-install database backup if staging validation fails.
