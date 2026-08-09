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

The first controlled synchronous DE was accepted by SIFEN TEST on 2026-08-06
with authority code `0260`. The accepted path exercised the qualified PKCS#12,
both logical credential bindings, XMLDSig, QR/CSC, final XSD validation, SOAP
1.2, mTLS, response classification, and transmission/document persistence.
This is evidence of interoperability for the tested invoice profile, not
production certification or coverage of every authority scenario. The suite at
current delivery baseline reports 548 counted tests across 484 test methods.

Stage 8.24B durable pre-POST persistence, production preflight, cron activation,
monitoring, and production go-live remain pending.

Homologation corrections remain Paraguay-local. `PySifenDatetimeService`
interprets naive Odoo datetimes as UTC instants, converts them through the IANA
zone `America/Asuncion`, and applies an explicit 60-second safety margin only to
new signing instants. `PySignedXmlAttachmentService` serializes signed-artifact
replacement under a document row lock, reuses byte-identical content, and
retains superseded signatures for audit. QR generation reads the final selected
signed XML and verifies its `DigestValue`; CSC is appended transiently only to
the hash preimage. VAT-inclusive item and document totals are derived from one
Decimal calculation path before XML serialization. None of these rules depends
on the homologated document, taxpayer, establishment, receiver, or CDC.

Live SIFEN TEST acceptance requires the taxpayer's Qualified Certificate issued by a Prestador Cualificado de Servicios de Confianza (PCSC) habilitado. The supported operational input format is PKCS#12 (`.p12`). One certificate may be used for both XML signing and mutual TLS, but the adapter keeps the `xml_signing` and `mutual_tls` bindings logically separate; both bindings may point to the same `fiscal.credential`. This separation preserves explicit role validation and allows rotation without changing signing, submission, persistence, or retry consumers.

The credential boundaries have distinct responsibilities. `PySifenCredentialProvider` resolves document-scoped adapter configuration, role bindings, signing material, CSC, endpoint, and timeout into a redaction-safe runtime object. `FiscalCredentialMaterialProvider` defines how referenced secret material is loaded transiently. `ExternalSecretPkcs12MaterialProvider` implements that interface for `external_secret` credentials without changing any consumer. It reads PKCS#12 bytes from an absolute `file://` reference and resolves the optional password from a `file://` or `env://` reference. It returns only the existing `pkcs12_bytes` and `password` material contract, does not cache values, and remains independent of every Prestador Cualificado de Servicios de Confianza (PCSC) habilitado.

`PyQualifiedCertificateInstallationValidationService` validates an installed Paraguay credential without invoking signing, submission, or transport services. It requires the same active `external_secret` PKCS#12 credential to be bound explicitly to `xml_signing` and `mutual_tls`, loads the material once through the registry, and delegates both role inspections to `PyCertificateInspectionService`. It persists only the existing certificate metadata, status, inspection time, and secret-free JSON report. Provider exception text, secret references, PKCS#12 bytes, and passwords are excluded.

Local inspection validates the certificate structure, private-key match, taxpayer RUC, validity interval, and key usages. Local XMLDSig verification proves the generated signature cryptographically, but neither operation establishes that SIFEN trusts the client certificate. SIFEN makes the final client-certificate trust decision during mutual TLS and its authority validations. A self-signed certificate remains useful for deterministic local tests and negative connection scenarios, but cannot obtain real SIFEN acceptance.

The sandbox transport continues to avoid persisting secret material to Odoo or logs. Because stdlib `ssl` requires temporary certificate/key files for `load_cert_chain`, it creates restrictive OS-managed temporary files only during SSL context construction and unlinks them immediately afterward. The qualified certificate has a one-year operational validity and must be rotated before expiry. Replacement material can be introduced through the credential provider and bindings, inspected, and preflighted without modifying consumer services.

KuDE is a representation branch, not a submission stage. The submission pipeline
persists the exact final QR URL after XMLDSig as a versioned
`paraguay_qr_payload` artifact. `PyKudeService` later consumes only the latest
persisted `paraguay_payload_json` and current QR artifact, renders a
deterministic PDF with ReportLab, and persists it as a versioned
`paraguay_kude_pdf`. It cannot access XML, SOAP, authority responses, CSC, or
network services. Identical input reuses the current PDF; changed payload or QR
creates a new current version while preserving prior versions and their input
hashes. The document row lock makes selection and persistence atomic for
concurrent generators. This boundary is recorded in
[ADR-015](ADR/ADR-015-paraguay-kude-from-persisted-payload.md).

Stage 8.22 makes the existing TEST-only `verify_document_connection()` operation suitable for a manual live mTLS preflight. It resolves the document credential through the existing provider and role bindings, creates the normal client-certificate SSL context, and performs only an HTTPS `HEAD`. Results distinguish configuration, credential, DNS, TCP, TLS, client-certificate rejection, server-certificate trust, endpoint reachability, and HTTP response outcomes. A non-2xx HTTP response is successful connectivity evidence because it can occur only after reaching the HTTP layer. The adapter stores only a timestamped safe summary under `metadata_json["sifen_test_mtls_preflight"]`; endpoints, secret references, environment-variable names, certificate bytes, passwords, and exception text are excluded.

Stage 8.24A adds a TEST-only ambiguous-submission lifecycle without changing transaction durability. A timeout after a synchronous POST is normalized as ambiguous and persisted for manual review. While such a submission exists, `PySifenTransmissionPersistenceService` blocks every new POST for the same tenant, company, and CDC. The boundary is exposed as `PySifenDocumentQueryService` and `PySifenReconciliationService`; the original Stage 8.24A names remain aliases. Consulta DE sends the official SOAP 1.2 `rEnviConsDeRequest` (`dId`, `dCDC`) through the existing sandbox transport, mTLS material, and credential provider. Every attempt creates a separate `status_query` transmission with safe endpoint, duration, HTTP status, hashes, normalized result, authority timestamp and links to prior submissions; response XML and secrets are not copied into fiscal storage.

`0422` confirms remote approval: the document becomes accepted, `authority_status` and `accepted_at` are set, and `dProtAut` is copied only when returned. The original submission remains immutable; reconciliation evidence lives in the query transmission. Official Consulta DE exposes no distinct confirmed-rejection result. `0420` means only “not found or not approved”, is recorded as `reconciliation_not_found`, keeps the document in manual review and does not authorize resend. Timeout, HTTP/TLS failure, SOAP Fault, malformed content, unsupported codes, and CDC mismatch also remain unresolved. A row lock serializes reconciliation, accepted documents never regress, identical completed results are idempotent, and explicit diagnostics require a prior submission. No scheduler, automatic resend, independent cursor, explicit commit or outbox is introduced.

Paraguay emitter events form a separate boundary from DE submission. `PySifenEventService` builds and signs the official v150 `rEve`, wraps it in SOAP 1.2 `rEnviEventoDe`, reuses credential bindings and mTLS, parses `rRetEnviEventoDe`, and records safe hashes and transport/authority metadata. Cancellation uses a `cancel` transmission linked to the accepted document; successful code `0600` adds a lifecycle `fiscal.event` and moves the document to `cancelled` without altering `accepted_at` or accepted artifacts. Inutilization has a Paraguay-specific audit model because it concerns unused numbers rather than a fiscal document. This decision is recorded in [ADR-016](ADR/ADR-016-paraguay-sifen-emitter-events.md).

Stage 8.25 adds `PySifenTestReadinessService`, a local and deterministic readiness check over the existing document, Paraguay fiscal records, adapter, credential bindings, and qualified-certificate installation validator. It distinguishes invalid fiscal configuration, fiscal readiness, missing CSC, missing PKCS#12 reference, missing password reference, invalid certificate installation, and full submission readiness. The report contains only booleans, fixed status identifiers, and safe messages; it never contains CSC values, secret references, paths, passwords, or certificate material. Missing certificate configuration is a normal not-ready result and does not interrupt unrelated Odoo usage. No model, submission flow, transport, or network behavior changes.

Stage 8.26 completes the Paraguay v150 XMLDSig boundary by refining the existing `PyXmlSignatureService`, not by adding another signer. It signs the single SIFEN `DE` identified by the complete CDC, emits `Reference URI="#{CDC}"`, and places the standard XMLDSig `Signature` immediately after `DE` under `rDE`. SignedInfo uses inclusive XML C14N 1.0, RSA-SHA256, SHA-256, and only the enveloped-signature transform. `KeyInfo/X509Data/X509Certificate` contains only Base64-encoded DER certificate data. The immutable result returns signed bytes, reference URI, digest, signature value, and certificate DER Base64.

The signer receives the already normalized PEM certificate/private-key identity produced through the existing credential-provider and PKCS#12 material boundaries; it does not load PKCS#12 itself. It validates an RSA identity and certificate/private-key correspondence before signing. Local verification uses the embedded public certificate through a separate xmlsec verification path. XML signing occurs after unsigned DE preparation and before QR/final-document processing. XMLDSig identity and mutual-TLS identity remain separate logical roles even when both bindings reference the same physical certificate. Once signed, the XML must not be pretty-printed or otherwise mutated before verification and later QR/final assembly.

Stage 8.27 evolves the existing QR service into a dedicated `PySifenQrBuilder` with a backward-compatible document adapter. The builder accepts only signed SIFEN XML, validates the single `DE`, CDC, XMLDSig `DigestValue`, receiver identity, totals, item groups, CSC inputs, and environment, and returns an immutable result. Parameter ordering is explicit rather than mapping-dependent. Emission datetime and the Base64 text of `DigestValue` are converted directly from UTF-8 text to lowercase hexadecimal; the digest is not Base64-decoded or hashed again. Totals retain their XML text and `cItems` counts `gCamItem` elements.

The builder selects the TEST or PRODUCTION QR URL from one environment map, hashes the ordered parameter string concatenated with the transient CSC secret using SHA-256, and creates the namespaced `gCamFuFD/dCarQR` fragment with XML-library escaping. The secret is absent from the URL, immutable result, XML fragment, logs, and errors. The existing submission pipeline appends the generated group after the already signed content without pretty-printing or re-indenting signed XML. The builder has no dependency on SOAP, transport, network access, or graphical QR rendering.

Stage 8.28 introduces `PySifenRdeAssembler` as the final XML boundary. It accepts the already signed `rDE` plus the generated `gCamFuFD`, verifies the CDC and required structure, and appends the QR group to produce the exact `dVerFor`, `DE`, XMLDSig `Signature`, `gCamFuFD` order. It does not rebuild, reorder, re-indent, or pretty-print signed nodes. The assembler delegates validation to the existing `PyXsdValidationService` and returns an immutable result containing final XML, the parsed document, CDC, QR URL, validation status, and structured validation errors with message, line, column, element, and path when available. The submission pipeline consumes this result without changing signing, QR calculation, SOAP, transport, persistence, or retry responsibilities.

Stage 8.29 introduces `PySifenSoapEnvelopeBuilder` as a pure SOAP XML boundary. Stage 8.29A audits it against the official v150 Manual and `WS_SiRecepDE_v150.xsd`: the builder validates the final `rDE`, preserves its root-element bytes, and embeds it once under the SOAP 1.2 `Envelope/Header/Body/rEnviDe/dId/xDE` structure. It returns immutable XML plus `SiRecepDE` service/action metadata, CDC, and submission identifier. Namespace boundaries use the official SOAP and SIFEN namespace URIs without adding inherited prefixes to the signed subtree; no indentation or pretty-printing occurs, and local XMLDSig verification remains valid after wrapping. The existing submission service delegates envelope construction to this builder while retaining sequence allocation, HTTP, response normalization, persistence, and retry behavior.

Stage 8.30 adds `PySifenSoapClient` as a TEST-only HTTPS execution boundary for an already assembled envelope. It validates the SOAP 1.2 hierarchy, signed final `rDE`, and local XSD report before delegating the original request bytes to `PySifenSandboxTransport`. The transport continues to own PKCS#12 material resolution and transient mTLS context construction, now with an explicit TLS 1.2 minimum. The immutable client result preserves HTTP status, safe header pairs, raw response bytes, parsed XML when possible, elapsed time, endpoint, `dId`, and a fixed failure category. It performs no XML generation, business response interpretation, persistence, retry, or production dispatch.

Stage 8.31 adds `PySifenRecepDeResponseParser` immediately after that transport boundary without coupling it to submission or storage. It consumes only the immutable SOAP-client result and validates the SOAP 1.2 `Body/rRetEnviDe/rProtDe` response hierarchy by namespace URI. The official v150 response contract maps `rProtDe/Id` to the response identifier and processed CDC, `dFecProc` to processing time, optional `dProtAut` to the authorization transaction number, `dEstRes` to the overall authority state, and each of the zero-to-100 `gResProc` groups to `dCodRes` and `dMsgRes`. The originating request `dId` remains available separately from the SOAP-client result.

Classification is deliberately layered: a SOAP 1.2 Fault is never a business rejection, an HTTP error takes precedence over any embedded business fields, and a successful HTTP status alone never means acceptance. Official `0260` and the documented approved states map to accepted; rejected authority states remain rejected; duplicate validation codes `1001` and `1002` are distinguished from other rejections. The synchronous v150 contract defines no received-for-processing or pending outcome—`0361` belongs to the separate lot-result service—so the finite model reserves that classification without inferring it from unrelated services. Unknown future codes remain recoverable as `unrecognized_official_code`, with the original code, message, raw bytes, and a safe warning retained. Empty, non-XML, wrong-namespace, structurally invalid, or conflicting responses are malformed. The parser performs no logging, persistence, retry, Consulta DE, or network operation.

Stage 8.32 extends the existing `PySifenSubmissionService` with a TEST-only `submit()` composition entry point. It invokes the existing unsigned builder and signing preparation, XMLDSig signer, QR builder, final `rDE` assembler/XSD validator, SOAP envelope builder, SOAP client, and `siRecepDE` response parser in that order. Credentials are resolved once through `PySifenCredentialProvider`; callers may instead supply the already resolved runtime object. The existing `submit_final_xml()` compatibility API, persistence pipeline, retry services, Consulta DE, and authority workflow remain unchanged.

An authority response, including a SOAP Fault or business rejection, is returned as `PySifenRecepDeResponseResult`. Failures before an HTTP response use the immutable, secret-free `PySifenSubmissionFailureResult`, whose stage and category distinguish configuration, DE construction, XMLDSig, QR, local XSD, SOAP generation, and transport. Optional debug logging records only stage names, CDC, safe categories, HTTP status, and SHA-256 hashes; it never records PKCS#12 data, keys, passwords, CSC, certificates, SOAP bytes, or signed XML. This operation intentionally performs no fiscal persistence, automatic retry, state transition, Consulta DE, or KuDE generation.

Authority incidents are classified independently from fiscal acceptance or rejection. Transmission persistence records the safe HTTPS endpoint, actual HTTP status, measured duration, hashes, and a sensitive normalized-response JSON artifact; the raw response body is deliberately not copied into fiscal storage because it can contain document data. The exact Paraguay combination `0100` plus the normalized message `Error Inesperado(PKI)` remains an explicit, non-ambiguous rejection but is classified as `transient_authority_incident`: an operator may authorize a guarded manual retry, while automatic retry remains forbidden. Other `0100` responses do not inherit that classification. `PySifenManualRetryService` blocks accepted or ambiguous CDCs and requires a signing instant newer than the current signed artifact before delegating to the ordinary persistence pipeline.

The authoritative operator references are the
[SIFEN TEST Configuration](PARAGUAY/CONFIGURATION.md) and
[Homologation Runbook](PARAGUAY/HOMOLOGATION_RUNBOOK.md). Submission boundary
and postponed-durability decisions are recorded in
[ADR-013](ADR/ADR-013-sifen-submission-boundaries.md); TEST timbrado separation
is recorded in [ADR-014](ADR/ADR-014-paraguay-test-timbrado-profile.md).

Administrative UI labels should remain country-neutral whenever a generic concept exists. Country-specific terminology should be used only when there is no meaningful cross-country abstraction, such as Timbrado, CDC, CSC, issuer RUC, establishment, or point of issue.

### Paraguay recipient delivery boundary

`PyFiscalDocumentDeliveryService` is a read-only boundary over accepted fiscal
evidence. It never builds payloads, signs XML, renders KuDE, contacts SIFEN, or
interprets transport results. The submission pipeline persists the XSD-valid
recipient-ready `rDE` as the versioned `paraguay_rde_final` artifact immediately
before SOAP submission; this is distinct from `paraguay_xml_signed`, which is
the signed pre-QR input retained for signing and retry audit. Delivery resolves
only the single current final `rDE` and current KuDE PDF, verifies hashes, final
XML structure and XMLDSig locally, and returns immutable, redacted file results.

Only `accepted` documents are deliverable. Rejected, ambiguous, draft, ready,
signed, submitted, failed, and cancelled documents are blocked. Cancellation
delivery semantics remain pending the future authority-event implementation.
Downloads use authenticated UUID-scoped routes and re-run document record-rule
and company checks; callers cannot address arbitrary attachment IDs. Email
preparation is side-effect-free and returns only the PDF/XML pair. No delivery
audit model is added: pure resolution and preparation remain idempotent and do
not create records; a future actual mail/send operation may justify an audit
event at that side-effect boundary.

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
  * Exact Paraguay QR payload artifact persistence
  * Deterministic, versioned Paraguay invoice KuDE/PDF generation
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
* Paraguay KuDE is derived only from persisted payload and exact QR artifacts, never fiscal XML or authority responses

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
-> Exact QR Payload Attachment
-> Final rDE Assembly
-> Full Official XSD Validation
-> SIFEN Sandbox mTLS Verification
-> Environment-Aware SIFEN Submission Pipeline
-> Pending Fiscal Transmission / Payload Persistence
-> HTTPS POST and Authority Response
-> Final Fiscal Transmission / Document Persistence
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
-> SOAP 1.2 Envelope Assembly
-> SOAP 1.2 Submission
-> SIFEN Client-Certificate Trust Decision

Persisted Payload + Exact QR Payload Attachment
-> Deterministic KuDE Rendering
-> Versioned KuDE PDF Attachment

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
