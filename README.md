# Odoo Restaurant Suite

Odoo 17 Community project combining Restaurant POS/KDS and a country-neutral
electronic-invoicing platform with the Paraguay SIFEN implementation.

## Current validated baselines

### Restaurant KDS

* AWS STAGING baseline: tag `kds-staging-v1`, commit `e861c41`.
* Installed addon: `kds_module` `17.0.1.1.3`.
* Validated with Restaurant POS orders, quantity deltas, cancellations,
  replay/reconnect/payment idempotency, preparation notes and the complete
  `new -> preparing -> ready -> done` workflow.
* Odoo's native preparation-printer output was validated with the separate
  STAGING-only Epson ePOS simulator. A physical printer has not yet been tested.
* The latest AWS smoke test used KDS order `#10` / line `#22`: one Café with
  note `PRUEBA KDS AWS 12-OCT`, projected exactly once and completed in `done`.

This is a development/STAGING milestone, not production authorization. A
production clone, real multi-terminal traffic, physical printer, public domain,
reverse proxy, HTTPS, monitoring and production backup policy remain pending.

### Paraguay e-Invoice

The synchronous FE MVP is closed end-to-end for the exercised TEST profiles:

* live B2C and B2B SIFEN TEST acceptance (`0260`);
* posted `account.move` to neutral `fiscal.document` snapshot;
* operator-controlled readiness, submission, manual retry and Consulta DE;
* durable pre-POST evidence, artifact provenance and conservative recovery;
* XML v150, XMLDSig, QR, XSD, SOAP 1.2 and mTLS;
* authoritative accepted KuDE/XML delivery.

Production operation is not ready. NCE/NDE are complete offline but still need
live TEST validation; asynchronous batches, Consulta RUC, received-DTE flows
and completion/live validation of fiscal events remain future work.

## Addons

* `custom_addons/kds_module`: Restaurant Kitchen Display System.
* `custom_addons/fiscal_api`: country-neutral fiscal core/API boundary.
* `custom_addons/einvoice_module`: shared electronic-invoicing integration.
* `custom_addons/einvoice_py`: Paraguay SIFEN implementation.

## Documentation

* [Documentation index](docs/README.md)
* [KDS operational notes](docs/KDS.md)
* [Paraguay documentation](docs/PARAGUAY/README.md)
* [Architecture](docs/ARCHITECTURE.md)
* [Roadmap](docs/ROADMAP.md)
* [Changelog](docs/CHANGELOG.md)

The Epson simulator under `tools/epos_simulator` is temporary test
infrastructure and is not part of the production KDS runtime.
