# Paraguay

[Documentation Home](../README.md) -> Paraguay

[Documentation Home](../README.md)
-> [Architecture](../ARCHITECTURE.md)
-> [ADRs](../index.md#adrs)
-> [Diagrams](../diagrams/README.md)

## Overview

The Paraguay implementation lives in the country-specific addon `einvoice_py`.

The addon keeps Paraguay fiscal concepts outside the country-neutral core while using the shared fiscal document lifecycle, tenant isolation, attachments, events, and adapter pattern.

Current implemented Paraguay stages:

* issuer configuration
* establishment configuration
* point of issue configuration
* timbrado configuration
* CSC configuration
* sequence configuration
* numbering
* CDC generation
* normalized payload builder
* unsigned SIFEN-oriented XML draft builder
* SIFEN-oriented XML structural alignment
* issuer schema-readiness configuration for future `gEmis`
* receiver schema-readiness snapshot fields for future `gDatRec`
* payload schema-readiness extensions for future XML emission
* XML schema-readiness emission for issuer and receiver data
* pre-signature XML validation harness
* fiscal data enrichment for receiver, operation, payment, and tax details
* administrative UI stabilization for validation/support workflows
* accepted synchronous SIFEN TEST interoperability baseline

## Homologation status

The first controlled real TEST transmission was accepted on 2026-08-06:

* fiscal document: `16106`
* transmission: `17896`
* authority code: `0260`
* authority result: `Autorización del DE satisfactoria`

This is an auditable interoperability milestone for one invoice profile. It is
not production authorization and does not replace the remaining official TEST
cases. No operational identifier above is embedded in production services or
test fixtures.

The subsequent controlled B2B pipeline is locally complete and structurally
validated. Its first live TEST attempt was explicitly rejected with `1306`
because the masked real receiver `380****-*` was not present in the SIFEN TEST
Marangatu dataset. DNIT support confirmed that TEST is not synchronized with
Production and instructed homologation participants to select receivers from
the official published electronic-taxpayer list rather than trying arbitrary
production RUCs. A fresh two-item B2B document (`17894`) now uses a
DNIT-published electronic taxpayer and passes payload, XMLDSig, QR, rDE/XSD,
SOAP 1.2, credential-readiness and KuDE validation offline. Its status is
**REQUIRES LIVE TEST**; no submission has been made. See the
[homologation matrix](HOMOLOGATION_MATRIX.md) and
[runbook](HOMOLOGATION_RUNBOOK.md#handling-receiver-rejection-1306).

## Configuration

### Issuer

`fiscal.py.issuer` stores Paraguay issuer fiscal data needed for future SIFEN processing and CDC generation.

Key data:

* RUC without DV
* RUC DV
* taxpayer type
* economic activities
* tenant
* company
* environment

Issuer data is snapshotted onto the fiscal document during Paraguay processing so historical documents remain stable if configuration changes later.

`fiscal.py.economic.activity` stores Paraguay issuer economic activities needed later for schema-ready `gEmis/gActEco` output.

Economic activity data includes:

* code
* description
* sequence
* active flag
* tenant and company derived from the issuer

Economic activities belong to the Paraguay issuer. They are Paraguay-specific configuration in `einvoice_py`, not country-neutral core data.

### Establishment

`fiscal.py.establishment` represents the Paraguay establishment code.

An active establishment belongs to an issuer and carries tenant/company scope.

Stage 6.5.2B-1 adds optional SIFEN location fields to the establishment for future schema-ready `gEmis` output:

* house number
* department code and name
* district code and name
* city code and name
* branch name / `dDenSuc`

These fields are optional at the ORM and administrative UI level for now. They will be required later only by XML-readiness validation when generating schema-ready issuer data.

### Point Of Issue

`fiscal.py.point.of.issue` represents the Paraguay point of issue, also known as punto de expedicion.

It belongs to an establishment and provides the three-digit point code used in the full document number and CDC.

### Timbrado

`fiscal.py.timbrado` represents Paraguay fiscal authorization.

It is scoped by tenant, company, environment, and document type, and can be associated with allowed points of issue.

### CSC

`fiscal.py.csc` stores IdCSC and CSC configuration for Paraguay.

CSC is not used for CDC generation. It is used only for the implemented
QR/`cHashQR` generation after XMLDSig.

The CSC value is sensitive and should not be exposed in APIs or public payloads.

See [ADR-009 CSC Only For QR](../ADR/ADR-009-csc-only-for-qr.md).

### Sequence

`fiscal.py.sequence` stores Paraguay numbering configuration.

Sequences are scoped by:

* tenant
* company
* timbrado
* establishment
* point of issue
* document type

The initial next number is configured manually to support migration from existing numbering.

## Numbering

Paraguay numbering runs before CDC generation.

The assigned fields are:

* `py_document_number`
* `py_full_number`

`py_full_number` format:

```text
EST-PUNEXP-NUMBER
```

Example:

```text
001-003-0000015
```

Retries do not assign a new number when one already exists.

See [ADR-008 Paraguay Numbering Before CDC](../ADR/ADR-008-paraguay-numbering-before-cdc.md).

## CDC

CDC generation happens after issuer/config selection and numbering.

The CDC is stored in:

* `py_cdc`
* `py_cdc_base`
* `py_cdc_dv`
* `py_cod_seg`
* core `country_identifier`

The core remains country-neutral by using `country_identifier` as the shared fiscal identifier field.

See [ADR-002 CDC as Country Identifier](../ADR/ADR-002-cdc-country-identifier.md).

## Payload

`PyPayloadBuilder` builds a normalized Paraguay payload dictionary before XML generation.

The payload includes:

* document
* operation
* issuer
* receiver
* condition
* items
* totals
* paraguay
* warnings

The payload is persisted as a sensitive fiscal attachment of type `paraguay_payload_json`.

Stage 6.5.2B-3 extends `paraguay_payload_json` with pre-signature schema-readiness data. The issuer section now includes establishment SIFEN location fields and ordered active economic activities. The receiver section now includes taxpayer/non-taxpayer identity, country description, geography fields, and customer code.

Missing schema-readiness data is reported as payload warnings. Final unsigned
XML construction rejects mandatory omissions before signing.

See [ADR-003 Payload Before XML](../ADR/ADR-003-payload-before-xml.md).

## Unsigned XML Draft

Stage 6 adds `PyUnsignedXmlBuilder`, the first cut of the Paraguay unsigned XML builder.

Stage 6.5.1 aligns that draft closer to the official SIFEN XML structure while keeping it unsigned and draft-only.

Input:

* normalized Paraguay payload JSON produced by `PyPayloadBuilder`

Output:

* unsigned SIFEN-oriented XML draft
* fiscal attachment type `paraguay_xml_unsigned`
* filename format `<document_uuid>-paraguay-unsigned.xml`
* mimetype `application/xml`

The XML builder stays inside `einvoice_py` and uses the normalized payload as its source of truth. It does not read scattered fiscal document fields directly when building XML from payload.

Stage 6.5.1 XML alignment includes:

* official SIFEN default namespace: `http://ekuatia.set.gov.py/sifen/xsd`
* `xsi` namespace and `schemaLocation` for `siRecepDE_v150.xsd`
* root `rDE` with `dVerFor`
* `DE` preamble fields `dDVId` and `dSisFact`
* no `dFecFirma`, because that belongs to the future digital signature stage
* `gOpeDE` for emission fields such as `iTipEmi`, `dDesTipEmi`, and `dCodSeg`
* aligned `gTimb` with document type description
* invoice group `gCamFE`
* item value structure with `gValorItem` and nested `gValorRestaItem`
* `gCamIVA` with VAT affectation description
* updated `gTotSub` totals using SIFEN-oriented tags such as `dIVA5`, `dIVA10`, `dBaseGrav5`, `dBaseGrav10`, and `dTBasGraIVA`

Formatter decisions are local to XML output:

* money and decimal formatting are normalized when generating XML
* integer code normalization is applied when generating XML, for example `01` becomes `1` where SIFEN-oriented tags expect an integer code
* these formatter choices do not change the normalized payload or stored document data

The Paraguay fake adapter now attempts to create both attachments during processing:

* `paraguay_payload_json`
* `paraguay_xml_unsigned`

If the payload is complete enough for XML, the unsigned XML attachment is created. Incomplete admin/debug payloads may skip XML generation while still preserving fake adapter processing and payload attachment persistence.

Stage 6.5.2B-4 emits schema-readiness payload fields in the unsigned XML draft while keeping the builder payload-first.

Issuer XML emission now includes:

* establishment SIFEN location fields in `gEmis`
* repeated issuer economic activities in `gEmis/gActEco`

Receiver XML emission now includes:

* taxpayer receiver identity
* non-taxpayer receiver ID identity
* receiver geography fields
* customer code

Stage 6.5.3 adds `PyXmlValidationService`, a project-owned pre-signature XML readiness validation harness. This is not official SIFEN XSD validation.

The harness validates:

* required unsigned XML structure and groups
* receiver identity rules for taxpayer and non-taxpayer receivers
* repeated issuer economic activities
* repeated item groups
* absence of signing and QR-stage elements

It intentionally rejects unsigned XML containing:

* `dFecFirma`
* `Signature`
* `gCamFuFD`
* `dCarQR`

The fake adapter does not call this validation automatically yet.

Historical Stage 6 scope exclusions (now implemented by later stages):

* digital signature, `dFecFirma`, and `ds:Signature`
* QR generation and CSC QR/hash logic
* SIFEN submission
* KuDE/PDF
* XSD validation

## Schema Readiness

ADR-010 defines the distinction between pre-signature schema readiness and full official SIFEN XSD validation.

Stage 6.5.2B-1 completed issuer-side schema-readiness configuration:

* establishment SIFEN location fields
* issuer economic activities

These fields support future schema-ready `gEmis` and repeated `gActEco` output.

Stage 6.5.2B-2 completed receiver-side schema-readiness snapshot fields on `fiscal.document`:

* receiver taxpayer type for future `iTiContRec`
* receiver ID type, description, and number for non-taxpayer receivers
* receiver country description
* receiver house number
* receiver department, district, and city codes and names
* receiver customer code

Receiver operation type is aligned for future SIFEN readiness:

* `1 = B2B`
* `2 = B2C`
* `3 = B2G`
* `4 = B2F`

No migration was performed for older records where `3` had previously been exposed as `Foreign`. Existing records with receiver operation type `3` must be reviewed before schema-ready XML use.

These receiver fields are optional at the ORM and administrative UI level for now. They will be required later only by payload/XML readiness validation where applicable.

Stage 6.5.2B-3 completed payload schema-readiness extensions. `paraguay_payload_json` now includes issuer schema-readiness data:

* establishment SIFEN location fields
* ordered active economic activities

It also includes receiver schema-readiness snapshot data:

* taxpayer and non-taxpayer identity
* country description
* geography fields
* customer code

Receiver operation mapping is now SIFEN-aligned in the payload:

* `1 = B2B`
* `2 = B2C`
* `3 = B2G`
* `4 = B2F`

Missing schema-readiness data creates warnings but does not block payload generation.

Stage 6.5.2B-4 completed XML schema-readiness emission. The unsigned XML draft now emits the issuer and receiver schema-readiness fields already present in `paraguay_payload_json`:

* establishment SIFEN location fields in `gEmis`
* repeated issuer economic activities in `gActEco`
* taxpayer receiver identity in `gDatRec`
* non-taxpayer receiver ID identity in `gDatRec`
* receiver geography and customer code in `gDatRec`

`PyUnsignedXmlBuilder` remains payload-first and does not read Odoo document/configuration models directly for these fields.

Full official XSD validation is performed after signature and QR assembly. The
unsigned artifact intentionally contains no `dFecFirma`, `ds:Signature`, or QR.

## Homologation-driven service behavior

The following behavior is production-oriented and configuration-independent:

* `PySifenDatetimeService` treats naive Odoo datetimes as UTC, converts fiscal
  values with `America/Asuncion`, and applies the centralized 60-second margin
  only when producing a fresh `dFecFirma`.
* `PySignedXmlAttachmentService` keeps one current signed artifact per document,
  reuses identical bytes, and preserves changed versions as superseded audit
  evidence. Retry selection uses the current version.
* `PyPayloadBuilder` derives VAT-inclusive item bases, VAT, subtotals, and grand
  totals from one Decimal calculation path. `PyUnsignedXmlBuilder` serializes
  the resulting lexical values consistently.
* `PySifenQrBuilder` uses the exact `DigestValue` from the selected signed XML,
  explicit parameter ordering, UTF-8 lowercase hexadecimal conversion, and a
  transient CSC hash preimage. The CSC is absent from QR output and results.
* `PySifenTransmissionPersistenceService` locks the document, blocks accepted
  and ambiguous resubmissions, creates the pending transmission before calling
  the pipeline, and persists authority code, receipt, timestamps, and safe
  hashes after the response.

These rules contain no dependency on a specific RUC, document ID,
establishment, point of issue, receiver type, or homologation fixture.

Stage 6.5.3 completed the pre-signature XML validation harness with `PyXmlValidationService`. The service validates project-owned readiness rules for unsigned XML, including structure, receiver identity, required unsigned groups, and absence of signing/QR elements. It does not perform official XSD validation and is not automatically called by the fake adapter yet.

## SIFEN XSD Assets

Stage 6.5.8 pins the official SIFEN v150 schema dependency tree locally. Runtime downloads remain forbidden.

Location:

```text
custom_addons/einvoice_py/xsd/sifen/v150/
```

Structure:

```text
custom_addons/einvoice_py/xsd/sifen/v150/
├── README.md
├── manifest.json
└── schemas/
    ├── siRecepDE_v150.xsd
    ├── DE_v150.xsd
    ├── DE_Types_v150.xsd
    ├── Paises_v100.xsd
    ├── Departamentos_v141.xsd
    ├── Monedas_v150.xsd
    ├── Unidades_Medida_v141.xsd
    └── xmldsig-core-schema.xsd
```

`manifest.json` tracks:

* schema family
* country
* version
* root schema
* official source URL
* download date
* SHA-256 checksums
* dependency map
* runtime download policy

All eight files were retrieved byte-for-byte from:

```text
https://ekuatia.set.gov.py/sifen/xsd/
```

The original absolute `schemaLocation` values are preserved. `PyXsdValidationService` maps only manifest-listed official URLs to local files and blocks every unlisted external schema reference.

The pinned dependency tree is:

```text
siRecepDE_v150.xsd
└── DE_v150.xsd
    ├── xmldsig-core-schema.xsd
    ├── Paises_v100.xsd
    ├── Departamentos_v141.xsd
    ├── Monedas_v150.xsd
    ├── Unidades_Medida_v141.xsd
    └── DE_Types_v150.xsd
```

Full validation of generated XML still waits for signature and QR stages. Stage 6.5.3 remains project-owned pre-signature readiness validation, not official XSD validation.

Stage 6.5.5 adds `PyXsdValidationService` as local XSD validation infrastructure.

The service loads the pinned assets from:

```text
custom_addons/einvoice_py/xsd/sifen/v150/
```

It can:

* locate the expected local XSD directory
* load and validate a future `manifest.json`
* resolve root schema paths safely inside the local XSD directory
* compile the pinned schemas with `lxml`
* validate XML against the pinned schema

When assets are absent or fail checksum verification, it fails clearly with `ValidationError` instead of silently passing.

The schema is available for explicit validation, but the current unsigned XML draft is not required to pass it because full validation still requires signature and QR.

Stage 6.5.6 hardens `PyXsdValidationService` before real XSD assets are introduced. The service now:

* enforces `validation_policy.runtime_downloads_allowed = false`
* validates `root_schema` as a non-empty local path
* validates manifest file entries for `path`, `sha256`, and `role`
* validates SHA-256 checksums for listed files
* validates dependency map structure
* blocks path traversal outside the expected XSD root
* blocks external schema references in `xs:include` and `xs:import`

Stage 6.5.8 confirms the official dependency layout and adds manifest-backed URL-to-local resolution without rewriting the official files.

## Fiscal Data Enrichment

Stage 5.5 enriches the Paraguay payload data model with explicit fiscal fields on documents and document lines.

Document-level enrichment includes:

* receiver nature and operation type
* receiver country, address, and phone
* transaction type
* tax type
* currency and exchange rate
* sale condition
* payment type, amount, and currency

Line-level enrichment includes:

* internal item code
* unit measure code and description
* tax affectation
* tax rate
* tax proportion
* tax base
* tax amount
* exempt base
* discount amount

The payload builder uses these explicit fields to reduce warnings and calculate MVP tax buckets for exempt, IVA 5, and IVA 10 lines.

## Stage 5 Validation

The Fiscal Document form is an administrative and support tool. It is used for troubleshooting, audit, payload validation, and controlled correction flows. It is not intended to become the primary manual invoice-entry interface.

Stage 5.6.1 applies the shared UI terminology rule: labels should be country-neutral whenever a generic concept exists. Country-specific terms remain only when they represent genuine Paraguay fiscal concepts.

Keep Paraguay-specific terms:

* Timbrado
* CDC
* CSC
* Issuer RUC
* Issuer RUC DV
* Establishment
* Point of Issue

Use generic labels for shared concepts:

* Receiver Information
* Operation Information
* Payment Information
* Tax Affectation
* Tax Base
* Tax Amount
* Tax Rate

Primary operational channels remain:

* POS
* ERP integrations
* SaaS API
* future country or customer-specific integrations

Administrative users can validate a standard Paraguay invoice with:

* document type: invoice
* local taxpayer receiver
* receiver RUC with DV
* receiver address and email
* transaction type: service provision
* tax type: IVA
* sale condition: cash
* payment type: cash
* currency: PYG
* one line taxed by IVA 10%
* line tax base and tax amount populated

Expected result:

* Paraguay number assigned
* CDC assigned and copied to `country_identifier`
* Paraguay payload attachment generated
* IVA 10 bucket populated
* payload warnings empty for the fully populated MVP scenario

Warnings remain meaningful when optional or required-for-fiscal-quality data is missing, such as receiver DV, receiver email/address, receiver fiscal nature, operation type, or item tax details.

## Digital Signature

Stage 7.5 adds `PyXmlSignatureService`, a pure XMLDSig generation service for prepared Paraguay XML.

ADR-011 defines the SIFEN v150 signing strategy:

* use W3C XMLDSig in enveloped form
* do not add XAdES unless a future official requirement mandates it
* sign the `DE` node using `Reference URI="#CDC"`
* insert `dFecFirma` inside `DE`, after `dDVId` and before `dSisFact`
* place `Signature` under `rDE`, after `DE` and before `gCamFuFD`
* require CDC before signing and keep it immutable after signing
* preserve unsigned XML and signed XML as separate sensitive fiscal attachments
* use `xmlsec` or another maintained XML security library
* keep certificate and private-key access tenant-safe
* separate XML signing credentials logically from mutual TLS credentials
* never store private keys in ordinary plaintext fields

The service signs the prepared `DE` element by `Reference URI="#CDC"` using transient certificate and private-key material only. It uses:

* `CanonicalizationMethod`: inclusive C14N (`http://www.w3.org/TR/2001/REC-xml-c14n-20010315`)
* `SignatureMethod`: RSA-SHA256
* `DigestMethod`: SHA256
* transforms: enveloped signature and exclusive C14N

It embeds `X509Certificate`, places `Signature` as a sibling immediately after `DE`, rejects existing signatures, and verifies generated fixture signatures in tests.

Stage 7.5 does not generate QR content, submit to SIFEN, perform trust-chain or revocation validation, persist signed XML attachments, or retrieve production credential material from the credential architecture.

See [ADR-011 Paraguay Digital Signature Strategy](../ADR/ADR-011-paraguay-digital-signature-strategy.md).

## Local XMLDSig Verification

Stage 7.6 adds `PyXmlSignatureVerificationService`, a pure local verification service for signed Paraguay XML.

The service verifies signed XML structurally and cryptographically:

* requires official `rDE` root
* requires exactly one `DE`
* requires exactly one `Signature`
* requires `Signature` after `DE`
* requires `Reference URI="#CDC"`
* validates expected CDC and expected certificate fingerprint when provided
* verifies the XMLDSig signature with `xmlsec` using the embedded certificate
* checks the expected XMLDSig algorithms and transforms

The verification report is secret-free and includes the CDC, Reference URI, XMLDSig `DigestValue`, embedded certificate SHA-256 fingerprint, canonicalization method, signature method, digest method, and transforms.

Stage 7.6 does not generate QR content, submit to SIFEN, persist signed XML attachments, perform trust-chain validation, or perform revocation validation.

## Signed XML Attachment Persistence

Stage 7.7 adds signed XML fiscal attachment persistence.

The Paraguay attachment extension now includes:

* `paraguay_xml_signed` / `Signed XML`

`PySignedXmlAttachmentService` persists already-signed Paraguay XML as a separate sensitive fiscal attachment. It does not overwrite the unsigned XML attachment and does not overwrite the Paraguay payload JSON attachment.

The signed XML attachment stores:

* `mimetype`: `application/xml`
* `is_sensitive`: `True`
* SHA-256 of the signed XML bytes
* linked `ir.attachment`
* safe metadata JSON only:
  * CDC
  * XMLDSig `DigestValue`
  * signing certificate SHA-256 fingerprint
  * signing timestamp, when available

The service is idempotent: retrying persistence for a document with an existing signed XML attachment returns the existing attachment instead of creating a duplicate.

Stage 7.7 does not generate QR content, submit to SIFEN, integrate fake adapter processing, perform trust-chain validation, or perform revocation validation.

## Signing Pipeline

Stage 7.8 adds `PySigningPipelineService`, a single orchestration service for the Paraguay signing pipeline.

The pipeline accepts a fiscal document, normalized Paraguay payload, transient signing credential material, and signing timestamp. It then invokes the already implemented services in order:

1. `PyUnsignedXmlBuilder`
2. `PySignedXmlPreparationService`
3. `PyXmlSignatureService`
4. `PyXmlSignatureVerificationService`
5. `PySignedXmlAttachmentService`

The service does not duplicate signing, preparation, verification, or attachment logic. It aborts immediately on any failure and persists the signed XML only after successful local verification.

The returned report includes:

* CDC
* XMLDSig `DigestValue`
* signing certificate SHA-256 fingerprint
* signed fiscal attachment id
* local verification result

Stage 7.8 is callable orchestration only. It does not generate QR content, submit to SIFEN, perform trust-chain validation, perform revocation validation, or wire the fake adapter processing flow into production signing.

## QR Payload Generation

Stage 7.9 adds `PyQrGenerationService`, a pure service for generating the Paraguay QR payload string from a successfully signed XML document.

The repository-pinned official v150 XSD identifies the post-signature QR container as `gCamFuFD/dCarQR` and constrains it as the QR-code character content. ADR-009 reserves `IdCSC`/CSC for QR hashing, and ADR-011 requires QR generation after XMLDSig because QR depends on the XMLDSig `DigestValue`. The repository does not currently vendor an official SIFEN QR/cHashQR example vector, so the implemented hash vector is project-locked and must be confirmed against SIFEN sandbox or a future vendored official test vector before production submission.

The service requires:

* signed XML bytes
* CDC
* XMLDSig `DigestValue`
* document CSC configuration (`IdCSC` and CSC)
* mandatory QR fields present in the signed XML

It produces:

* `qr_string`
* `qr_hash`

The QR query payload is deterministic and follows the project-locked ordering:

1. `nVersion`
2. `Id`
3. `dFeEmiDE`
4. `dRucRec`
5. `dTotGralOpe`
6. `dTotIVA`
7. `cItems`
8. `DigestValue`
9. `IdCSC`
10. `cHashQR`

The CSC value is used only to compute `cHashQR`; it is not included in the generated QR string.

The service also validates that the signed XML contains exactly one XMLDSig `Signature`, exactly one XMLDSig `DigestValue`, and that the extracted digest matches the supplied `DigestValue`. The `dRucRec` QR field is populated from the official `dRucRec` XML element as-is; `dDVRec` remains a separate XML field and is not appended to the QR `dRucRec` value.

Stage 7.9 does not generate a QR image, submit to SIFEN, perform trust-chain validation, or perform revocation validation.

## Full Official XSD Validation

Stage 7.10 extends `PyXsdValidationService` with final signed XML validation for complete Paraguay XML after signature and QR payload generation.

The final validation path:

* uses the pinned official SIFEN v150 schema set vendored under `custom_addons/einvoice_py/xsd/sifen/v150`
* compiles schemas through the local-only resolver
* blocks runtime downloads and unlisted external schema references
* validates the complete signed XML document against `siRecepDE_v150.xsd`
* requires final-stage content before reporting success:
  * XMLDSig `Signature`
  * `gCamFuFD/dCarQR`

The service returns a structured report:

* `valid`
* `errors`
* `warnings`
* `schema_used`
* `failing_element`
* `line`
* `column`
* `message`

Stage 7.10 is validation only. It does not submit to SIFEN, perform trust-chain validation, perform revocation validation, generate QR images, or integrate the signing pipeline into production processing. Real generated final XML acceptance remains pending full pipeline integration and SIFEN sandbox confirmation.

## Certificate Inspection

Stage 7.3A adds `PyCertificateInspectionService`, a pure service for transient inspection of Paraguay certificate material.

The service supports:

* password-protected PKCS#12 bundles (`.p12` and `.pfx`)
* PEM certificate and private-key pairs
* RSA key type, minimum key size, and certificate/private-key matching
* certificate fingerprint, subject, issuer, serial number, validity, KeyUsage, ExtendedKeyUsage, and SAN reporting
* strict Paraguay RUC extraction from Subject `serialNumber` and supported SAN identity structures
* separate validation rules for `xml_signing` and `mutual_tls` roles
* secret-free reports with sanitized parsing and extension errors

XML-signing certificates require `digitalSignature` and `contentCommitment`. Mutual-TLS certificates require `clientAuth` and require `digitalSignature` when KeyUsage is present.

The service does not persist certificate bundles, private keys, or passwords. XML signing is implemented by the signing pipeline, and `ExternalSecretPkcs12MaterialProvider` retrieves deployment-mounted PKCS#12 material transiently. Inspection is local preventive validation; it does not establish that SIFEN trusts the client certificate.

## Credential Architecture

Stage 7.3B adds country-neutral credential references and adapter role bindings in `einvoice_module`.

`fiscal.credential` stores:

* tenant and company scope
* provider and material format
* external secret references
* certificate inspection metadata and secret-free inspection reports

It does not store private keys, PKCS#12 or PEM contents, or passwords.

`fiscal.adapter.credential.binding` binds an adapter configuration to one credential for each logical role:

* `xml_signing`
* `mutual_tls`

Bindings require the credential and adapter configuration to belong to the same tenant and company. XML-signing and mutual-TLS roles are logically separate and retain their role-specific validation. They may use different credentials, or both bindings may point to the same `fiscal.credential` when one qualified certificate satisfies both roles.

The credential services have different responsibilities:

* `PySifenCredentialProvider` resolves the document adapter, scoped role bindings, XML-signing material, CSC, endpoint, and timeout into one fully redacted runtime object.
* `FiscalCredentialMaterialProvider` defines the interface for loading referenced secret material transiently.
* `FiscalCredentialProviderRegistry` selects the registered material provider for a credential.
* `ExternalSecretPkcs12MaterialProvider` is the concrete provider for `external_secret` PKCS#12 credentials.

`ExternalSecretPkcs12MaterialProvider` resolves the existing references without storing secret material in Odoo:

* `secret_ref` must be an absolute `file://` reference to deployment-mounted PKCS#12 material.
* `password_secret_ref` is optional and may be an absolute `file://` reference or an `env://VARIABLE_NAME` reference.
* password files may contain one trailing line ending, which is removed when material is loaded.
* missing, empty, oversized, invalid, or unsupported references fail with fixed errors that do not expose paths, variable names, operating-system errors, or secret content.
* the provider returns only `{"pkcs12_bytes": ..., "password": ...}` and does not cache the result.

Encrypted Odoo storage, KMS, and PKCS#11/HSM providers remain unimplemented. The implemented provider boundary remains independent of every specific Prestador Cualificado de Servicios de Confianza (PCSC) habilitado.

### PKCS#12 Installation Validation

Stage 8.21 adds `PyQualifiedCertificateInstallationValidationService` for offline installation validation. It does not generate XML, sign a document, construct an SSL context, open a network connection, or submit a DE.

Installation procedure:

1. Mount the PKCS#12 and, when file-based, its password outside the repository. Example fictitious locations are `/run/secrets/sifen/test-client.p12` and `/run/secrets/sifen/test-client-password`.
2. Create one active `fiscal.credential` with `provider_type="external_secret"` and `material_format="pkcs12"`.
3. Set `secret_ref` to an absolute reference such as `file:///run/secrets/sifen/test-client.p12`.
4. Set the optional `password_secret_ref` to either `file:///run/secrets/sifen/test-client-password` or an environment reference such as `env://SIFEN_TEST_P12_PASSWORD`.
5. Configure the Paraguay adapter with `credentials_mode="external_secret"`.
6. Create exactly one `xml_signing` binding and one `mutual_tls` binding. Both bindings may point to the same credential.
7. Run the validation service with the credential, adapter, expected taxpayer RUC, and optional inspection time:

```python
from odoo.addons.einvoice_py.services import (
    PyQualifiedCertificateInstallationValidationService,
)

report = PyQualifiedCertificateInstallationValidationService(env).validate(
    credential=credential,
    adapter_config=adapter_config,
    expected_ruc="80000000-0",
)
```

The validation loads PKCS#12 material through `FiscalCredentialProviderRegistry` and delegates cryptographic inspection to `PyCertificateInspectionService` for both roles. It checks the password, X.509 certificate and private key presence, certificate/private-key match, end-entity status, expected RUC, validity interval, `digitalSignature`, `contentCommitment`, and `clientAuth`.

Only certificate metadata, inspection status/time, and a secret-free report are persisted on `fiscal.credential`. The service does not persist the PKCS#12 bundle, password, or private key, and it does not copy complete filesystem paths or environment-variable names into inspection metadata or reports. Provider failures are represented by a fixed safe message.

Never place `.p12` files, password files, plaintext passwords, or real secret references in source control. The paths and RUC above are examples only.

Credential references and bindings are restricted to system administrators for now.

The legacy `fiscal.adapter.config` fields `certificate_ref` and `private_key_ref` remain temporarily for compatibility. They are references only and must never contain raw certificates, PKCS#12 or PEM content, passwords, or private-key material. Future work should migrate these references to role bindings before removing the legacy fields.

## Qualified Certificate Lifecycle

Real SIFEN TEST acceptance requires the taxpayer's Qualified Certificate issued by a Prestador Cualificado de Servicios de Confianza (PCSC) habilitado. The supported operational format is a password-protected PKCS#12 (`.p12`) bundle containing the certificate and corresponding private key.

The same qualified certificate may be used for:

* XML signing through the `xml_signing` binding
* mutual-TLS client authentication through the `mutual_tls` binding

The bindings remain distinct even when they reference the same credential. This is a logical separation between consumers and validation rules, not a requirement to install two physical certificates.

The certificate inspection service validates structure, supported key characteristics, certificate/private-key correspondence, taxpayer RUC, validity interval, and role-specific usages. The signing pipeline then generates and verifies XMLDSig locally. These checks do not make a certificate trusted by the authority. SIFEN makes the final client-certificate trust and acceptance decision during mutual TLS and its authority validations.

A self-signed certificate can exercise local parsing, XML signing, verification, and negative TLS scenarios. It must not be used as evidence that a real SIFEN TEST submission can be accepted.

The qualified certificate has a one-year operational validity. Rotation must make replacement PKCS#12 material available through the configured material provider, inspect it for both required roles, update or replace the scoped credential bindings, and complete a TEST preflight before expiry and cutover. The signing, submission, persistence, and retry services continue consuming the existing credential interfaces and must not change for a certificate rotation.

See [ADR-012 Paraguay Qualified Certificate Lifecycle](../ADR/ADR-012-paraguay-qualified-certificate-lifecycle.md).

## Signed XML Preparation

Stage 7.4 adds `PySignedXmlPreparationService` as the boundary between unsigned XML generation and XMLDSig signing.

The service:

* safely parses unsigned Paraguay XML
* verifies that `DE/@Id`, `py_cdc`, and `country_identifier` contain the same CDC
* verifies that `dDVId` matches the CDC check digit
* rejects missing or duplicate signing-stage fields
* inserts `dFecFirma` immediately after `dDVId`
* preserves `dSisFact` and the remaining `DE` child ordering
* emits deterministic UTF-8 XML
* returns the prepared XML bytes, CDC, and normalized signing timestamp

The signing timestamp uses `YYYY-MM-DDTHH:MM:SS`. Odoo naive datetimes are
interpreted explicitly as UTC and converted with the IANA zone
`America/Asuncion`; timezone-aware values are converted from their represented
instant. Because SIFEN validation 1004 requires `dFecFirma` not to be later than
the SIFEN reception clock and publishes no tolerance, newly generated signing
times use an explicit 60-second safety margin. Already serialized retry metadata
is preserved so the margin is not applied twice. SIFEN documents the NTP hosts
`aravo1.set.gov.py` and `aravo2.set.gov.py` for operational clock synchronization.

## Future QR Image

QR image rendering is not implemented yet.

QR payload generation happens after digital signature because the QR input includes the XMLDSig `DigestValue`. Future QR image/rendering work should consume the generated QR string. CSC must not be used for CDC generation.

See [ADR-009 CSC Only For QR](../ADR/ADR-009-csc-only-for-qr.md).
See [ADR-011 Paraguay Digital Signature Strategy](../ADR/ADR-011-paraguay-digital-signature-strategy.md).

## Future SIFEN

Stage 8 begins SIFEN test integration with `PySifenTestSubmissionService`.

Stage 8.1 adds a pure service for test-environment submission. It:

* requires a Paraguay document in `test` environment
* requires an HTTPS SIFEN test endpoint supplied by the caller
* rejects endpoint URLs containing credentials, query strings, or fragments
* validates the final signed XML locally with `PyXsdValidationService.validate_final_signed_xml` before transport
* builds the official SOAP 1.2 `rEnviDe/dId/xDE/rDE` envelope around the final `rDE`
* delegates HTTP transport through an injectable transport callable
* sanitizes retryable transport errors so raw exception text is not returned for later persistence
* normalizes accepted, rejected, SOAP fault, malformed, and retryable transport outcomes into a secret-free result dictionary
* returns request and response SHA-256 hashes for later `fiscal.transmission` persistence

Stage 8.2 adds `PySifenSandboxTransport`, the first concrete transport for calling the official SIFEN test environment. The transport:

* posts the SOAP request over HTTPS
* builds an `ssl.SSLContext` with mutual TLS client certificate material
* rejects non-HTTPS endpoints even when the transport is called directly
* consumes the existing `fiscal.credential` reference and `FiscalCredentialProviderRegistry` provider boundary
* supports transient PKCS#12 and PEM pair material returned by a provider
* keeps transport injectable for tests and does not require live sandbox access during automated tests
* separates connection failures, TLS failures, HTTP failures, SOAP faults, and authority business responses through typed errors and normalized metadata
* returns HTTP error response bodies for normal response normalization instead of treating them as connection failures

`ExternalSecretPkcs12MaterialProvider` retrieves deployment-mounted PKCS#12 material and its optional password through the configured `file://` and `env://` references. It returns transient material through the existing provider contract.

The transport does not persist private keys, PKCS#12 bundles, PEM content, passwords, or certificates to Odoo records and does not log secret material or temporary file paths. Python's stdlib `ssl` API requires filesystem paths for `load_cert_chain`, so the transport writes certificate and private-key PEM bytes only to OS-managed restrictive temporary files while constructing the `ssl.SSLContext`; those files are unlinked when context construction completes.

The submission service retains a non-mTLS development fallback transport for tests, but it rejects calls that include a mutual-TLS credential. Real SIFEN sandbox mTLS use must inject `PySifenSandboxTransport`.

Stage 8.3 extends `PySifenSandboxTransport` with a live sandbox connection verification operation. The verifier:

* builds the same mutual-TLS `ssl.SSLContext` used by sandbox submission
* performs an HTTPS `HEAD` request so it does not require a valid DE payload
* treats HTTP errors as proof that DNS, TCP, and TLS reached the remote authority
* returns secret-free categories for configuration, credential, DNS, TCP, TLS, client-certificate rejection, server-certificate trust, endpoint reachability, and HTTP response outcomes
* keeps `urlopen` injectable so automated tests use stubs and do not require live sandbox access

Stage 8.4 adds `PySifenSubmissionPipelineService`, a test-environment orchestration layer. It executes the existing Paraguay services in order:

* signing pipeline
* signed XML attachment readback
* QR payload generation
* final XML preparation with `gCamFuFD/dCarQR`
* local final SIFEN XSD validation
* SIFEN test submission

The pipeline aborts after the first failure and returns a normalized, secret-free result containing CDC, signed XML SHA-256, XMLDSig digest, certificate fingerprint, QR hash/payload, authority status, authority message, request hash, and response hash when available. It does not expose certificate bytes, private keys, CSC values, passwords, PKCS#12 bundles, PEM content, or raw secret material.

Stage 8.5 adds idempotent `fiscal.transmission` persistence for normalized SIFEN test submission attempts. The persistence service calls `PySifenSubmissionPipelineService`, then creates or updates a submit transmission for the document. It stores only non-secret data:

* country and environment
* fiscal document reference
* CDC
* submission status and authority code/message
* request and response SHA-256 hashes
* signed XML SHA-256
* QR hash
* started and finished timestamps

The transmission record does not store private keys, certificates, CSC values, passwords, raw SOAP envelopes, raw signed XML, PKCS#12 bundles, PEM content, or raw secret material.

Stage 8.6 adds `PySifenRetrySchedulerService` for retry scheduling only. It evaluates existing `fiscal.transmission` records and schedules retries only for retryable SIFEN test transport failures. It does not retry accepted submissions, authority rejections, malformed requests, business validation failures, SOAP faults, or permanent failures. Scheduling increments a retry counter, sets `next_retry_at`, applies exponential backoff, honors a maximum retry limit, and stores only secret-free retry state.

Stage 8.7 adds `PySifenRetryExecutionService` for callable retry execution. It selects only `fiscal.transmission` records whose retry is scheduled and due, reuses `PySifenTransmissionPersistenceService` and `PySifenSubmissionPipelineService` for the actual retry attempt, clears consumed schedules, and either stops retrying or reschedules through `PySifenRetrySchedulerService` when the normalized result is still retryable. It does not add cron jobs, background workers, automatic execution, production submission, or new submission logic.

Stage 8.8 adds `py.sifen.retry.runner` as a manual Odoo runner plus a disabled-by-default cron record. The runner delegates to `PySifenRetryExecutionService`, applies a small batch limit, selects due retries through the existing execution service, and logs only secret-free summary counts. Enabling the cron remains an administrator decision because sandbox retry execution still depends on configured submission inputs and credential boundaries.

Stage 8.15 adds automatic credential resolution at the persistence boundary. `PySifenTransmissionPersistenceService` defaults to `PySifenCredentialProvider`, resolves credentials only when callers provide neither `PySifenRuntimeCredentials` nor legacy explicit credential arguments, and passes the resolved runtime object transiently into the existing submission pipeline. Supplied runtime credentials bypass automatic resolution, while certificate, private-key, password, endpoint, mutual-TLS credential, and timeout arguments remain backward compatible. Retry execution reuses the same persistence service and therefore inherits automatic resolution. A credential-provider failure propagates before pipeline execution and before any `fiscal.transmission` is created.

Retry resolves business data only from the unique current `paraguay_payload_json`. Payload and unsigned XML now retain explicit `current`/`superseded` history and validate SHA-256, document/tenant/company scope and exact CDC. A sole legacy payload remains compatible only when it is the only valid candidate; ambiguous history fails closed.

Every scheduled or manual retry uses `PySifenRetrySigningTimeService`. Its injectable fresh reference instant is serialized by the centralized `America/Asuncion` policy with the existing 60-second margin. Historical `signing_time` is evidence only and is never reused. Safe provenance metadata links payload → unsigned XML → signed XML → QR → final rDE, while old versions remain auditable. Explicit scheduler arguments cannot override the current payload or retry clock. The cron remains disabled by default.

Stage 8.17 adds the configuration-driven `PySifenSandboxTransport.verify_document_connection()` preflight for Paraguay TEST documents. It resolves the endpoint, timeout, and mutual-TLS credential from the document's runtime credentials and delegates exclusively to the existing `verify_connection()` HEAD probe. It does not generate a payload or XML, create a POST request, or submit a document. An explicitly supplied credential provider always takes precedence, including a falsey provider instance. Fixed `ValidationError` messages with suppressed exception chaining prevent provider text, PKCS#12 and SSL details, passwords, certificate contents, and parser details from escaping.

Stage 8.22 completes the live TEST mTLS preflight operation. Configure and validate the qualified PKCS#12 credential as described above, ensure the TEST document references the active Paraguay adapter, and run from an Odoo shell:

```python
from odoo.addons.einvoice_py.services import PySifenSandboxTransport

result = PySifenSandboxTransport(env).verify_document_connection(document)
```

This operation loads the `external_secret` material, constructs the client-certificate SSL context with the system trust store, resolves DNS, opens TCP, performs the TLS handshake, verifies the server certificate, and issues an HTTPS `HEAD` to the configured TEST endpoint. It never builds a payload, SOAP envelope, or POST request and never submits a DE.

Result categories are:

* `configuration_invalid`: document or adapter configuration cannot support the preflight.
* `credential_absent`: the required active `mutual_tls` binding is unavailable.
* `credential_invalid`: installed credential material or metadata is invalid.
* `credential_password_invalid`: the installation inspection could not decrypt the PKCS#12.
* `certificate_expired`: the installation inspection reports an expired client certificate.
* `dns_failure`: the TEST hostname could not be resolved.
* `tcp_failure`: the TCP connection could not be opened before the timeout.
* `tls_failure`: the TLS handshake failed without a more specific safe classification.
* `client_certificate_rejected`: the peer returned a recognized TLS alert rejecting the client certificate.
* `server_certificate_untrusted`: normal server-certificate verification failed.
* `endpoint_reachable`: TLS succeeded and a normal HTTP response was received.
* `http_response_received`: TLS succeeded and a non-2xx HTTP response was received.

Both `endpoint_reachable` and `http_response_received` set `ok=True`: any HTTP status from the mTLS-required SIFEN endpoint proves that the configured client-certificate connection and endpoint access reached the HTTP layer, regardless of whether the status is 2xx. The result and the adapter's `sifen_test_mtls_preflight` metadata contain only status, category, HTTP status, safe booleans, and timestamp. They never contain complete paths, environment-variable names, provider exception text, certificate bytes, private keys, or passwords.

Stage 8.18 makes synchronous DE submission compliant with the DNIT v150 wire structure. Requests use SOAP 1.2 with `application/soap+xml` and contain `rEnviDe`, a mandatory `dId`, `xDE`, and the signed `rDE` nested under `xDE`. The taxpayer-controlled, sequential `dId` is generated from the existing persistent `fiscal.adapter.config.sequence_id` and must be numeric with no more than 15 digits. Stage test configuration uses `no_gap`, but DNIT does not explicitly require gapless allocation; `no_gap` is therefore not treated as a protocol requirement.

Stage 8.24A introduces TEST-only recovery for an uncertain synchronous POST. A transport timeout marks the submission as ambiguous and prevents any further POST for the same tenant, company, and CDC until a safe policy decision follows Consulta DE. `PySifenDocumentQueryService` queries by CDC using SOAP 1.2, the existing credential provider and mTLS sandbox transport. `PySifenReconciliationService` locks the document and applies the result. Backward-compatible Stage 8.24A names remain available.

An authority result of `0422` confirms remote approval and marks the fiscal document accepted. `accepted_at` and `authority_status` are populated, while `authority_receipt_ref` is updated only when SIFEN returns `dProtAut`. The original submission is immutable. Result `0420` means only that an approved DTE was not found and is persisted as `reconciliation_not_found`; it is not a fiscal rejection. `PySifenRetryEligibilityService` may authorize one operator-triggered resend of the same DE/CDC only when the later successful `0420` is explicitly linked to the same ambiguous, post-started submission and exact tenant/company/environment/country/CDC scope. Missing hashes or linkage, acceptance, a newer unresolved submit, a later contradictory query, or a CDC change fails closed. Automatic retry remains forbidden. The official service has no separate confirmed-rejection result. Timeout, HTTP/TLS failure, SOAP Fault, malformed response, unsupported result, or CDC mismatch remains unresolved. Repeating a completed reconciliation is idempotent.

Each query persists a separate `status_query` audit record: sanitized HTTPS endpoint, HTTP status, duration, request/response SHA-256, authority code/message/time, safe result category, query time and links to the relevant submission attempts. Raw response XML, CSC, certificate, key and password material are excluded. Automatic reconciliation is limited to ambiguous/manual-review submissions; an operator diagnostic is allowed only after a real prior submission. Accepted documents and never-submitted drafts are not queried automatically.

DE submission now commits a narrowly scoped durable attempt independently of
the caller transaction. `pending` means local preparation began but the
pre-POST marker did not run; `sent` means request SHA-256 and complete artifact
provenance were committed immediately before transport and the remote outcome
must be treated as unknown until a result or Consulta DE resolves it. The
caller cursor is never explicitly committed. Consulta DE itself retains its
existing transaction behavior and remains TEST-only.

## Cancellation and number inutilization

Emitter events use the official SOAP 1.2 event endpoint and v150 event schemas.
`PySifenCancellationService` accepts only an approved Paraguay document with a
CDC and authority acceptance time. A Factura Electrónica must be inside the
official 48-hour window; other supported DTE types use 168 hours. The reason is
5–500 characters. Code `0600` is the only locally recognized success and moves
the document to `cancelled` while preserving `accepted_at`, the accepted
transmission and all DE artifacts. Rejection leaves the document accepted.
Timeout, HTTP/TLS uncertainty, SOAP Fault or malformed XML creates a manual
review cancellation transmission and blocks another cancellation POST.

`PySifenInutilizationService` handles a correlated range of 1–1000 unused
seven-digit numbers scoped by tenant, company, environment, timbrado,
establishment, point of issue and document type. The range cannot overlap any
locally issued number or prior inutilization evidence. The reason is 5–150
characters, and reporting is limited to the first 15 days of the month after
the recorded numbering error. It creates `fiscal.py.inutilization`; no dummy DE,
CDC, CSC or signed document artifact is generated. Identical repeated calls are
idempotent, and ambiguous evidence is never automatically retried.

Both operations sign `rEve` using the existing `xml_signing` credential and use
the existing `mutual_tls` binding. They persist only safe endpoint, HTTP status,
duration, request/response hashes, event identity, authority code/message,
protocol and timestamp. Raw event XML and secret material are excluded.

## SIFEN TEST homologation readiness

Stage 8.25 checks the existing document-scoped TEST profile without making a network call:

```python
from odoo.addons.einvoice_py.services import PySifenTestReadinessService

report = PySifenTestReadinessService(env).check(document=document)
```

Configure the profile in this order:

1. Select an active Paraguay issuer in the TEST environment with its RUC and DV.
2. For TEST homologation, configure the timbrado number as the RUC without its DV.
3. Set the timbrado start date to the date shown on Form 364.
4. Configure both establishment and expedition-point codes as exactly three numeric digits.
5. Select an active TEST CSC with both IdCSC and its secret value.
6. Select an active Paraguay TEST adapter with an HTTPS endpoint and persistent `sequence_id`.
7. Configure one active `external_secret`/`pkcs12` credential. Its `secret_ref` points to a deployment-managed PKCS#12 file and its `password_secret_ref` points to a deployment-managed `file://` or `env://` secret.
8. Bind that credential once to `xml_signing` and once to `mutual_tls`.
9. Run the existing qualified-certificate installation validation, then run the readiness check.

The readiness status is one of `fiscal_configuration_invalid`, `fiscal_configuration_ready`, `csc_missing`, `certificate_reference_missing`, `certificate_password_missing`, `certificate_configuration_invalid`, or `ready`. The result never returns the CSC secret, PKCS#12 path, password reference, password, certificate bytes, or provider exception text. A missing certificate or password reference produces a normal not-ready report; it does not crash normal Odoo operations. The check does not create a certificate, open a network connection, or submit a DE.

## SIFEN v150 XMLDSig

Stage 8.26 uses the existing Paraguay signing pipeline. `PySignedXmlPreparationService` first prepares the unsigned `rDE/DE`; `PyXmlSignatureService` then signs exactly that `DE`, and local verification runs before any later QR or final-document stage.

The signed node is the single `DE` in the official SIFEN namespace. Its `Id` is the complete CDC, and the reference is exactly `URI="#{CDC}"`. The XMLDSig `Signature` is a direct child of `rDE`, immediately after `DE`. No XAdES `QualifyingProperties`, `SignedProperties`, namespaces, or profile are generated.

The fixed algorithm URIs are:

* CanonicalizationMethod: `http://www.w3.org/TR/2001/REC-xml-c14n-20010315`
* Transform: `http://www.w3.org/2000/09/xmldsig#enveloped-signature`
* SignatureMethod: `http://www.w3.org/2001/04/xmldsig-more#rsa-sha256`
* DigestMethod: `http://www.w3.org/2001/04/xmlenc#sha256`

`X509Certificate` contains only the DER certificate encoded as Base64. Certificate PEM headers, private keys, passwords, and unrelated text are never inserted into the signed XML. Do not pretty-print, re-indent, reorder, or mutate signed XML after signature generation: any modification to signed content invalidates the digest or signature.

The credential provider normalizes supported PKCS#12 material into the certificate and private-key inputs consumed by the signer; the signer does not read secret references or PKCS#12 files. XML signing proves document integrity and signer possession of the private key. Mutual TLS authenticates the HTTPS client connection. They are separate logical credential bindings even when both use the same qualified certificate.

## SIFEN v150 QR payload and gCamFuFD

Stage 8.27 uses `PySifenQrBuilder` after XMLDSig and before final XSD/submission processing. It produces URL text and the XML fragment only; it does not render PNG/SVG, call SIFEN, or use SOAP.

The parameter order is fixed:

1. `nVersion`
2. `Id`
3. `dFeEmiDE`
4. exactly one of `dRucRec` or `dNumIDRec`
5. `dTotGralOpe`
6. `dTotIVA`
7. `cItems`
8. `DigestValue`
9. `IdCSC`

`nVersion` is `150`, and `Id` is the complete CDC matching `DE@Id`. `dFeEmiDE` is the lowercase hexadecimal representation of its UTF-8 XML text. `DigestValue` is likewise the lowercase hexadecimal representation of the UTF-8 Base64 text already present in XMLDSig; it is not Base64-decoded and is not hashed again. Totals are copied exactly from the signed XML without floating-point conversion, and `cItems` is the count of `gCamItem` groups rather than a quantity sum. `IdCSC` preserves leading zeroes.

The ordered parameter text, excluding the URL, is concatenated directly with the transient CSC secret and hashed with SHA-256 to obtain the 64-character lowercase `cHashQR`. The CSC secret is never returned or placed in XML. TEST uses `https://ekuatia.set.gov.py/consultas-test/qr`; PRODUCTION uses `https://ekuatia.set.gov.py/consultas/qr`. Both environments share the same builder logic.

The generated fragment is:

```xml
<gCamFuFD xmlns="http://ekuatia.set.gov.py/sifen/xsd">
  <dCarQR>...</dCarQR>
</gCamFuFD>
```

The XML library escapes ampersands when serializing `dCarQR`; callers must not insert `&amp;` manually. The pipeline appends this fragment without pretty-printing or re-indenting the already signed XML.

## Final rDE assembly and XSD validation

Stage 8.28 adds `PySifenRdeAssembler` as the single final-document assembly boundary. It accepts the already signed `rDE` and the `gCamFuFD` generated by `PySifenQrBuilder`, validates the CDC and required inputs, and produces this exact v150 order:

```xml
<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd">
  <dVerFor>150</dVerFor>
  <DE Id="...">...</DE>
  <Signature xmlns="http://www.w3.org/2000/09/xmldsig#">...</Signature>
  <gCamFuFD>
    <dCarQR>...</dCarQR>
  </gCamFuFD>
</rDE>
```

Assembly is append-only: it does not rebuild, reorder, re-indent, or pretty-print the signed content. The resulting XMLDSig therefore remains locally verifiable. The assembler delegates final validation to the existing `PyXsdValidationService` and its vendored official SIFEN v150 XSD set. Its immutable result includes the final XML, parsed XML document, CDC, QR URL, validation status, and structured XSD errors with message, line, column, element, and path when available. It performs no SOAP construction, transport, mutual TLS, or network communication.

## SOAP 1.2 envelope assembly

Stage 8.29 adds `PySifenSoapEnvelopeBuilder` for the XML-only synchronous request boundary. It accepts an XSD-valid final `rDE` and a numeric `dId` of 1–15 digits, then produces:

```xml
<Envelope xmlns="http://www.w3.org/2003/05/soap-envelope">
  <Header/>
  <Body>
    <rEnviDe xmlns="http://ekuatia.set.gov.py/sifen/xsd">
      <dId>...</dId>
      <xDE>
        <rDE>...</rDE>
      </xDE>
    </rEnviDe>
  </Body>
</Envelope>
```

Stage 8.29A audits this structure against Manual Técnico v150 sections 7.4, 7.9, 7.10, and 9.1 plus the official `WS_SiRecepDE_v150.xsd`. The TEST WSDL is published at `https://sifen-test.set.gov.py/de/ws/sync/recibe.wsdl?wsdl`; the POST endpoint is the same URL without `?wsdl`. The contract uses SOAP 1.2, UTF-8 XML, document/literal messages, the SOAP namespace `http://www.w3.org/2003/05/soap-envelope`, and the SIFEN namespace `http://ekuatia.set.gov.py/sifen/xsd`. The payload root is `rEnviDe`, in the exact `dId`, `xDE`, `rDE` order. Namespace prefixes are lexical aliases rather than element identity; the builder uses default namespace boundaries to comply with the SIFEN prohibition on prefixes in the data XML and to avoid changing inclusive XMLDSig canonicalization.

The official Manual and XSD do not impose a SOAP action value. The builder therefore reports no action by default; the existing SOAP 1.2 transport can add a configured action parameter when explicitly supplied. HTTP transport uses `application/soap+xml; charset=utf-8`; no separate SOAP 1.1 `SOAPAction` header is generated.

The builder performs no HTTP, mutual TLS, response parsing, retry, or network operation. It inserts the complete `rDE` root-element byte sequence once, removing only the standalone XML declaration because an XML declaration is not legal inside `xDE`. It does not rebuild signed nodes or apply normalization, indentation, or pretty-printing. The namespace boundary is chosen so SOAP namespace declarations do not alter the inclusive canonicalization context of the signed `DE`; local XMLDSig verification remains valid after wrapping. Its immutable result contains SOAP bytes, the parsed envelope, `SiRecepDE` service/action metadata, CDC, and `dId`. The existing submission service retains persistent sequence allocation and delegates only envelope construction.

## SIFEN TEST SOAP client

Stage 8.30 adds `PySifenSoapClient` for the HTTPS POST of an already assembled SOAP envelope. The client does not generate, normalize, or modify XML. Before transport it verifies the audited SOAP 1.2 hierarchy, numeric `dId`, single signed `rDE`, and successful local XSD validation. It then delegates the original byte string to the existing `PySifenSandboxTransport` with `application/soap+xml; charset=utf-8`, the configured endpoint and timeout, and the configured mutual-TLS credential.

The existing credential registry and `external_secret` PKCS#12 provider load material only at the transport boundary. The SSL context uses system server trust, presents the client certificate, and explicitly requires TLS 1.2 or newer. The client never logs credential material and does not persist certificates, keys, passwords, CSC, requests, or responses.

The immutable result contains the HTTP status, sorted response-header pairs, raw response bytes, parsed XML when available, elapsed milliseconds, endpoint, and request `dId`. Fixed categories distinguish success, timeout, DNS failure, connection failure, TLS handshake failure, local certificate validation failure, HTTP error, SOAP Fault, and malformed or empty XML. These categories are transport/protocol facts only; authority business interpretation, retry, Consulta DE, persistence, production, and asynchronous submission remain outside the client.

## Synchronous siRecepDE response parsing

Stage 8.31 adds the side-effect-free `PySifenRecepDeResponseParser`. Its sources of truth are Manual Técnico v150 sections 9.1.3 and 12.3.1.3 plus the official `WS_SiRecepDE_v150.xsd` and `protProcesDE_v150.xsd`. The SOAP 1.2 Body contains exactly one SIFEN `rRetEnviDe`, which contains exactly one `rProtDe`. In the current official XSD, `rProtDe/Id` is both the response identifier and processed CDC, `dFecProc` is mandatory processing time, `dDigVal`, `dEstRes`, and `dProtAut` are optional, and `gResProc` occurs zero to 100 times. Each processing-result group may contain `dCodRes` and `dMsgRes`. The parser retains every group in order while exposing the first as the primary code/message for compatibility. The originating request `dId` is retained separately.

The Manual defines the authority states `Aprobado`, `Aprobado con observación`, and `Rechazado`; chapter 12 defines `0260` as successful DE authorization and `1001`/`1002` as CDC/document duplication validations. Approved states and `0260` classify as accepted. Duplicate codes classify separately from other rejected outcomes. SOAP Fault, HTTP error, malformed response, and unknown official codes are separate results. HTTP 200 alone never produces acceptance. Unknown future codes preserve the official code and message and return a warning instead of raising. Although the finite result model reserves `processing_pending`, synchronous `siRecepDE` v150 defines no such authority outcome; `0361` is the processing state of the different `siResultLoteDE` service and is intentionally not mapped here.

SOAP Fault parsing extracts SOAP 1.2 Code, optional Subcode, Reason, and Detail without treating the fault as a SIFEN business result. Namespace comparison uses namespace URIs, not lexical prefixes. Empty bodies, non-XML, missing SOAP Body, wrong namespaces, missing `rRetEnviDe/rProtDe`, invalid cardinality, missing mandatory `dFecProc`, and conflicting accepted/rejected fields are classified as malformed. The immutable result preserves raw bytes for its caller, but `repr` and `str` redact raw and parsed content. The parser emits no logs and performs no persistence, retry, Consulta DE, submission, or network call.

## End-to-end SIFEN TEST submission

Stage 8.32 adds `PySifenSubmissionService.submit()` as the first non-persistent live TEST entry point. It resolves the document's runtime credentials and executes:

```text
Payload → unsigned rDE → signing preparation/CDC validation → XMLDSig
→ QR/gCamFuFD → final rDE/XSD → SOAP 1.2 → mTLS HTTPS POST
→ siRecepDE response parsing
```

No algorithm or transport is reimplemented. A normal authority response returns `PySifenRecepDeResponseResult`; SOAP Fault and business rejection remain parsed authority results. A failure before a response returns `PySifenSubmissionFailureResult` with a fixed safe stage/category. The operation does not create a `fiscal.transmission`, update the document, retry, call Consulta DE, or generate KuDE. Consequently, operators must use it only for the controlled first TEST submission and must not repeat it blindly after a timeout.

### Official TEST contract revalidation

The DNIT technical portal still identifies Manual Técnico v150 as current. Manual v150 sections 7.4, 7.9, 7.10, and 9.1 continue to define the synchronous `SiRecepDE` operation, SOAP 1.2 namespace `http://www.w3.org/2003/05/soap-envelope`, SIFEN namespace `http://ekuatia.set.gov.py/sifen/xsd`, UTF-8 XML, and the `rEnviDe/dId/xDE/rDE` body. The official TEST service is:

```text
https://sifen-test.set.gov.py/de/ws/sync/recibe.wsdl
```

Transport uses `application/soap+xml; charset=utf-8`, no SOAP 1.1 `SOAPAction` header, TLS 1.2 or newer, server-certificate verification, and the configured qualified client certificate for mTLS. A public WSDL download without the client-authenticated TEST session currently returns the SIFEN BIG-IP logout page; therefore the contract remains the v150 WSDL/XSD already audited in Stage 8.29A, with no evidence of a changed operation or namespace.

### Controlled submission procedure

The authoritative field checklist is
[SIFEN TEST Configuration](CONFIGURATION.md). Operational safeguards and
response handling are consolidated in the
[Homologation Runbook](HOMOLOGATION_RUNBOOK.md).

Before running the operation, complete all of the following:

1. Use one active Paraguay `fiscal.document` in environment `test`, with complete issuer, establishment, point of issue, TEST timbrado, document numbering, receiver, items, totals, CDC, and signing timestamp inputs.
2. Assign one active matching `fiscal.adapter.config` with country `PY`, environment `test`, endpoint `https://sifen-test.set.gov.py/de/ws/sync/recibe.wsdl`, a numeric `sequence_id`, and a positive timeout.
3. Configure the TEST CSC record with its four-digit `id_csc` and secret.
4. Configure an active `external_secret` PKCS#12 credential with `file://` material and a `file://` or `env://` password reference. Never place either value in source control.
5. Bind the credential as both `xml_signing` and `mutual_tls` (or use two valid credentials). Tenant, company, environment, RUC, validity, key usages, and certificate/private-key correspondence must match.
6. Run qualified-certificate installation validation and `verify_document_connection()` successfully.
7. Confirm that the selected CDC is not accepted or ambiguous. The persistence
   service also enforces this under a document row lock.

From an Odoo shell connected to the configured database, run exactly one controlled request:

```python
from odoo import fields
from odoo.addons.einvoice_py.services.py_payload_builder import PyPayloadBuilder
from odoo.addons.einvoice_py.services.py_sifen_transmission_persistence_service import (
    PySifenTransmissionPersistenceService,
)

document = env["fiscal.document"].browse(DOCUMENT_ID).exists()
payload = PyPayloadBuilder(env).build(document)
persisted = PySifenTransmissionPersistenceService(env).submit_and_persist(
    document=document,
    payload=payload,
    signing_timestamp=fields.Datetime.now(),
)
env.cr.commit()
persisted
```

The request is UTF-8 SOAP 1.2 containing one signed, QR-bearing, XSD-valid `rDE` under `rEnviDe/dId/xDE`; the HTTPS layer presents the configured client certificate. A successful authority result has classification `accepted`, `dEstRes` equal to `Aprobado` or `Aprobado con observación`, and normally code `0260`; `dProtAut` is present only when SIFEN returns it.

Interpret failures as follows:

* `configuration`: inspect adapter scope, endpoint, sequence, bindings, CSC, and external-secret references.
* `build`: correct missing or invalid fiscal payload fields and CDC consistency.
* `signing`: validate PKCS#12 password, RSA identity, certificate/key match, and certificate validity/usages.
* `qr`: validate CSC, receiver identity, totals, item count, CDC, and DigestValue.
* `xsd_validation`: inspect the local XSD report before any network attempt.
* `soap`: verify final `rDE`, sequence output, SOAP 1.2 structure, and local XSD status.
* `transport`: use the safe category to distinguish DNS, connection, timeout, TLS, or certificate validation. After a timeout, do not resend; reconcile the CDC first.
* `soap_fault`: inspect the safe Fault code/reason and retain the raw response securely.
* `rejected`, `duplicate`, or `unrecognized_official_code`: retain the official code/message and do not infer acceptance from HTTP 200.

The current delivery baseline reports 589 counted tests across 523 test methods.
Production service composition, configuration-driven
sandbox preflight, SOAP 1.2 synchronous framing, TEST-only ambiguous-submission
reconciliation, local homologation readiness, XMLDSig signing, QR/`gCamFuFD`,
final `rDE` assembly/XSD validation, deterministic SOAP wrapping, the mocked
TEST SOAP client, deterministic authority-response parsing, and mocked
end-to-end TEST composition are covered. Automated tests make no live SIFEN
calls. The accepted live baseline separately proves authority interoperability
for the tested certificate, CSC, fiscal configuration, and invoice profile.

Still pending:

* remaining official SIFEN TEST homologation cases
* adoption of the durable pre-POST primitive by emitter/receiver events and queries
* production connection preflight
* retry cron activation
* operational monitoring and production go-live

Future SIFEN work should build on:

* normalized Paraguay payload
* XML generation
* digital signature
* QR generation
* local final XSD validation
* SIFEN test submission service
* SIFEN sandbox mutual-TLS transport
* SIFEN sandbox mTLS connection verification
* SIFEN test submission pipeline orchestration
* SIFEN fiscal transmission persistence
* SIFEN retry scheduling
* SIFEN callable retry execution
* SIFEN automatic retry runner
* authority response normalization
* retry/error handling

## KuDE PDF representation

The invoice KuDE implementation follows Manual Técnico SIFEN v150 chapter 13.
It is a simplified graphical representation of the DTE, not a replacement for
the signed XML. `PyKudeService` accepts one persisted Paraguay
`fiscal.document`, reads only its latest `paraguay_payload_json` and current
`paraguay_qr_payload`, renders a deterministic PDF, and persists a
`paraguay_kude_pdf` fiscal artifact. It never reads XML, SOAP requests,
authority responses, credentials or CSC, and it performs no network operation.

The submission pipeline persists the exact QR URL produced from the final
signed artifact. KuDE generation embeds that persisted URL unchanged; it never
recalculates `cHashQR`. Each PDF metadata record contains only safe attachment
identifiers and SHA-256 hashes for its payload and QR inputs. The PDF and QR
attachments use current/superseded metadata under a document row lock:
byte-identical regeneration is idempotent, while changed input creates a new
current version and keeps every prior version for audit.

ReportLab is used directly rather than HTML/wkhtmltopdf. Its invariant mode,
explicit pagination and exact QR dimensions make output independent of browser
engine, CSS, host font and external-process differences. The KuDE includes the
official invoice header in a compact bordered block, issuer/timbrado and
document identity, a two-column operation/receiver block, bordered item and
totals tables, page numbering, consultation information, grouped CDC and the
QR on the first page. Numeric columns are right-aligned, Guaraní amounts use a
deterministic thousands presentation, and item descriptions wrap without
truncation. The optional company logo is read from the existing Odoo company
record at render time, preserves its aspect ratio and is never copied into a
new fiscal artifact. Missing or invalid branding leaves a neutral text header.
The QR is rendered at 28 mm, above the Manual's 25 mm minimum. XML values are
represented; no new business calculation is performed.

Generate or regenerate locally from Odoo shell:

```python
from odoo.addons.einvoice_py.services.py_kude_service import PyKudeService

document = env["fiscal.document"].browse(DOCUMENT_ID).exists()
result = PyKudeService(env).generate(document=document)
result.attachment_id, result.sha256, result.page_count
```

Preconditions are a current persisted payload and exact QR artifact for the
same CDC. Missing, malformed or hash-inconsistent inputs fail safely. The
initial renderer supports Factura Electrónica only; credit notes, debit notes,
events and their distinct official representations remain unsupported.
Historical documents without an exact QR artifact are not silently rebuilt
from CSC.

Official basis:

* Manual Técnico SIFEN v150 §13.1 defines KuDE as a simplified graphical representation.
* §§13.3–13.4 define pagination, header, items, totals, consultation data, CDC and QR content.
* §13.5 permits standard paper formats and states the published models are referential.
* §13.8 requires an ISO/IEC 18004 QR with a minimum total size of 25 mm.

The architecture decision and renderer trade-off are recorded in
[ADR-015](../ADR/ADR-015-paraguay-kude-from-persisted-payload.md).

## Accepted document delivery

`PyFiscalDocumentDeliveryService` exposes the recipient-facing evidence for an
accepted Paraguay document. It resolves the current deterministic KuDE PDF and
the current final signed `rDE`, validates both stored hashes, confirms that the
XML contains the matching `DE`, valid XMLDSig `Signature`, and `gCamFuFD`, and
returns immutable file descriptors. It never selects unsigned XML, the signed pre-QR
artifact, superseded artifacts, normalized payloads, QR payloads, manifests,
responses, credentials, or certificate material.

Delivery requires two independent facts: a coherent document state and
persisted authority-backed acceptance. The accepted evidence must belong to
the same document, tenant, company, environment and CDC. It is either an
accepted synchronous `submit` transmission with official result `0260`, or an
accepted Consulta DE reconciliation with `0422`, exact returned CDC, normalized
`approved` result and linkage to the prior submission. Ambiguous, incomplete or
contradictory evidence is rejected. Setting `state = accepted`, adding local
metadata, or installing artifacts does not make a document deliverable.

Recipient filenames are deterministic and contain no database identifiers:
`FE-001-001-0000006.pdf` and `FE-001-001-0000006.xml`. The fiscal document form
shows **Download KuDE** and **Download XML** only for accepted Paraguay
documents. The authenticated routes use the document UUID, then enforce the
normal tenant record rule and active-company boundary before resolving the
artifacts; no arbitrary attachment-ID download is exposed.

`prepare_email()` suggests the persisted receiver email, a short subject/body,
and exactly those two immutable attachments. It does not send mail or create an
audit record. Rejected, ambiguous, unfinished, failed, and cancelled documents
are not final-recipient deliverables. Cancellation behavior remains pending
the authority event/cancellation implementation.

## KuDE preview

The fiscal document form exposes **Preview KuDE** for complete, non-cancelled
Paraguay invoices outside `validation_error`. The action uses the separate,
authenticated `/einvoice_py/preview/<document UUID>/kude` route and generates
`PREVIEW-FE-<number>.pdf` on demand from the current persisted payload.

Preview output is visibly marked **VISTA PREVIA — SIN VALIDEZ FISCAL** and
retains the TEST/PRODUCTION environment label. It shares only the visual
renderer with the fiscal KuDE; its evidence and delivery semantics remain a
separate boundary. It never reads CSC,
credentials, authority responses or final XML. It neither requires nor creates
a fiscal QR: the QR area contains a non-functional preview placeholder.
Preview PDFs are not cached or persisted as fiscal attachments, do not enter
artifact version history and can never be selected by recipient delivery.

Preview does not mutate state, create a transmission, simulate `0260`/`0422`,
or satisfy delivery eligibility. Accepted documents may also be previewed, but
their preview remains distinct from their authority-backed KuDE/XML delivery.

Historical accepted documents created before `paraguay_rde_final` persistence
fail closed. Their final XML may be installed only by a separately audited
migration from exact persisted evidence; delivery never rebuilds it from a
pre-QR signature, QR payload, SOAP request, or authority response.

## Related Documents

* [Documentation Home](../README.md)
* [Documentation Index](../index.md)
* [Architecture](../ARCHITECTURE.md)
* [Roadmap](../ROADMAP.md)
* [Paraguay Processing Diagram](../diagrams/paraguay-processing.mmd)
* [Fiscal State Machine](../diagrams/fiscal-state-machine.mmd)
* [SIFEN TEST Homologation Matrix](HOMOLOGATION_MATRIX.md)
* [ADR-008 Paraguay Numbering Before CDC](../ADR/ADR-008-paraguay-numbering-before-cdc.md)
* [ADR-009 CSC Only For QR](../ADR/ADR-009-csc-only-for-qr.md)
* [ADR-010 SIFEN XSD Validation Strategy](../ADR/ADR-010-sifen-xsd-validation-strategy.md)
* [ADR-011 Paraguay Digital Signature Strategy](../ADR/ADR-011-paraguay-digital-signature-strategy.md)
* [ADR-012 Paraguay Qualified Certificate Lifecycle](../ADR/ADR-012-paraguay-qualified-certificate-lifecycle.md)
* [ADR-015 Paraguay KuDE From Persisted Payload](../ADR/ADR-015-paraguay-kude-from-persisted-payload.md)
* [ADR-016 Paraguay SIFEN Emitter Events](../ADR/ADR-016-paraguay-sifen-emitter-events.md)

## Next Recommended Reading

## Receiver events

The official v150 receiver choices are notification of receipt (`10`),
conformity (`11`, partial or total), disconformity (`12`) and unknown document
(`13`). `PySifenReceiverEventService` signs `rEve` and reuses SOAP 1.2, the
credential provider and mTLS; CSC is not involved.

Each attempt creates a scoped `fiscal.py.receiver.event` with the receiver
snapshot, target CDC, event identity, hashes, safe endpoint, duration and
authority evidence. Original XML, KuDE and DE transmissions remain immutable.
The service enforces 45-day registration and 15-day corrective windows,
partial-before-total conformity, incompatible transition guards and mandatory
manual review after ambiguity. The official service set exposes no independent
event-status query; Consulta DE event content is not treated as proof of a
specific event outcome.

Normative references: [Manual Técnico v150](https://www.dnit.gov.py/documents/20123/420592/Manual%2BT%C3%A9cnico%2BVersi%C3%B3n%2B150.pdf/e706f7c7-6d93-21d4-b45b-5d22d07b2d22),
[official v150 XSD index](https://ekuatia.set.gov.py/sifen/xsd/) and
[Resolución General 23/19](https://ekuatia.set.gov.py/web/portal-institucional/w/resolucion-general-n-23-19).

* [ADR-008 Paraguay Numbering Before CDC](../ADR/ADR-008-paraguay-numbering-before-cdc.md)
* [ADR-009 CSC Only For QR](../ADR/ADR-009-csc-only-for-qr.md)
* [ADR-011 Paraguay Digital Signature Strategy](../ADR/ADR-011-paraguay-digital-signature-strategy.md)
* [ADR-012 Paraguay Qualified Certificate Lifecycle](../ADR/ADR-012-paraguay-qualified-certificate-lifecycle.md)
* [Paraguay Processing Diagram](../diagrams/paraguay-processing.mmd)
## Odoo Accounting integration

Posted customer invoices can be prepared explicitly with **Prepare Electronic
Invoice**:

```text
account.move -> neutral snapshot -> fiscal.document
             -> Paraguay numbering/CDC/payload -> KuDE Preview
```

Preparation does not submit, sign, create a fiscal QR, or manufacture authority
evidence. Each `account.tax` requires an explicit SIFEN treatment (IVA 10%, IVA
5% or Exempt); names are never parsed. The current boundary accepts PYG and one
tax-inclusive percentage mapping per line, failing closed otherwise.

Partners use an explicit receiver profile. B2B requires a Paraguay RUC in
`base-DV` form, taxpayer type, address and exact official geographic codes and
descriptions. B2C unnamed consumers use the official Innominado projection.
Missing values are never synthesized.

Source identity, Odoo line IDs, values, taxes, totals and a snapshot hash are
preserved. Repeated preparation returns the same document. Once snapshotted,
fiscal source edits, reset and cancellation are blocked pending an explicit
correction workflow. See
[ADR-018](../ADR/ADR-018-account-move-fiscal-snapshot-boundary.md).
