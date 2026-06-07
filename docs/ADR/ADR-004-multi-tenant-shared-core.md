Documentation > ADR > ADR-004 Multi-Tenant Shared Core

[Documentation Home](../README.md)
-> [Architecture](../ARCHITECTURE.md)
-> [ADRs](../index.md#adrs)
-> [Paraguay](../PARAGUAY/README.md)
-> [Diagrams](../diagrams/README.md)

# Title

ADR-004: Multi-Tenant Shared Core

## Status

Accepted

## Date

2026-06-07

## Context

The platform is intended to support multiple tenants in a shared Odoo environment. Fiscal documents, events, transmissions, attachments, API keys, Paraguay configuration records, and future country records must remain isolated by tenant.

The current implementation uses `fiscal.tenant` and user `allowed_fiscal_tenant_ids` to enforce tenant visibility through record rules. Admin users can see all records for operational support.

## Decision

Use a shared fiscal core with explicit tenant isolation rather than deploying a separate core per tenant.

Tenant isolation is enforced through:

* `tenant_id` on fiscal records
* tenant-aware record rules
* API key tenant resolution
* idempotency scoped by tenant
* country configuration scoped by tenant/company/environment where needed

## Consequences

* The same core workflow can serve multiple tenants and countries.
* SaaS-style deployment is simpler than maintaining separate codebases per tenant.
* All new fiscal and country-specific models must include tenant isolation when they store tenant data.
* Tests must cover cross-tenant access and idempotency behavior.
* Admin access remains powerful and must be audited where it affects locked fiscal documents.

## Alternatives Considered

* Separate database per tenant.
  * Deferred because the current platform is designed around shared Odoo modules and tenant-aware record rules.
* Separate addon per tenant.
  * Rejected because tenant behavior should be data/configuration, not code duplication.
* Trust application code without record rules.
  * Rejected because fiscal data requires defense-in-depth tenant isolation.

## Related ADRs

* [ADR-001: Country Addons](ADR-001-country-addons.md)
* [ADR-002: CDC as Country Identifier](ADR-002-cdc-country-identifier.md)
* [ADR-005: Fiscal Lock Policies](ADR-005-fiscal-lock-policies.md)

## Related Documents

* [Documentation Home](../README.md)
* [Documentation Index](../index.md)
* [Architecture](../ARCHITECTURE.md)
* [Roadmap](../ROADMAP.md)

## Next Recommended Reading

* [ADR-005 Fiscal Lock Policies](ADR-005-fiscal-lock-policies.md)
* [Architecture](../ARCHITECTURE.md)
