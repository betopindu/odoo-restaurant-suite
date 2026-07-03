# Architecture

[Documentation Home](README.md) -> Architecture

[Documentation Home](README.md)
-> [ADRs](index.md#adrs)
-> [Paraguay](PARAGUAY/README.md)
-> [Diagrams](diagrams/README.md)

## Overview

The e-Invoice Platform is built around a country-neutral fiscal core, country-specific addons, and an API-first integration layer.

The core owns common fiscal concepts such as document lifecycle, events, transmissions, attachments, tenant isolation, idempotency, lock policies, credential references, credential role bindings, and orchestration.

Country addons own country-specific concepts such as numbering, fiscal identifiers, payloads, authority-specific configuration, and future XML/signing/authority integration.
Paraguay already includes an unsigned SIFEN-oriented XML draft builder with structural alignment for official namespace, schema location, and key SIFEN groups. Schema-readiness configuration now includes issuer-side establishment location/economic activity data and receiver-side fiscal identity/geography snapshots. The normalized Paraguay payload carries those fields, and the unsigned XML draft emits them for `gEmis`, `gActEco`, and `gDatRec`. Paraguay also includes a project-owned pre-signature XML readiness harness that validates unsigned structure and rejects signing/QR-stage elements without claiming official XSD validation. The official SIFEN v150 schema dependency tree is pinned locally from the e-Kuatia endpoint with manifest provenance, SHA-256 checksums, local-only URL resolution, and no runtime downloads. The Odoo runtime includes XML security dependencies, and `PyCertificateInspectionService` can transiently inspect PKCS#12 and PEM certificate material for XML-signing and mutual-TLS roles. Inspection reports expose certificate metadata, role validation, and strict Subject/SAN RUC extraction without returning secret material. The core stores tenant-scoped `fiscal.credential` references and separate `fiscal.adapter.credential.binding` records for XML signing and mutual TLS. These records contain provider references and inspection metadata only; they do not contain certificate bundles, PEM content, private keys, or passwords. `PySignedXmlPreparationService` validates CDC consistency and prepares unsigned XML by inserting deterministic `dFecFirma` content immediately after `dDVId`. `PyXmlSignatureService` then signs the prepared `DE` by `Reference URI="#CDC"` with XMLDSig, RSA-SHA256, SHA256 digest, inclusive C14N, enveloped-signature and exclusive-C14N transforms, and an embedded `X509Certificate`. `PyXmlSignatureVerificationService` locally verifies signed XML structure and XMLDSig cryptographic validity, extracts `DigestValue`, and reports the embedded certificate SHA-256 fingerprint without trust-chain or revocation decisions. `PySignedXmlAttachmentService` persists signed XML as a separate sensitive `paraguay_xml_signed` fiscal attachment with SHA-256 and safe signing metadata only, without overwriting unsigned XML or payload JSON artifacts. `PySigningPipelineService` coordinates payload-to-signed-attachment execution by invoking the existing unsigned XML, preparation, XMLDSig, verification, and signed attachment services in sequence. `PyQrGenerationService` generates the deterministic Paraguay QR payload string from signed XML, CDC, XMLDSig `DigestValue`, and CSC/IdCSC configuration without exposing the CSC value. `PyXsdValidationService` can now validate final signed XML with QR content against the pinned official SIFEN v150 schema set and return structured line/column/error reports without runtime downloads. The repository does not currently vendor an official SIFEN QR/cHashQR test vector, so final QR hash behavior must be confirmed against SIFEN sandbox or a future official vector before production submission. ADR-011 defines the XMLDSig boundary: preserve unsigned and signed artifacts separately, keep signing and mutual TLS credential roles logically separate, and generate QR only after signing. Concrete secret-provider implementations, trust-chain validation, revocation validation, QR image rendering, signing pipeline processing integration, SIFEN submission, and KuDE/PDF remain future implementation stages.

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
-> Tax Authority (future)

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
