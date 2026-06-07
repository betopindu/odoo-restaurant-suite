Documentation > ADR > ADR-008 Paraguay Numbering Before CDC

[Documentation Home](../README.md)
-> [Architecture](../ARCHITECTURE.md)
-> [ADRs](../index.md#adrs)
-> [Paraguay](../PARAGUAY/README.md)
-> [Diagrams](../diagrams/README.md)

# Title

ADR-008: Paraguay Numbering Before CDC

## Status

Accepted

## Date

2026-06-07

## Context

The Paraguay CDC is composed from multiple document and issuer fields, including establishment code, point of issue code, and the fiscal document number. Therefore, a Paraguay document cannot generate a real CDC until the fiscal number has been assigned.

The implemented Paraguay flow assigns a number from `fiscal.py.sequence` before CDC generation.

## Decision

Generate Paraguay fiscal numbering before CDC generation.

The sequence is scoped by:

* tenant
* company
* timbrado
* establishment
* point of issue
* document type

The assigned number is persisted as `py_document_number` and `py_full_number`.

## Consequences

* CDC generation has the required document number input.
* Numbering is stable across retries and is not reassigned once present.
* Sequences can be initialized manually for migration from existing numbering.
* Sequence locking is required during assignment to reduce duplicate number risk.
* Missing sequence configuration causes validation error before CDC generation.

## Alternatives Considered

* Generate CDC before numbering.
  * Rejected because CDC requires the document number.
* Use Odoo `ir.sequence` directly without Paraguay scope.
  * Rejected because Paraguay numbering depends on timbrado, establishment, point of issue, and document type.
* Assign a new number on every retry.
  * Rejected because retries must preserve fiscal identity.

## Related ADRs

* [ADR-001: Country Addons](ADR-001-country-addons.md)
* [ADR-002: CDC as Country Identifier](ADR-002-cdc-country-identifier.md)
* [ADR-009: CSC Only For QR](ADR-009-csc-only-for-qr.md)

## Related Documents

* [Documentation Home](../README.md)
* [Documentation Index](../index.md)
* [Architecture](../ARCHITECTURE.md)
* [Paraguay Documentation](../PARAGUAY/README.md)
* [Paraguay Processing Diagram](../diagrams/paraguay-processing.mmd)

## Next Recommended Reading

* [ADR-009 CSC Only For QR](ADR-009-csc-only-for-qr.md)
* [Paraguay Processing Diagram](../diagrams/paraguay-processing.mmd)
