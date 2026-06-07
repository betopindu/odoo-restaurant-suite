Documentation > ADR > ADR-005 Fiscal Lock Policies

[Documentation Home](../README.md)
-> [Architecture](../ARCHITECTURE.md)
-> [ADRs](../index.md#adrs)
-> [Paraguay](../PARAGUAY/README.md)
-> [Diagrams](../diagrams/README.md)

# Title

ADR-005: Fiscal Lock Policies

## Status

Accepted

## Date

2026-06-07

## Context

Fiscal documents become sensitive after certain workflow states. Some states should be immutable to normal users to preserve auditability and prevent accidental changes after submission, acceptance, final failure, cancellation, or manual review.

The project originally used hardcoded locked states, then introduced tenant-level lock policies so each tenant can configure which fiscal states are locked while preserving the default behavior.

## Decision

Use configurable fiscal document lock policies at the tenant level.

Default locked states remain:

* `submitted`
* `accepted`
* `cancelled`
* `failed_final`
* `manual_review`

`validation_error` remains editable so users can correct data and retry validation.

Admin override can be allowed or disabled by policy. When allowed, admin edits to locked documents create audit events.

## Consequences

* Existing behavior is preserved when a tenant has no explicit lock policy.
* Tenants can adapt immutability rules without code changes.
* Manual review resolution remains controlled through explicit actions.
* Admin override behavior is auditable.
* Orchestrator/system transitions can continue using controlled bypass context.
* Lock policy changes must be tested carefully because they affect fiscal document mutability.

## Alternatives Considered

* Keep locked states hardcoded forever.
  * Rejected because tenants and future country workflows may need different immutability rules.
* Allow all admin edits without audit.
  * Rejected because locked fiscal documents require traceability.
* Make every non-draft state immutable.
  * Rejected because `validation_error` must remain editable for correction and retry.
* Store lock policy per document.
  * Deferred because tenant-level policy is sufficient for the current MVP.

## Related ADRs

* [ADR-004: Multi-Tenant Shared Core](ADR-004-multi-tenant-shared-core.md)
* [ADR-001: Country Addons](ADR-001-country-addons.md)

## Related Documents

* [Documentation Home](../README.md)
* [Documentation Index](../index.md)
* [Architecture](../ARCHITECTURE.md)
* [Fiscal State Machine](../diagrams/fiscal-state-machine.mmd)

## Next Recommended Reading

* [Fiscal State Machine](../diagrams/fiscal-state-machine.mmd)
* [Roadmap](../ROADMAP.md)
