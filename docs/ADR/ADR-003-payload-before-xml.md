Documentation > ADR > ADR-003 Payload Before XML

[Documentation Home](../README.md)
-> [Architecture](../ARCHITECTURE.md)
-> [ADRs](../index.md#adrs)
-> [Paraguay](../PARAGUAY/README.md)
-> [Diagrams](../diagrams/README.md)

# Title

ADR-003: Payload Before XML

## Status

Accepted

## Date

2026-06-07

## Context

Paraguay processing requires a future SIFEN XML document, digital signature, QR generation, and authority submission. Before implementing XML, the project needs a normalized representation of the country-specific fiscal data gathered from the document, issuer, establishment, point of issue, timbrado, numbering, CDC, receiver, items, totals, and fiscal defaults.

The current `einvoice_py` implementation generates a normalized Paraguay payload dictionary and persists it as a sensitive fiscal attachment of type `paraguay_payload_json`.

## Decision

Generate and persist a normalized country payload before XML generation.

For Paraguay, `PyPayloadBuilder` returns a Python dictionary with sections such as:

* `document`
* `operation`
* `issuer`
* `receiver`
* `condition`
* `items`
* `totals`
* `paraguay`
* `warnings`

## Consequences

* XML generation can be implemented later as a deterministic transformation from a normalized payload.
* The payload is auditable before signing/submission features exist.
* Missing optional data can be captured as warnings without blocking early processing.
* Tests can validate country data normalization without requiring XML, signing, or SIFEN connectivity.
* Payload schema evolution must be handled carefully once XML generation depends on it.

## Alternatives Considered

* Build XML directly from `fiscal.document`.
  * Rejected because it would mix extraction, defaults, validation, XML structure, and country logic in one step.
* Store only XML and skip a normalized payload.
  * Rejected because XML is not implemented yet and normalized payloads are easier to test and audit.
* Keep payload only in memory.
  * Rejected because fiscal processing requires auditability and reproducibility.

## Related ADRs

* [ADR-001: Country Addons](ADR-001-country-addons.md)
* [ADR-002: CDC as Country Identifier](ADR-002-cdc-country-identifier.md)
* [ADR-004: Multi-Tenant Shared Core](ADR-004-multi-tenant-shared-core.md)

## Related Documents

* [Documentation Home](../README.md)
* [Documentation Index](../index.md)
* [Architecture](../ARCHITECTURE.md)
* [Paraguay Documentation](../PARAGUAY/README.md)

## Next Recommended Reading

* [ADR-007 Fiscal Attachments](ADR-007-fiscal-attachments.md)
* [Paraguay Documentation](../PARAGUAY/README.md)
