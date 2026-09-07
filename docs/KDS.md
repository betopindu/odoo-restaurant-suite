# KDS Operational Notes

[Documentation Home](README.md) -> KDS

## Scope

`kds_module` is an Odoo 17 Restaurant KDS addon for databases that already run
Point of Sale Restaurant.

It depends on:

* `point_of_sale`
* `pos_restaurant`

If both modules are already installed, Odoo reuses them when `kds_module` is
installed. POS and Restaurant do not need to be reinstalled or upgraded solely
for KDS.

## Existing POS Installation Behavior

Installing `kds_module` adds KDS models, views, assets, a sequence, a KDS cron,
and KDS configuration fields on existing `pos.config` records. It does not
rewrite historical `pos.order` rows and does not create historical
`kitchen.order` records.

KDS starts from future POS Restaurant synchronizations that include
`last_order_preparation_change`. Existing historical orders are not backfilled.

## Preparation Event Identity

The cumulative preparation snapshot is content, not event identity. In an
`A -> B -> A` sequence, the final snapshot has the same hash as the initial
snapshot but represents a new transition that must produce a cancellation.

The POS therefore persists an invisible monotonic `kds_preparation_revision`
only when Odoo's native `changesToOrder()` reports new or cancelled quantities.
The projection ledger uses `(pos_order_id, source_revision)` for event
idempotency and retains `source_hash` to verify that a revision is never reused
with different content. Offline storage, reconnect, draft sync and payment
resend retain the same revision, while a later valid return to an earlier
snapshot receives a new revision.

Upgrading `kds_module` adds the revision columns and replaces the historical
`(pos_order_id, source_hash)` constraint. Existing projection records keep a
null revision and remain readable and hash-idempotent. The upgrade assigns no
synthetic revision and deletes no history.

## POS Configuration Isolation

The KDS screen should be opened with:

```text
/kitchen/display?config_id=<POS_CONFIG_ID>
```

Display, grid refresh, line transitions, and order state moves are scoped to the
selected `pos.config`. Cross-config and cross-company mutations are rejected by
the HTTP controllers; browser-provided kitchen line/order IDs are not sufficient
on their own.

## Delivered Lane

The Delivered lane is controlled by `pos.config.kds_show_done_lane`.

Default: disabled.

When enabled for a POS config, delivered KDS lines remain visible according to
that config's done-lane visibility window.

## Installation Procedure

Recommended staging and production procedure:

1. Back up database and filestore.
2. Validate first on a staging clone of production.
3. Deploy the `kds_module` code.
4. Restart Odoo workers.
5. Update the Apps list.
6. Confirm `point_of_sale` and `pos_restaurant` are already installed.
7. Install only `kds_module`.
8. Install outside operating hours with POS sessions closed.
9. Reopen or reload POS clients after installation.
10. Open an existing Restaurant POS config and confirm KDS fields.
11. Create a controlled POS Restaurant order and verify one KDS order appears.
12. Resend/synchronize the same order and verify no duplicate KDS quantity.
13. Increase quantity and verify only the delta appears.
14. Reduce to the original quantity and verify one cancellation change appears.
15. Replay that revision and verify no duplicate cancellation appears.
16. Pay/finalize and verify no duplicate KDS order appears.
17. Verify multi-POS isolation if more than one POS config exists.

Rollback is the normal Odoo rollback: restore the pre-install database,
filestore, and code deployment.

## Production Notes

KDS extends `pos.order.create_from_ui()` after the POS order creation result is
returned by Odoo. The KDS post-processing is isolated: if KDS synchronization
fails after POS has created the order, the original POS result is preserved and
the KDS failure is logged for operators.

The KDS cron touches only `kitchen.order` records and updates KDS admin
visibility flags. It does not mutate POS orders, POS sessions, stock, taxes,
payments, or receipts.

Remaining production-hardening debt:

* KDS ACLs are intentionally broad for internal users.
* State-changing KDS routes use authenticated `auth="user"` routes with
  standard Odoo CSRF validation for the display workflow.
* Staging must verify the actual production POS Restaurant workflow, browser
  reload behavior, and multi-terminal synchronization.
