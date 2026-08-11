# Documentation Index

[Documentation Home](README.md) -> Documentation Index

## Getting Started

Start here if you are new to the project or trying to understand what has already been implemented.

* [Documentation Home](README.md): project overview, reading paths, quick links, and implementation status.
* [Roadmap](ROADMAP.md): completed work, active documentation/product areas, next work, and future milestones.
* [Documentation Changelog](CHANGELOG.md): dated documentation baseline changes.
* [SIFEN TEST Configuration](PARAGUAY/CONFIGURATION.md): authoritative configuration and secret-reference checklist.
* [Homologation Runbook](PARAGUAY/HOMOLOGATION_RUNBOOK.md): controlled live TEST procedure.
* [SIFEN TEST Homologation Matrix](PARAGUAY/HOMOLOGATION_MATRIX.md): official minimum scope, repository capability, and authorization gates.

## Recommended Reading Paths

### New Developer

[README](README.md)
-> [Architecture](ARCHITECTURE.md)
-> [Roadmap](ROADMAP.md)
-> [ADRs](#adrs)
-> [Paraguay](PARAGUAY/README.md)

### Architect

[Architecture](ARCHITECTURE.md)
-> [ADRs](#adrs)
-> [Diagrams](diagrams/README.md)

### Country Implementation Developer

[Paraguay](PARAGUAY/README.md)
-> [ADR-008](ADR/ADR-008-paraguay-numbering-before-cdc.md)
-> [ADR-009](ADR/ADR-009-csc-only-for-qr.md)
-> [ADR-010](ADR/ADR-010-sifen-xsd-validation-strategy.md)
-> [Diagrams](diagrams/README.md)

### Product Owner

[README](README.md)
-> [Roadmap](ROADMAP.md)
-> [Paraguay](PARAGUAY/README.md)

## Architecture

Use this section to understand the module boundaries, processing flow, and design principles.

* [Architecture](ARCHITECTURE.md): core modules, country modules, architectural decisions, and processing flow.
* [Architecture Diagram](diagrams/architecture.mmd): high-level system flow.
* [Workflow Diagram](diagrams/workflow.mmd): simplified fiscal document workflow.
* [Fiscal State Machine](diagrams/fiscal-state-machine.mmd): detailed state transitions.

## Roadmap

Use this section to understand what is complete, what is next, and what is intentionally future work.

* [Roadmap](ROADMAP.md): completed, in-progress, next, and future work.

## ADRs

Use ADRs to understand why the platform is shaped the way it is.

* [ADR-001 Country Addons](ADR/ADR-001-country-addons.md): isolate country implementations in dedicated addons.
* [ADR-002 CDC as Country Identifier](ADR/ADR-002-cdc-country-identifier.md): store Paraguay CDC in the neutral `country_identifier`.
* [ADR-003 Payload Before XML](ADR/ADR-003-payload-before-xml.md): generate normalized payload before XML.
* [ADR-004 Multi-Tenant Shared Core](ADR/ADR-004-multi-tenant-shared-core.md): use a shared core with tenant isolation.
* [ADR-005 Fiscal Lock Policies](ADR/ADR-005-fiscal-lock-policies.md): configure document immutability by tenant policy.
* [ADR-006 API Processing Modes](ADR/ADR-006-api-processing-modes.md): support async and sync API processing.
* [ADR-007 Fiscal Attachments](ADR/ADR-007-fiscal-attachments.md): persist fiscal artifacts as attachments.
* [ADR-008 Paraguay Numbering Before CDC](ADR/ADR-008-paraguay-numbering-before-cdc.md): assign Paraguay number before CDC.
* [ADR-009 CSC Only For QR](ADR/ADR-009-csc-only-for-qr.md): use CSC for QR hashing, not CDC.
* [ADR-010 SIFEN XSD Validation Strategy](ADR/ADR-010-sifen-xsd-validation-strategy.md): distinguish pre-signature schema readiness from full official XSD validation.
* [ADR-011 Paraguay Digital Signature Strategy](ADR/ADR-011-paraguay-digital-signature-strategy.md): define SIFEN XMLDSig placement, credential boundaries, artifact handling, and signature-before-QR ordering.
* [ADR-012 Paraguay Qualified Certificate Lifecycle](ADR/ADR-012-paraguay-qualified-certificate-lifecycle.md): define qualified-certificate requirements, logical credential roles, provider-neutral PKCS#12 resolution, trust boundaries, and rotation.
* [ADR-013 SIFEN Submission Boundaries](ADR/ADR-013-sifen-submission-boundaries.md): separate local validation, transport, authority parsing, and isolated submission side effects.
* [ADR-014 Paraguay TEST Timbrado Profile](ADR/ADR-014-paraguay-test-timbrado-profile.md): separate TEST homologation configuration from production electronic timbrado.
* [ADR-015 Paraguay KuDE From Persisted Payload](ADR/ADR-015-paraguay-kude-from-persisted-payload.md): generate and version deterministic KuDE PDFs from persisted payload and exact QR artifacts.
* [ADR-016 Paraguay SIFEN Emitter Events](ADR/ADR-016-paraguay-sifen-emitter-events.md): isolate cancellation and number inutilization from DE submission.
* [ADR-017 SIFEN Durable Pre-POST Boundary](ADR/ADR-017-sifen-durable-pre-post-boundary.md): preserve outbound evidence independently of the caller transaction.
* [ADR-018 Odoo Invoice Fiscal Snapshot Boundary](ADR/ADR-018-account-move-fiscal-snapshot-boundary.md): convert posted accounting invoices into immutable neutral fiscal snapshots.

## Country Implementations

Use this section when working on country-specific fiscal logic.

* [Paraguay Documentation](PARAGUAY/README.md): complete implemented TEST pipeline and country rules.
* [SIFEN TEST Configuration](PARAGUAY/CONFIGURATION.md)
* [Homologation Runbook](PARAGUAY/HOMOLOGATION_RUNBOOK.md)

## Diagrams

Use this section when you need a visual map before reading code or ADRs.

* [Diagrams Hub](diagrams/README.md): diagram descriptions, purpose, and related documentation.
* [Architecture Diagram](diagrams/architecture.mmd)
* [Workflow Diagram](diagrams/workflow.mmd)
* [Fiscal State Machine](diagrams/fiscal-state-machine.mmd)
* [Paraguay Processing Diagram](diagrams/paraguay-processing.mmd)
* [Credential Flow](diagrams/credential-flow.mmd)
* [Response Classification](diagrams/response-classification.mmd)
* [Homologation State](diagrams/homologation-state.mmd)

## Related Documents

* [Documentation Home](README.md)
* [Architecture](ARCHITECTURE.md)
* [Roadmap](ROADMAP.md)
* [Paraguay Documentation](PARAGUAY/README.md)

## Next Recommended Reading

* [Architecture](ARCHITECTURE.md)
* [Diagrams Hub](diagrams/README.md)
