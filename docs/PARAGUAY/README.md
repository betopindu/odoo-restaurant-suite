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
* fiscal data enrichment for receiver, operation, payment, and tax details
* administrative UI stabilization for validation/support workflows

## Configuration

### Issuer

`fiscal.py.issuer` stores Paraguay issuer fiscal data needed for future SIFEN processing and CDC generation.

Key data:

* RUC without DV
* RUC DV
* taxpayer type
* tenant
* company
* environment

Issuer data is snapshotted onto the fiscal document during Paraguay processing so historical documents remain stable if configuration changes later.

### Establishment

`fiscal.py.establishment` represents the Paraguay establishment code.

An active establishment belongs to an issuer and carries tenant/company scope.

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

Out of scope for Stage 6:

* digital signature
* QR generation
* CSC QR/hash logic
* SIFEN submission
* KuDE/PDF
* XSD validation
* new database fields for geography or economic activities

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

## Future QR

QR generation is not implemented yet.

Future QR generation should use IdCSC and CSC hash rules. CSC must not be used for CDC generation.

See [ADR-009 CSC Only For QR](../ADR/ADR-009-csc-only-for-qr.md).

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

## Next Recommended Reading

* [ADR-008 Paraguay Numbering Before CDC](../ADR/ADR-008-paraguay-numbering-before-cdc.md)
* [ADR-009 CSC Only For QR](../ADR/ADR-009-csc-only-for-qr.md)
* [Paraguay Processing Diagram](../diagrams/paraguay-processing.mmd)
