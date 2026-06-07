Documentation > ADR > ADR-007 Fiscal Attachments

[Documentation Home](../README.md)
-> [Architecture](../ARCHITECTURE.md)
-> [ADRs](../index.md#adrs)
-> [Paraguay](../PARAGUAY/README.md)
-> [Diagrams](../diagrams/README.md)

# Title

ADR-007: Fiscal Attachments

## Status

Accepted

## Date

2026-06-07

## Context

Fiscal processing requires auditability. The platform needs to retain important generated and received artifacts without exposing internal records through the API. Current artifacts include canonical API request JSON, adapter response JSON, and Paraguay payload JSON.

Attachments are represented by `fiscal.attachment` and can link to `ir.attachment` for stored content.

## Decision

Persist fiscal artifacts as `fiscal.attachment` records linked to the fiscal document and tenant.

JSON payloads are stored as sensitive `ir.attachment` records through `fiscal.attachment`, with SHA-256 hashes populated for audit/debug purposes.

## Consequences

* Payloads and responses are available for audit and debugging.
* The API does not expose attachments by default.
* Attachment records inherit tenant isolation through their document.
* Country addons can extend attachment types for country-specific artifacts.
* Future download/delivery features must enforce tenant access and avoid exposing raw internal IDs.

## Alternatives Considered

* Store payloads only in text fields.
  * Rejected because attachments are a better fit for generated artifacts and future file formats.
* Store only final XML/PDF artifacts.
  * Rejected because intermediate canonical and payload artifacts are important for debugging.
* Expose attachments immediately through public URLs.
  * Rejected because fiscal payloads can contain sensitive data.

## Related ADRs

* [ADR-003: Payload Before XML](ADR-003-payload-before-xml.md)
* [ADR-004: Multi-Tenant Shared Core](ADR-004-multi-tenant-shared-core.md)
* [ADR-006: API Processing Modes](ADR-006-api-processing-modes.md)

## Related Documents

* [Documentation Home](../README.md)
* [Documentation Index](../index.md)
* [Architecture](../ARCHITECTURE.md)
* [Paraguay Documentation](../PARAGUAY/README.md)

## Next Recommended Reading

* [ADR-003 Payload Before XML](ADR-003-payload-before-xml.md)
* [Paraguay Documentation](../PARAGUAY/README.md)
