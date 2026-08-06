# e-Invoice Platform Documentation

[Documentation Home](README.md)
-> [Architecture](ARCHITECTURE.md)
-> [ADRs](index.md#adrs)
-> [Paraguay](PARAGUAY/README.md)
-> [Diagrams](diagrams/README.md)

## Project Overview

The e-Invoice Platform is a multi-tenant electronic invoicing platform built on Odoo.

It is organized around a country-neutral fiscal core, country-specific addons, API-first integration, tenant isolation, auditability, and an adapter pattern for future tax authority integrations.

Current country implementation:

* Paraguay through `einvoice_py`. The first controlled synchronous DE was
  accepted by SIFEN TEST with authority code `0260` on 2026-08-06. This proves
  TEST interoperability for the validated invoice profile; it is not production
  authorization or completion of the full homologation matrix.

## Documentation Map

* [Documentation Index](index.md): table of contents for the documentation portal
* [Architecture](ARCHITECTURE.md): modules, decisions, and processing flow
* [Roadmap](ROADMAP.md): completed, in-progress, next, and future work
* [ADRs](ADR/ADR-001-country-addons.md): architectural decision records
* [Paraguay Documentation](PARAGUAY/README.md): Paraguay-specific configuration and processing
* [SIFEN TEST Configuration](PARAGUAY/CONFIGURATION.md): authoritative field and secret-reference checklist
* [Homologation Runbook](PARAGUAY/HOMOLOGATION_RUNBOOK.md): controlled first-live-submission procedure
* [SIFEN TEST Homologation Matrix](PARAGUAY/HOMOLOGATION_MATRIX.md): official minimum scope and repository capability
* [Diagrams](diagrams/README.md): Mermaid diagrams for architecture and workflows

## How To Read This Documentation

### New Developers

1. Start with this page.
2. Read the [Documentation Index](index.md).
3. Read [Architecture](ARCHITECTURE.md).
4. Review the [Fiscal State Machine](diagrams/fiscal-state-machine.mmd).
5. Read [Paraguay Documentation](PARAGUAY/README.md) if working on Paraguay features.

### Architects

1. Read [Architecture](ARCHITECTURE.md).
2. Review all [ADRs](ADR/ADR-001-country-addons.md), especially:
   * [ADR-001 Country Addons](ADR/ADR-001-country-addons.md)
   * [ADR-004 Multi-Tenant Shared Core](ADR/ADR-004-multi-tenant-shared-core.md)
   * [ADR-007 Fiscal Attachments](ADR/ADR-007-fiscal-attachments.md)
3. Review [Architecture Diagram](diagrams/architecture.mmd).
4. Review [Roadmap](ROADMAP.md).

### Product Owners

1. Read [Project Overview](#project-overview).
2. Read [Current Implementation Status](#current-implementation-status).
3. Review [Roadmap](ROADMAP.md).
4. Review [Paraguay Documentation](PARAGUAY/README.md) for country scope.

### Country Implementation Developers

1. Read [ADR-001 Country Addons](ADR/ADR-001-country-addons.md).
2. Read [Paraguay Documentation](PARAGUAY/README.md).
3. Review [ADR-008 Paraguay Numbering Before CDC](ADR/ADR-008-paraguay-numbering-before-cdc.md).
4. Review [ADR-009 CSC Only For QR](ADR/ADR-009-csc-only-for-qr.md).
5. Review [Paraguay Processing Diagram](diagrams/paraguay-processing.mmd).

## Quick Links

### Core

* [Architecture](ARCHITECTURE.md)
* [Roadmap](ROADMAP.md)
* [Architecture Diagram](diagrams/architecture.mmd)
* [Credential Flow](diagrams/credential-flow.mmd)
* [Response Classification](diagrams/response-classification.mmd)
* [Homologation State](diagrams/homologation-state.mmd)
* [Workflow Diagram](diagrams/workflow.mmd)
* [Fiscal State Machine](diagrams/fiscal-state-machine.mmd)

### ADRs

* [ADR-001 Country Addons](ADR/ADR-001-country-addons.md)
* [ADR-002 CDC as Country Identifier](ADR/ADR-002-cdc-country-identifier.md)
* [ADR-003 Payload Before XML](ADR/ADR-003-payload-before-xml.md)
* [ADR-004 Multi-Tenant Shared Core](ADR/ADR-004-multi-tenant-shared-core.md)
* [ADR-005 Fiscal Lock Policies](ADR/ADR-005-fiscal-lock-policies.md)
* [ADR-006 API Processing Modes](ADR/ADR-006-api-processing-modes.md)
* [ADR-007 Fiscal Attachments](ADR/ADR-007-fiscal-attachments.md)
* [ADR-008 Paraguay Numbering Before CDC](ADR/ADR-008-paraguay-numbering-before-cdc.md)
* [ADR-009 CSC Only For QR](ADR/ADR-009-csc-only-for-qr.md)
* [ADR-010 SIFEN XSD Validation Strategy](ADR/ADR-010-sifen-xsd-validation-strategy.md)
* [ADR-011 Paraguay Digital Signature Strategy](ADR/ADR-011-paraguay-digital-signature-strategy.md)
* [ADR-012 Paraguay Qualified Certificate Lifecycle](ADR/ADR-012-paraguay-qualified-certificate-lifecycle.md)
* [ADR-013 SIFEN Submission Boundaries](ADR/ADR-013-sifen-submission-boundaries.md)
* [ADR-014 Paraguay TEST Timbrado Profile](ADR/ADR-014-paraguay-test-timbrado-profile.md)

### Paraguay

* [Paraguay Documentation](PARAGUAY/README.md)
* [SIFEN TEST Configuration](PARAGUAY/CONFIGURATION.md)
* [Homologation Runbook](PARAGUAY/HOMOLOGATION_RUNBOOK.md)
* [Paraguay Processing Diagram](diagrams/paraguay-processing.mmd)

## Current Implementation Status

Implemented:

* Core fiscal workflow
* Fiscal events and audit trail
* Fiscal attachments
* Retry processing
* Fiscal lock policies
* API
* API status endpoint
* API sync processing with timeout fallback
* Idempotency
* Tenant isolation
* Paraguay issuer configuration
* Paraguay establishment configuration
* Paraguay point of issue configuration
* Paraguay timbrado configuration
* Paraguay CSC configuration
* Paraguay sequence configuration
* Paraguay numbering
* Paraguay CDC generation
* Paraguay normalized payload builder
* SIFEN v150 unsigned XML, CDC-backed `DE@Id`, and XMLDSig
* QR payload and `gCamFuFD`
* final `rDE` assembly and local official XSD validation
* SOAP 1.2 envelope and TEST mTLS client
* `SiRecepDE` response parsing
* TEST-only Consulta DE reconciliation
* isolated TEST end-to-end submission composition
* offline qualified-certificate installation and readiness validation
* first accepted real SIFEN TEST synchronous DE (`0260`)
* deterministic invoice KuDE/PDF from persisted payload and exact QR artifacts

Operationally pending:

* completion of the official TEST homologation case matrix
* production credential, CSC, timbrado, endpoint, and operational approval
* Stage 8.24B durable pre-POST persistence, postponed until homologation evidence requires it
* production enablement and electronic timbrado workflow
* KuDE delivery and representations for additional Paraguay DTE types
* Delivery by email or WhatsApp

## Diagrams

* [Architecture Diagram](diagrams/architecture.mmd)
* [Workflow Diagram](diagrams/workflow.mmd)
* [Fiscal State Machine](diagrams/fiscal-state-machine.mmd)
* [Paraguay Processing Diagram](diagrams/paraguay-processing.mmd)

## Related Documents

* [Documentation Index](index.md)
* [Architecture](ARCHITECTURE.md)
* [Roadmap](ROADMAP.md)
* [Paraguay Documentation](PARAGUAY/README.md)

## Next Recommended Reading

* [Documentation Index](index.md)
* [Architecture](ARCHITECTURE.md)
