Documentation > ADR > ADR-001 Country Addons

[Documentation Home](../README.md)
-> [Architecture](../ARCHITECTURE.md)
-> [ADRs](../index.md#adrs)
-> [Paraguay](../PARAGUAY/README.md)
-> [Diagrams](../diagrams/README.md)

# Title

ADR-001: Country Addons

## Status

Accepted

## Date

2026-06-07

## Context

The platform must support electronic invoicing requirements for multiple countries while keeping the fiscal core stable and country-neutral. Each country has its own fiscal concepts, regulatory vocabulary, authority integrations, document identifiers, numbering rules, payload formats, and future representation requirements.

The current implementation already follows this direction:

* `einvoice_module` contains the neutral fiscal workflow, documents, events, transmissions, attachments, lock policies, and orchestration.
* `fiscal_api` exposes the neutral API surface.
* `einvoice_py` contains Paraguay-specific concepts such as issuer, establishment, point of issue, timbrado, CSC, sequence, numbering, CDC, and Paraguay payload building.

## Decision

Country implementations are isolated in dedicated addons.

Examples:

* `einvoice_py`
* `einvoice_cr`
* `einvoice_ar`

## Consequences

* Country regulations can evolve independently without polluting the neutral fiscal core.
* Country-specific tests, views, models, adapters, and services can be released independently.
* Cross-country regression risk is reduced because Paraguay-specific behavior remains in `einvoice_py`.
* The core must expose stable extension points for adapters, attachments, events, and document lifecycle behavior.
* Some concepts may appear duplicated across countries, but duplication is acceptable until a truly country-neutral abstraction is proven.

## Alternatives Considered

* Put all country behavior directly in `einvoice_module`.
  * Rejected because it would couple the core to country-specific regulations and make future countries harder to maintain.
* Put all country behavior behind configuration only.
  * Rejected because fiscal rules often require country-specific models, services, validations, and workflows that are not cleanly represented by configuration alone.
* Create separate full applications per country.
  * Rejected because the platform needs a shared fiscal core, shared API, shared audit model, and shared tenant isolation model.

## Related ADRs

* [ADR-002: CDC as Country Identifier](ADR-002-cdc-country-identifier.md)
* [ADR-003: Payload Before XML](ADR-003-payload-before-xml.md)
* [ADR-004: Multi-Tenant Shared Core](ADR-004-multi-tenant-shared-core.md)
* [ADR-005: Fiscal Lock Policies](ADR-005-fiscal-lock-policies.md)

## Related Documents

* [Documentation Home](../README.md)
* [Documentation Index](../index.md)
* [Architecture](../ARCHITECTURE.md)

## Next Recommended Reading

* [ADR-004 Multi-Tenant Shared Core](ADR-004-multi-tenant-shared-core.md)
* [Paraguay Documentation](../PARAGUAY/README.md)
