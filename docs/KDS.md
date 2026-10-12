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

Active security controls:

* State-changing KDS routes use authenticated `auth="user"` routes with
  standard Odoo CSRF validation for the display workflow.
* The dedicated KDS user/manager groups and company/POS-config isolation are
  active.

Remaining production-hardening debt:

* A later production-clone exercise must verify interactions with any
  third-party POS addons and real multi-terminal traffic.
* A public domain, reverse proxy and HTTPS are deliberately deferred while the
  environment remains development/STAGING-only.
* A physical preparation printer has not yet been validated. The Epson ePOS
  simulator is test evidence, not a production printer.

## STAGING preparation-printer simulation

The repository includes `tools/epos_simulator` solely for development and
STAGING validation of Odoo's standard Epson ePOS preparation-printer flow. It
is independent of `kds_module`, stores a bounded set of protected test captures,
and must not be treated as a production printing service.

Use SSH port forwarding for both Odoo and the simulator. Opening Odoo through a
public IP and targeting a loopback printer is blocked by modern browser local
network protections. Do not expose the simulator port publicly. See the
simulator README for deployment, automated protocol checks, evidence review,
retention, and cleanup.

The validated STAGING behavior is deliberately parallel: a POS preparation
event reaches KDS and the native Odoo preparation printer independently.
Initial items, incremental additions and cancellations have been observed in
both channels. KDS automated tests cover quantity deltas, cancellation,
reconnect/replay and payment idempotency; the simulator tests cover only the
ePOS receiver and protected evidence viewer.

## Validated STAGING baseline

Baseline `kds-staging-v1` points to commit `e861c41`. It was closed on
2026-10-12 after deploying functional commit `2ad9a22`. The installed KDS
module version is `17.0.1.1.3` on Odoo 17 Community.

Verified in AWS STAGING:

* normal Restaurant POS order projection;
* quantity increments, reductions and cancellation deltas;
* replay/reconnect/payment idempotency and concurrent duplicate protection;
* scoped KDS workflow through `new`, `preparing`, `ready` and `done`;
* initial preparation notes, note-only updates and explicit note removal,
  without changing the projected product quantity;
* native preparation-printer output received by the protected Epson ePOS
  simulator in parallel with KDS;
* module upgrade over the existing STAGING database and successful registry,
  route, view and asset loading;
* a verified database-and-filestore backup and isolated restoration check.

The automated KDS suite completed with 41 post-tests / 49 checks and zero
failures or errors. The note scenario was also exercised interactively against
order `00001-010-0001`: initial note, updated note and removed note produced one
normal KDS projection plus two zero-quantity note-change projections, leaving
the active quantity at one.

A final post-baseline AWS smoke test created KDS order `#10`, line `#22`, from
Restaurant POS order `00001-010-0001`: one Café with note
`PRUEBA KDS AWS 12-OCT`. It appeared exactly once at source revision 4 and was
advanced visually through `new`, `preparing`, `ready` and `done`. The initial
browser reload had one transient `Failed to fetch`; the normal polling cycle
recovered automatically, the backend routes remained HTTP 200 and no duplicate
projection was created.

STAGING currently permits direct development access to Odoo on public port
`8069` for authorized testers. This is a temporary exception, not the target
production topology. Keep PostgreSQL and simulator port `9000` closed publicly;
use SSH tunnelling where practical. Before production, replace direct `8069`
access with a domain, reverse proxy and HTTPS.

STAGING backups are intentionally manual during active development. Take a
database-and-filestore backup before important deployments. The verified
2026-10-12 recovery point exists both on the EC2 host and as a private Mac copy;
scheduled retention/off-site automation is deferred until production planning.

This closes the KDS development/STAGING MVP. It does not certify production
readiness: physical printer validation, production-clone compatibility,
domain/HTTPS, production monitoring and production backup policy remain future
deployment work.
