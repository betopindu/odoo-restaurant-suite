# Architecture

[Documentation Home](README.md) -> Architecture

[Documentation Home](README.md)
-> [ADRs](index.md#adrs)
-> [Paraguay](PARAGUAY/README.md)
-> [Diagrams](diagrams/README.md)

## Overview

The e-Invoice Platform is built around a country-neutral fiscal core, country-specific addons, and an API-first integration layer.

The core owns common fiscal concepts such as document lifecycle, events, transmissions, attachments, tenant isolation, idempotency, lock policies, credential references, credential role bindings, and orchestration.

Country addons own country-specific concepts such as numbering, fiscal identifiers, payloads, authority-specific configuration, XML signing, QR generation, and authority integration.
Paraguay includes an unsigned SIFEN-oriented XML builder, pinned local SIFEN v150 schemas, XMLDSig preparation/generation/verification, sensitive signed-XML attachment persistence, QR payload generation, and final official XSD validation. Tenant-scoped `fiscal.credential` references and separate adapter bindings preserve the distinction between XML signing and mutual TLS without persisting certificate bundles, PEM content, private keys, or passwords.

Stages 8.9 through 8.13 complete the current production-capable service composition. `PySifenCredentialProvider` resolves a production document's adapter, scoped signing and mutual-TLS credentials, signing material, CSC, endpoint, and timeout into a fully redacted runtime object. `PySifenSubmissionService` and `PySifenSubmissionPipelineService` are environment-independent, while `PySifenTestSubmissionService` remains a compatibility wrapper for TEST callers. The pipeline dispatches TEST and PRODUCTION documents through the same signing, QR, final XML, XSD, and normalized submission implementation. `PySifenTransmissionPersistenceService` stores secret-free transmission results for either environment, and the existing scheduler and execution services accept eligible `test_submission` and `production_submission` transport failures with the same backoff, limits, idempotency, and stale-state protections. The retry runner and cron entry remain unchanged, and the cron remains disabled by default.

Stage 8.13 is tests-only: one deterministic integration scenario proves production credential resolution, pipeline dispatch, persistence, retry scheduling, retry execution, and final acceptance compose correctly without a network call. The current `einvoice_py` suite reports 363 counted tests across 323 test methods. This coverage is not live SIFEN certification. Real sandbox calls, authority-issued certificates and mutual TLS, real CSC behavior, cron activation, operational monitoring, and production go-live remain pending.

The sandbox transport continues to avoid persisting secret material to Odoo or logs. Because stdlib `ssl` requires temporary certificate/key files for `load_cert_chain`, it creates restrictive OS-managed temporary files only during SSL context construction and unlinks them immediately afterward. Trust-chain validation, revocation validation, official QR/cHashQR confirmation, QR image rendering, adapter processing integration, and KuDE/PDF remain future work.

Administrative UI labels should remain country-neutral whenever a generic concept exists. Country-specific terminology should be used only when there is no meaningful cross-country abstraction, such as Timbrado, CDC, CSC, issuer RUC, establishment, or point of issue.

## 1. Core Modules

* `einvoice_module`
  * Fiscal documents
  * Fiscal document lines
  * Fiscal tenants
  * Fiscal events
  * Fiscal transmissions
  * Fiscal attachments
  * Fiscal credential references
  * Adapter credential role bindings
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
  * Paraguay XML schema-readiness emission
  * Paraguay pre-signature XML validation harness
  * Paraguay local XSD validation infrastructure
  * Paraguay local XSD validation infrastructure hardening
  * Paraguay official SIFEN v150 XSD assets
  * Paraguay certificate inspection service
  * Paraguay signed XML preparation service
  * Paraguay XMLDSig generation service
  * Paraguay local XMLDSig verification service
  * Paraguay signed XML attachment persistence
  * Paraguay signing pipeline service
  * Paraguay QR payload generation service
  * Paraguay final official XSD validation service
  * Paraguay SIFEN test submission service
  * Paraguay SIFEN sandbox mutual-TLS transport
  * Paraguay SIFEN sandbox mTLS connection verification
  * Paraguay SIFEN test submission pipeline orchestration
  * Paraguay SIFEN fiscal transmission persistence
  * Paraguay SIFEN retry scheduling
  * Paraguay SIFEN callable retry execution
  * Paraguay SIFEN automatic retry runner
  * Paraguay SIFEN credential provider
  * Environment-independent Paraguay SIFEN submission service
  * Paraguay SIFEN production submission dispatch
  * Paraguay SIFEN production transmission persistence
  * Paraguay SIFEN production retry scheduling and execution
  * Paraguay SIFEN production composition integration test
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
* Paraguay signs `DE` by CDC before generating QR
* Unsigned and signed Paraguay XML are separate fiscal artifacts
* Certificate inspection is transient and produces secret-free reports
* XML-signing and mutual-TLS certificate roles are validated separately
* Fiscal credentials store provider references and inspection metadata, not secret material
* Adapter configurations bind XML-signing and mutual-TLS credentials independently
* Fiscal credential references and bindings are administrator-only until a narrower delegated access policy is designed

See the [ADR index](index.md#adrs) for detailed decision records.

## 4. Processing Flow

Fiscal Document
-> Validation
-> Country Adapter
-> Numbering
-> CDC
-> Payload
-> Unsigned XML
-> Signed XML Preparation / dFecFirma
-> XMLDSig Signature
-> Local XMLDSig Verification
-> Signed XML Attachment
-> QR Payload
-> QR Image (future)
-> Full Official XSD Validation
-> SIFEN Sandbox mTLS Verification
-> Environment-Aware SIFEN Submission Pipeline
-> Fiscal Transmission Persistence
-> Retry Scheduling
-> Callable Retry Execution
-> Automatic Retry Runner
-> Production service composition (tested without live SIFEN calls)

## Related Documents

* [Documentation Home](README.md)
* [Documentation Index](index.md)
* [Roadmap](ROADMAP.md)
* [ADR-001 Country Addons](ADR/ADR-001-country-addons.md)
* [ADR-004 Multi-Tenant Shared Core](ADR/ADR-004-multi-tenant-shared-core.md)
* [ADR-011 Paraguay Digital Signature Strategy](ADR/ADR-011-paraguay-digital-signature-strategy.md)
* [Paraguay Documentation](PARAGUAY/README.md)
* [Diagrams Index](diagrams/README.md)

## Next Recommended Reading

* [ADR-001 Country Addons](ADR/ADR-001-country-addons.md)
* [Diagrams Hub](diagrams/README.md)
