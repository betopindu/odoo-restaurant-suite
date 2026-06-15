# Architecture

[Documentation Home](README.md) -> Architecture

[Documentation Home](README.md)
-> [ADRs](index.md#adrs)
-> [Paraguay](PARAGUAY/README.md)
-> [Diagrams](diagrams/README.md)

## Overview

The e-Invoice Platform is built around a country-neutral fiscal core, country-specific addons, and an API-first integration layer.

The core owns common fiscal concepts such as document lifecycle, events, transmissions, attachments, tenant isolation, idempotency, lock policies, and orchestration.

Country addons own country-specific concepts such as numbering, fiscal identifiers, payloads, authority-specific configuration, and future XML/signing/authority integration.
Paraguay already includes an unsigned SIFEN-oriented XML draft builder with structural alignment for official namespace, schema location, and key SIFEN groups. Schema-readiness configuration now includes issuer-side establishment location/economic activity data and receiver-side fiscal identity/geography snapshots, and the normalized Paraguay payload carries those fields for future XML emission. Digital signature, QR, SIFEN submission, KuDE/PDF, full XSD validation, and XML emission of the new schema-readiness fields remain future stages.

Administrative UI labels should remain country-neutral whenever a generic concept exists. Country-specific terminology should be used only when there is no meaningful cross-country abstraction, such as Timbrado, CDC, CSC, issuer RUC, establishment, or point of issue.

## 1. Core Modules

* `einvoice_module`
  * Fiscal documents
  * Fiscal document lines
  * Fiscal tenants
  * Fiscal events
  * Fiscal transmissions
  * Fiscal attachments
  * Fiscal lock policies
  * Orchestration
  * Adapter registry
* `fiscal_api`
  * API key authentication
  * Tenant resolution
  * Document creation endpoint
  * Status endpoint
  * Async and sync processing modes
  * Idempotency behavior

## 2. Country Modules

* `einvoice_py`
  * Paraguay issuer
  * Paraguay establishment
  * Paraguay point of issue
  * Paraguay timbrado
  * Paraguay CSC
  * Paraguay sequence
  * Paraguay numbering
  * Paraguay CDC
  * Paraguay payload builder
  * Paraguay unsigned XML draft builder
  * Paraguay XML structural alignment
  * Paraguay issuer schema-readiness configuration
  * Paraguay receiver schema-readiness snapshot fields
  * Paraguay payload schema-readiness extensions
* future `einvoice_cr`
* future `einvoice_ar`

## 3. Architectural Decisions

* Country-neutral core
* Country addons isolated
* CDC stored in `country_identifier`
* Payload generated before XML
* Multi-tenant isolation
* Fiscal event audit trail
* API supports async and sync processing modes
* Fiscal artifacts are persisted as attachments
* Paraguay numbering happens before CDC
* CSC is reserved for QR and is not used for CDC

See the [ADR index](index.md#adrs) for detailed decision records.

## 4. Processing Flow

Fiscal Document
-> Validation
-> Country Adapter
-> Numbering
-> CDC
-> Payload
-> Unsigned XML
-> Signature (future)
-> Tax Authority (future)

## Related Documents

* [Documentation Home](README.md)
* [Documentation Index](index.md)
* [Roadmap](ROADMAP.md)
* [ADR-001 Country Addons](ADR/ADR-001-country-addons.md)
* [ADR-004 Multi-Tenant Shared Core](ADR/ADR-004-multi-tenant-shared-core.md)
* [Paraguay Documentation](PARAGUAY/README.md)
* [Diagrams Index](diagrams/README.md)

## Next Recommended Reading

* [ADR-001 Country Addons](ADR/ADR-001-country-addons.md)
* [Diagrams Hub](diagrams/README.md)
