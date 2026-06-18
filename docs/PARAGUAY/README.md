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

CSC is not used for CDC generation. It is reserved for future QR/hash generation.

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

Missing schema-readiness data is reported as payload warnings but does not block payload generation yet.

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

Out of scope for Stage 6:

* digital signature
* `dFecFirma`
* `ds:Signature`
* QR generation
* CSC QR/hash logic
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

Full official XSD validation remains out of scope until later signature and QR stages. The unsigned draft still does not include `dFecFirma`, `ds:Signature`, QR/CSC QR data, SIFEN submission, KuDE, or PDF generation.

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

## Future Digital Signature

Digital signature is not implemented yet.

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

See [ADR-011 Paraguay Digital Signature Strategy](../ADR/ADR-011-paraguay-digital-signature-strategy.md).

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

The service does not persist certificate bundles, private keys, or passwords. Tenant-safe secret-provider implementations, XML signing, trust-chain validation, and revocation validation are not implemented yet.

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

Bindings require the credential and adapter configuration to belong to the same tenant and company. XML-signing and mutual-TLS roles may use different credentials.

`FiscalCredentialMaterialProvider` and `FiscalCredentialProviderRegistry` define the provider boundary only. No encrypted Odoo storage, external secret-store, KMS, or PKCS#11/HSM provider is implemented yet, so the architecture cannot retrieve production secret material.

Credential references and bindings are restricted to system administrators for now.

The legacy `fiscal.adapter.config` fields `certificate_ref` and `private_key_ref` remain temporarily for compatibility. They are references only and must never contain raw certificates, PKCS#12 or PEM content, passwords, or private-key material. Future work should migrate these references to role bindings before removing the legacy fields.

## Future QR

QR generation is not implemented yet.

Future QR generation must happen after digital signature because the QR input includes the XMLDSig `DigestValue`. It should use IdCSC and CSC hash rules. CSC must not be used for CDC generation.

See [ADR-009 CSC Only For QR](../ADR/ADR-009-csc-only-for-qr.md).
See [ADR-011 Paraguay Digital Signature Strategy](../ADR/ADR-011-paraguay-digital-signature-strategy.md).

## Future SIFEN

SIFEN submission is not implemented yet.

Future SIFEN work should build on:

* normalized Paraguay payload
* XML generation
* digital signature
* QR generation
* authority response normalization
* retry/error handling

## Related Documents

* [Documentation Home](../README.md)
* [Documentation Index](../index.md)
* [Architecture](../ARCHITECTURE.md)
* [Roadmap](../ROADMAP.md)
* [Paraguay Processing Diagram](../diagrams/paraguay-processing.mmd)
* [Fiscal State Machine](../diagrams/fiscal-state-machine.mmd)
* [ADR-008 Paraguay Numbering Before CDC](../ADR/ADR-008-paraguay-numbering-before-cdc.md)
* [ADR-009 CSC Only For QR](../ADR/ADR-009-csc-only-for-qr.md)
* [ADR-010 SIFEN XSD Validation Strategy](../ADR/ADR-010-sifen-xsd-validation-strategy.md)
* [ADR-011 Paraguay Digital Signature Strategy](../ADR/ADR-011-paraguay-digital-signature-strategy.md)

## Next Recommended Reading

* [ADR-008 Paraguay Numbering Before CDC](../ADR/ADR-008-paraguay-numbering-before-cdc.md)
* [ADR-009 CSC Only For QR](../ADR/ADR-009-csc-only-for-qr.md)
* [ADR-011 Paraguay Digital Signature Strategy](../ADR/ADR-011-paraguay-digital-signature-strategy.md)
* [Paraguay Processing Diagram](../diagrams/paraguay-processing.mmd)
