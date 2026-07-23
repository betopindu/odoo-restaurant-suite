Documentation > ADR > ADR-012 Paraguay Qualified Certificate Lifecycle

[Documentation Home](../README.md)
-> [Architecture](../ARCHITECTURE.md)
-> [ADRs](../index.md#adrs)
-> [Paraguay](../PARAGUAY/README.md)
-> [Roadmap](../ROADMAP.md)

# ADR-012: Paraguay Qualified Certificate Lifecycle

## Status

Accepted

## Date

2026-07-23

## Context

SIFEN TEST requires the taxpayer's Qualified Certificate issued by a Prestador Cualificado de Servicios de Confianza (PCSC) habilitado. Real acceptance therefore differs from local cryptographic testing: a self-signed certificate can exercise parsing, XML signing, verification, and negative TLS scenarios, but it cannot obtain real SIFEN acceptance.

The supported operational delivery format is a password-protected PKCS#12 (`.p12`) bundle containing the certificate and corresponding private key. The same qualified certificate can satisfy both XML signing and mutual-TLS authentication. The platform nevertheless has two explicit credential roles because their consumers and validation rules are different.

Certificate material is tenant- and company-sensitive, has a one-year operational validity, and must be replaceable without coupling country services to any particular Prestador Cualificado de Servicios de Confianza (PCSC) habilitado.

## Decision

The SIFEN credential architecture remains based on provider-neutral credential references and transient material resolution.

`fiscal.credential` stores scope, provider references, material format, and non-secret inspection metadata. It must not store PKCS#12 bytes, private-key bytes, or passwords in ordinary plaintext fields.

`fiscal.adapter.credential.binding` retains two logical roles:

* `xml_signing`
* `mutual_tls`

Both bindings may reference the same `fiscal.credential`. Their separation is logical rather than a requirement for two physical certificates. Consumers must continue requesting the role they need and must not infer that the other role uses the same record.

`PySifenCredentialProvider` resolves the document adapter, scoped bindings, XML-signing material, CSC, endpoint, and timeout into a redaction-safe runtime credential object. It does not define how secret bytes are retrieved.

`FiscalCredentialMaterialProvider` is the boundary for transient retrieval of referenced material. `ExternalSecretPkcs12MaterialProvider` implements the existing `external_secret` provider type. It reads PKCS#12 bytes from an absolute deployment-managed `file://` reference and resolves an optional password from a `file://` or `env://` reference. It returns material through the existing `pkcs12_bytes` and `password` contract and does not depend on the identity or API of any specific Prestador Cualificado de Servicios de Confianza (PCSC) habilitado.

The supported operational certificate input is PKCS#12 (`.p12`). Normalized certificate, private-key, and password values remain transient and must not be logged, included in normalized results, or persisted in fiscal transmissions or payload attachments.

Local certificate inspection validates:

* X.509 structure and supported RSA key characteristics
* certificate and private-key correspondence
* taxpayer RUC identity
* certificate validity interval
* XML-signing KeyUsage requirements
* mutual-TLS ExtendedKeyUsage requirements

Local inspection is preventive validation, not an authority trust decision. Local XMLDSig verification proves signature integrity using the embedded certificate. SIFEN makes the final decision about trust, validity, and acceptance of the client certificate during mutual TLS and subsequent authority validation.

A self-signed certificate may be used only for local deterministic tests or deliberate negative certificate scenarios. It must not be represented as suitable for a real accepted SIFEN TEST submission.

Certificate rotation is a configuration and deployment operation that must be completed before the one-year certificate validity expires. Replacement PKCS#12 material must be made available through the configured material provider, inspected for the required roles, bound to the correct tenant/company/environment, and verified through the TEST preflight before cutover. Signing, submission, persistence, and retry services must continue consuming the same credential interfaces without code changes.

`PyQualifiedCertificateInstallationValidationService` performs the installation inspection before preflight. It loads the referenced material through the existing registry, validates both logical bindings and both certificate roles through `PyCertificateInspectionService`, and stores only non-secret inspection metadata and reports. It does not contact SIFEN or invoke any document-processing service.

## Consequences

* The platform remains independent of every Prestador Cualificado de Servicios de Confianza (PCSC) habilitado.
* A taxpayer may operate one qualified certificate for both XML signing and mutual TLS.
* Role-specific validation and tenant isolation remain explicit.
* Deployment must mount the PKCS#12 material and configure its external references before live preflight.
* Local success does not claim SIFEN trust or acceptance.
* Certificate replacement does not require redesigning consumer services.
* Operational procedures must track expiry and complete rotation before the active certificate becomes unusable.

## Alternatives Considered

* Couple credential loading to a specific Prestador Cualificado de Servicios de Confianza (PCSC) habilitado.
  * Rejected because certificate issuance and runtime secret retrieval are separate concerns, and provider coupling would violate the existing credential boundary.
* Merge XML signing and mutual TLS into one binding.
  * Rejected because the roles have distinct consumers and validation rules even when they use the same certificate.
* Persist the PKCS#12 bundle or password directly in ordinary Odoo fields.
  * Rejected because it would expose tenant secrets through database access, exports, logs, or backups.
* Treat successful local inspection as proof of SIFEN trust.
  * Rejected because only SIFEN can make the authority-side client-certificate trust decision.
* Use a self-signed certificate for a real accepted TEST submission.
  * Rejected because self-signed material is limited to local and negative testing.

## Related ADRs

* [ADR-004: Multi-Tenant Shared Core](ADR-004-multi-tenant-shared-core.md)
* [ADR-007: Fiscal Attachments](ADR-007-fiscal-attachments.md)
* [ADR-011: Paraguay Digital Signature Strategy](ADR-011-paraguay-digital-signature-strategy.md)

## Related Documents

* [Architecture](../ARCHITECTURE.md)
* [Roadmap](../ROADMAP.md)
* [Paraguay Documentation](../PARAGUAY/README.md)
