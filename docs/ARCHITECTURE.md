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

Stages 8.9 through 8.18 complete the current production-capable service composition, non-live sandbox preflight, and synchronous SOAP protocol framing. `PySifenCredentialProvider` resolves a document's adapter, scoped signing and mutual-TLS credentials, signing material, CSC, endpoint, and timeout into a fully redacted runtime object. `PySifenSubmissionService` and `PySifenSubmissionPipelineService` are environment-independent, while `PySifenTestSubmissionService` remains a compatibility wrapper for TEST callers. The pipeline dispatches TEST and PRODUCTION documents through the same signing, QR, final XML, XSD, and normalized submission implementation. Synchronous submission uses SOAP 1.2, `application/soap+xml`, and the official `rEnviDe/dId/xDE/rDE` request structure. Its taxpayer-controlled, sequential `dId` is allocated from the existing persistent `fiscal.adapter.config.sequence_id` and validated as numeric with a maximum of 15 digits. Stage test configuration uses `no_gap`; DNIT does not explicitly require gapless or rollback-safe allocation, so `no_gap` is not a protocol requirement. `PySifenTransmissionPersistenceService` stores secret-free transmission results for either environment and resolves runtime credentials automatically when neither runtime credentials nor legacy explicit credential arguments are supplied. Retry execution reconstructs omitted payload and signing timestamp inputs from `paraguay_payload_json` and `paraguay_xml_signed` metadata respectively. Stage 8.17 adds `PySifenSandboxTransport.verify_document_connection()` for Paraguay TEST documents. It resolves the runtime endpoint, timeout, and mutual-TLS credential and delegates exclusively to `verify_connection()` without generating payloads, XML, or submissions. Supplied credential providers always take precedence, including falsey instances. Fixed `ValidationError` boundaries suppress provider, PKCS#12, SSL, password, certificate, and parser details. The retry runner and cron entry remain unchanged, and the cron remains disabled by default.

Stage 8.13 is tests-only: one deterministic integration scenario proves production credential resolution, pipeline dispatch, persistence, retry scheduling, retry execution, and final acceptance compose correctly without a network call. Stages 8.15 and 8.16 complete automatic credential and retry-input resolution. Stage 8.17 composes document configuration with the existing injectable sandbox connection verifier. Stage 8.18 completes SOAP 1.2 synchronous request framing. The current `einvoice_py` suite reports 429 counted tests across 383 test methods. This coverage is not live SIFEN certification. Live sandbox validation, real certificate installation and mutual TLS, authority and CSC validation, production preflight, cron activation, operational monitoring, and production go-live remain pending.

Live SIFEN TEST acceptance requires the taxpayer's Qualified Certificate issued by a Prestador Cualificado de Servicios de Confianza (PCSC) habilitado. The supported operational input format is PKCS#12 (`.p12`). One certificate may be used for both XML signing and mutual TLS, but the adapter keeps the `xml_signing` and `mutual_tls` bindings logically separate; both bindings may point to the same `fiscal.credential`. This separation preserves explicit role validation and allows rotation without changing signing, submission, persistence, or retry consumers.

The credential boundaries have distinct responsibilities. `PySifenCredentialProvider` resolves document-scoped adapter configuration, role bindings, signing material, CSC, endpoint, and timeout into a redaction-safe runtime object. `FiscalCredentialMaterialProvider` defines how referenced secret material is loaded transiently. `ExternalSecretPkcs12MaterialProvider` implements that interface for `external_secret` credentials without changing any consumer. It reads PKCS#12 bytes from an absolute `file://` reference and resolves the optional password from a `file://` or `env://` reference. It returns only the existing `pkcs12_bytes` and `password` material contract, does not cache values, and remains independent of every Prestador Cualificado de Servicios de Confianza (PCSC) habilitado.

`PyQualifiedCertificateInstallationValidationService` validates an installed Paraguay credential without invoking signing, submission, or transport services. It requires the same active `external_secret` PKCS#12 credential to be bound explicitly to `xml_signing` and `mutual_tls`, loads the material once through the registry, and delegates both role inspections to `PyCertificateInspectionService`. It persists only the existing certificate metadata, status, inspection time, and secret-free JSON report. Provider exception text, secret references, PKCS#12 bytes, and passwords are excluded.

Local inspection validates the certificate structure, private-key match, taxpayer RUC, validity interval, and key usages. Local XMLDSig verification proves the generated signature cryptographically, but neither operation establishes that SIFEN trusts the client certificate. SIFEN makes the final client-certificate trust decision during mutual TLS and its authority validations. A self-signed certificate remains useful for deterministic local tests and negative connection scenarios, but cannot obtain real SIFEN acceptance.

The sandbox transport continues to avoid persisting secret material to Odoo or logs. Because stdlib `ssl` requires temporary certificate/key files for `load_cert_chain`, it creates restrictive OS-managed temporary files only during SSL context construction and unlinks them immediately afterward. The qualified certificate has a one-year operational validity and must be rotated before expiry. Replacement material can be introduced through the credential provider and bindings, inspected, and preflighted without modifying consumer services. Official QR/cHashQR confirmation, QR image rendering, adapter processing integration, and KuDE/PDF remain future work.

Stage 8.22 makes the existing TEST-only `verify_document_connection()` operation suitable for a manual live mTLS preflight. It resolves the document credential through the existing provider and role bindings, creates the normal client-certificate SSL context, and performs only an HTTPS `HEAD`. Results distinguish configuration, credential, DNS, TCP, TLS, client-certificate rejection, server-certificate trust, endpoint reachability, and HTTP response outcomes. A non-2xx HTTP response is successful connectivity evidence because it can occur only after reaching the HTTP layer. The adapter stores only a timestamped safe summary under `metadata_json["sifen_test_mtls_preflight"]`; endpoints, secret references, environment-variable names, certificate bytes, passwords, and exception text are excluded.

Stage 8.24A adds a TEST-only ambiguous-submission lifecycle without changing transaction durability. A timeout after a synchronous POST is normalized as ambiguous and persisted for manual review. While such a submission exists, `PySifenTransmissionPersistenceService` blocks every new POST for the same tenant, company, and CDC. `PySifenConsultaDeService` sends the official SOAP 1.2 Consulta DE request by CDC through the existing sandbox transport, mTLS material, and credential provider, and records a separate `status_query` transmission containing only request/response hashes, authority code/message, HTTP status, and timestamps.

`PySifenAmbiguousSubmissionReconciliationService` interprets authority code `0422` as remote approval, accepts the original submission and document, sets `authority_status` and `accepted_at`, and copies `dProtAut` only when the official response contains it. Code `0420` does not authorize an automatic resend: the original transmission becomes final and the document remains in manual review until explicit operator action. Consulta timeout, SOAP Fault, malformed content, unsupported codes, and CDC mismatch leave the original ambiguity unresolved and therefore keep submission blocked. Reconciliation is idempotent. This stage deliberately does not add independent cursors, explicit commits, an outbox, or durable pre-POST persistence.

Stage 8.25 adds `PySifenTestReadinessService`, a local and deterministic readiness check over the existing document, Paraguay fiscal records, adapter, credential bindings, and qualified-certificate installation validator. It distinguishes invalid fiscal configuration, fiscal readiness, missing CSC, missing PKCS#12 reference, missing password reference, invalid certificate installation, and full submission readiness. The report contains only booleans, fixed status identifiers, and safe messages; it never contains CSC values, secret references, paths, passwords, or certificate material. Missing certificate configuration is a normal not-ready result and does not interrupt unrelated Odoo usage. No model, submission flow, transport, or network behavior changes.

Stage 8.26 completes the Paraguay v150 XMLDSig boundary by refining the existing `PyXmlSignatureService`, not by adding another signer. It signs the single SIFEN `DE` identified by the complete CDC, emits `Reference URI="#{CDC}"`, and places the standard XMLDSig `Signature` immediately after `DE` under `rDE`. SignedInfo uses inclusive XML C14N 1.0, RSA-SHA256, SHA-256, and only the enveloped-signature transform. `KeyInfo/X509Data/X509Certificate` contains only Base64-encoded DER certificate data. The immutable result returns signed bytes, reference URI, digest, signature value, and certificate DER Base64.

The signer receives the already normalized PEM certificate/private-key identity produced through the existing credential-provider and PKCS#12 material boundaries; it does not load PKCS#12 itself. It validates an RSA identity and certificate/private-key correspondence before signing. Local verification uses the embedded public certificate through a separate xmlsec verification path. XML signing occurs after unsigned DE preparation and before QR/final-document processing. XMLDSig identity and mutual-TLS identity remain separate logical roles even when both bindings reference the same physical certificate. Once signed, the XML must not be pretty-printed or otherwise mutated before verification and later QR/final assembly.

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
  * Paraguay SIFEN automatic credential resolution at persistence
  * Paraguay SIFEN retry input reconstruction from fiscal attachments
  * Configuration-driven Paraguay SIFEN sandbox preflight
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
* The two certificate roles are logically separate and may resolve to one qualified certificate
* Fiscal credentials store provider references and inspection metadata, not secret material
* Adapter configurations bind XML-signing and mutual-TLS credentials independently
* Qualified certificate material is resolved through provider-neutral credential boundaries
* SIFEN, not local inspection, makes the final client-certificate trust decision
* Certificate rotation must not require changes to credential-consuming services
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
-> Automatic runtime credential resolution at persistence
-> Automatic retry input reconstruction from fiscal attachments
-> Configuration-driven sandbox preflight (TEST only, no submission)
-> Credential Provider / PKCS#12 Material
-> XML Signing Binding
-> Mutual-TLS Binding
-> SOAP 1.2 Submission
-> SIFEN Client-Certificate Trust Decision

## Related Documents

* [Documentation Home](README.md)
* [Documentation Index](index.md)
* [Roadmap](ROADMAP.md)
* [ADR-001 Country Addons](ADR/ADR-001-country-addons.md)
* [ADR-004 Multi-Tenant Shared Core](ADR/ADR-004-multi-tenant-shared-core.md)
* [ADR-011 Paraguay Digital Signature Strategy](ADR/ADR-011-paraguay-digital-signature-strategy.md)
* [ADR-012 Paraguay Qualified Certificate Lifecycle](ADR/ADR-012-paraguay-qualified-certificate-lifecycle.md)
* [Paraguay Documentation](PARAGUAY/README.md)
* [Diagrams Index](diagrams/README.md)

## Next Recommended Reading

* [ADR-001 Country Addons](ADR/ADR-001-country-addons.md)
* [Diagrams Hub](diagrams/README.md)
