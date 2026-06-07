Documentation > ADR > ADR-002 CDC as Country Identifier

[Documentation Home](../README.md)
-> [Architecture](../ARCHITECTURE.md)
-> [ADRs](../index.md#adrs)
-> [Paraguay](../PARAGUAY/README.md)
-> [Diagrams](../diagrams/README.md)

# Title

ADR-002: CDC as Country Identifier

## Status

Accepted

## Date

2026-06-07

## Context

The neutral core model `fiscal.document` includes `country_identifier` as the country-specific fiscal identifier. Paraguay uses the CDC as its official fiscal document identifier. The CDC is generated inside `einvoice_py` from Paraguay-specific data such as issuer RUC, establishment, point of issue, document number, emission date, emission type, and security code.

The core should not know the structure or generation algorithm of Paraguay CDC. At the same time, API responses and status views need a neutral place to expose the country-specific fiscal identifier.

## Decision

For Paraguay documents, store the generated CDC in `fiscal.document.country_identifier`.

The Paraguay-specific fields remain in `einvoice_py`, including:

* `py_cdc`
* `py_cdc_base`
* `py_cdc_dv`
* `py_cod_seg`

## Consequences

* The core remains country-neutral while still exposing a standard fiscal identifier field.
* API clients can read `country_identifier` without knowing each country's internal field names.
* Paraguay-specific CDC details remain available for audit/debug through `einvoice_py` fields.
* Future country addons can store their own official identifiers in the same neutral field.
* The system must ensure `country_identifier` is updated only through controlled country processing, not arbitrary user edits.

## Alternatives Considered

* Add a generic `cdc` field to the core.
  * Rejected because CDC is Paraguay-specific and would pollute the country-neutral core.
* Expose only `py_cdc` and leave `country_identifier` empty.
  * Rejected because API/status consumers need a neutral identifier field.
* Store CDC only inside payload attachments.
  * Rejected because CDC is central to document identity and must be queryable on the fiscal document.

## Related ADRs

* [ADR-001: Country Addons](ADR-001-country-addons.md)
* [ADR-003: Payload Before XML](ADR-003-payload-before-xml.md)
* [ADR-004: Multi-Tenant Shared Core](ADR-004-multi-tenant-shared-core.md)

## Related Documents

* [Documentation Home](../README.md)
* [Documentation Index](../index.md)
* [Architecture](../ARCHITECTURE.md)
* [Paraguay Documentation](../PARAGUAY/README.md)

## Next Recommended Reading

* [ADR-008 Paraguay Numbering Before CDC](ADR-008-paraguay-numbering-before-cdc.md)
* [Paraguay Documentation](../PARAGUAY/README.md)
