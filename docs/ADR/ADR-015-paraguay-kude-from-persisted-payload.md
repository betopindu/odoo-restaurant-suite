# ADR-015: Paraguay KuDE From Persisted Payload

## Status

Accepted

## Date

2026-08-06

## Context

The KuDE is the simplified graphical representation of a Paraguay electronic
tax document. Manual Técnico SIFEN v150 chapter 13 defines its permitted
content, general layout and QR requirements, but it is not the signed fiscal
XML and must not become another source of fiscal truth.

The platform is payload-first and already persists the normalized Paraguay
payload before XML generation. The SIFEN QR URL is produced only after
XMLDSig because it contains the final `DigestValue`. Recalculating either the
business data from XML or the QR from CSC during KuDE generation would create
a second processing path and could make the representation disagree with the
submitted artifact.

Two rendering options were evaluated:

* HTML plus wkhtmltopdf reuses Odoo reporting conventions, but output depends
  on a separate browser engine, its version, fonts and runtime configuration.
* Direct PDF generation with ReportLab uses a library already present in the
  Odoo runtime and supports invariant PDF metadata, explicit pagination and
  exact QR dimensions without another process.

## Decision

`PyKudeService` generates an invoice KuDE exclusively from the latest
persisted `paraguay_payload_json` and current `paraguay_qr_payload` artifacts.
It never reads fiscal XML, SOAP requests or authority responses, and it never
calls SIFEN. The exact QR URL is persisted by the submission pipeline after QR
generation; the KuDE service embeds that value unchanged and has no CSC input.

PDF rendering uses ReportLab directly with invariant output. The result is a
versioned `paraguay_kude_pdf` fiscal attachment. A document row lock serializes
artifact selection and creation: identical bytes reuse the current attachment;
changed payload or QR creates a new current version and preserves the previous
version as superseded audit evidence.

The initial supported representation is the Factura Electrónica. Other DTE
types require their own official KuDE field matrix and are rejected explicitly
instead of being rendered as an invoice.

## Consequences

* KuDE regeneration is deterministic and has no effect on signed XML,
  transmissions, retry state or authority evidence.
* Payload and QR attachment hashes identify the exact inputs used by every PDF
  version.
* Historical documents without a persisted exact QR URL cannot generate a
  KuDE through this service; silently recreating the URL from CSC is forbidden.
* PDF content remains a representation. The signed XML and authority result
  remain the fiscal evidence.
* ReportLab is the only renderer used by this path; wkhtmltopdf availability or
  host CSS/font configuration cannot alter the output.

## Official Basis

* [Manual Técnico SIFEN v150](https://www.dnit.gov.py/documents/20123/420592/Manual%2BT%C3%A9cnico%2BVersi%C3%B3n%2B150.pdf/e706f7c7-6d93-21d4-b45b-5d22d07b2d22?t=1687351495907), chapter 13, especially sections 13.1, 13.3, 13.4 and 13.5.
* Manual Técnico v150 section 13.8 for the QR minimum size and ISO/IEC 18004 reference.
* [DNIT e-Kuatia frequently asked questions](https://www.dnit.gov.py/web/e-kuatia/preguntas-frecuentes/-/categories/2705316) for receiver-delivery obligations.

## Related Documents

* [Architecture](../ARCHITECTURE.md)
* [Paraguay Documentation](../PARAGUAY/README.md)
* [Homologation Runbook](../PARAGUAY/HOMOLOGATION_RUNBOOK.md)
* [ADR-003 Payload Before XML](ADR-003-payload-before-xml.md)
* [ADR-007 Fiscal Attachments](ADR-007-fiscal-attachments.md)
* [ADR-009 CSC Only For QR](ADR-009-csc-only-for-qr.md)
