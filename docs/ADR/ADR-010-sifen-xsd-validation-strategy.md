Documentation > ADR > ADR-010 SIFEN XSD Validation Strategy

[Documentation Home](../README.md)
-> [Architecture](../ARCHITECTURE.md)
-> [ADRs](../index.md#adrs)
-> [Paraguay](../PARAGUAY/README.md)
-> [Diagrams](../diagrams/README.md)

# Title

ADR-010: SIFEN XSD Validation Strategy

## Status

Accepted

## Date

2026-06-08

## Context

The Paraguay addon now generates an unsigned SIFEN-oriented XML draft through `PyUnsignedXmlBuilder`.

Stage 6.5.1 aligned that draft closer to the official SIFEN structure by adding the official namespace, schema location, `gOpeDE`, improved document groups, SIFEN-oriented item value structure, VAT structure, and totals.

However, full official `siRecepDE_v150.xsd` validation is not only a structural XML problem. The official `rDE` schema also requires fields and groups that belong to later stages, especially digital signature and QR generation.

Full official validation requires:

* `dFecFirma`
* `ds:Signature`
* `gCamFuFD/dCarQR`

Those are intentionally outside the current unsigned XML draft stage.

## Decision

Official SIFEN XSD files should be pinned locally in the repository in a future implementation stage. They should not be downloaded at runtime.

The planned local location is:

```text
custom_addons/einvoice_py/xsd/sifen/v150/
```

The planned structure is:

```text
custom_addons/einvoice_py/xsd/sifen/v150/
├── README.md
├── manifest.json
└── schemas/
    └── *.xsd
```

The `manifest.json` file should record the schema family, country, version, root schema, official source URL, download date, SHA-256 checksums, dependency map, and runtime download policy.

Only official DNIT/SIFEN/e-Kuatia source packages or files should be used. GitHub repositories, random mirrors, and copied third-party schema bundles should not be treated as authoritative sources.

Future XSD loader code should resolve `xs:import` and `xs:include` locally from the pinned directory and forbid network access.

The unsigned XML remains a draft artifact and is not expected to pass full `siRecepDE_v150.xsd` validation.

Stage 6.5.x will focus on pre-signature schema readiness:

* structural alignment
* official enum descriptions
* field ordering
* payload and model gap closure
* a partial validation harness if useful

True full XSD-valid SIFEN XML is only expected after the digital signature and QR stages.

Stage 6.5.3 implements that partial validation harness as `PyXmlValidationService`. It validates project-owned pre-signature readiness rules for unsigned XML and explicitly rejects signing/QR-stage elements. It is not official XSD validation and does not vendor SIFEN XSD files.

Stage 6.5.5 adds `PyXsdValidationService` as infrastructure for future locally pinned SIFEN assets. It can locate the planned local XSD directory, load and validate a future manifest, resolve root schema paths safely, compile schemas with `lxml`, and validate XML once official assets exist. Because no XSD files are vendored yet, missing assets fail clearly. It does not perform official XSD validation yet.

## Consequences

* The project avoids runtime dependency on DNIT/e-Kuatia schema availability.
* Schema validation can be deterministic once official XSD files are pinned.
* The current unsigned XML attachment remains useful for audit, debugging, and pre-signature development.
* Full `rDE` validation must wait until signature and QR output exist.
* Documentation and tests should distinguish pre-signature readiness from full official XSD validation.
* Future implementation should record source URLs, download date, and checksums for pinned XSD files.
* The future XSD loader must resolve imports/includes locally and fail closed if a schema attempts network access.
* Before real XSD files are vendored, the loader should add a local-only resolver for `xs:include` and `xs:import`, enforce `runtime_downloads_allowed = false`, and validate manifest file entries, checksums, and dependency map structure.

## Alternatives Considered

* Download XSD files at runtime.
  * Rejected because it creates external availability risk and makes validation non-deterministic.
* Expect the unsigned XML draft to pass full `siRecepDE_v150.xsd`.
  * Rejected because full `rDE` validation requires signature and QR groups that are intentionally future work.
* Skip XSD validation until SIFEN submission.
  * Rejected because pre-signature schema readiness can catch mapping, enum, ordering, and payload gaps earlier.
* Vendor schemas immediately.
  * Deferred because this ADR defines strategy only; schema pinning and validation implementation belong to a later stage.

## Related ADRs

* [ADR-001: Country Addons](ADR-001-country-addons.md)
* [ADR-003: Payload Before XML](ADR-003-payload-before-xml.md)
* [ADR-007: Fiscal Attachments](ADR-007-fiscal-attachments.md)
* [ADR-008: Paraguay Numbering Before CDC](ADR-008-paraguay-numbering-before-cdc.md)
* [ADR-009: CSC Only For QR](ADR-009-csc-only-for-qr.md)

## Related Documents

* [Documentation Home](../README.md)
* [Documentation Index](../index.md)
* [Architecture](../ARCHITECTURE.md)
* [Roadmap](../ROADMAP.md)
* [Paraguay Documentation](../PARAGUAY/README.md)

## Next Recommended Reading

* [Paraguay Documentation](../PARAGUAY/README.md)
* [Roadmap](../ROADMAP.md)
* [Paraguay Processing Diagram](../diagrams/paraguay-processing.mmd)
