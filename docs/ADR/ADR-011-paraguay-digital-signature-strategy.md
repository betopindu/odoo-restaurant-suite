Documentation > ADR > ADR-011 Paraguay Digital Signature Strategy

[Documentation Home](../README.md)
-> [Architecture](../ARCHITECTURE.md)
-> [ADRs](../index.md#adrs)
-> [Paraguay](../PARAGUAY/README.md)
-> [Diagrams](../diagrams/README.md)

# Title

ADR-011: Paraguay Digital Signature Strategy

## Status

Accepted

## Date

2026-06-18

## Context

The Paraguay addon generates an unsigned SIFEN-oriented XML draft and pins the official SIFEN v150 XSD dependency tree locally.

The official `rDE` structure requires signing-stage and QR-stage content that is intentionally absent from the unsigned draft:

* `dFecFirma`
* `ds:Signature`
* `gCamFuFD/dCarQR`

Stage 7.0 discovery reviewed the SIFEN v150 technical manual, the official schemas, the SIFEN test guide, and the project architecture. The discovery established that QR generation depends on the XMLDSig `DigestValue`, so digital signature must precede QR generation.

The project also needs to preserve the unsigned XML for audit and debugging while protecting private keys and tenant-specific credentials.

## Decision

SIFEN v150 digital signatures will use the W3C XML Signature standard in enveloped form.

XAdES is not required by the current SIFEN v150 technical profile or official schemas. It will not be introduced unless a future official SIFEN requirement explicitly mandates it.

The signed node is `DE`. Its `Id` attribute contains the previously generated CDC, and the XMLDSig reference must use that same value:

```xml
<Reference URI="#CDC">
```

The CDC must exist before signing. It must not change after signing because it identifies both the signed `DE` node and the signature reference target.

`dFecFirma` belongs to the signing stage. It will be inserted inside `DE`, after `dDVId` and before `dSisFact`.

The signature is a child of `rDE`, placed after `DE` and before `gCamFuFD`:

```xml
<rDE>
  <dVerFor>150</dVerFor>
  <DE Id="CDC">
    <dDVId>...</dDVId>
    <dFecFirma>...</dFecFirma>
    <dSisFact>...</dSisFact>
    ...
  </DE>
  <Signature xmlns="http://www.w3.org/2000/09/xmldsig#">
    ...
  </Signature>
  <gCamFuFD>
    ...
  </gCamFuFD>
</rDE>
```

QR generation must happen after digital signature because the SIFEN QR input includes the XMLDSig `DigestValue`.

Full official SIFEN XSD validation will happen only after both signature and QR content exist.

Signed XML will be persisted as a separate sensitive fiscal attachment. Signing must not overwrite or mutate the existing unsigned XML attachment.

The implementation will use `xmlsec` or another maintained XML security library. The project will not implement XML canonicalization, digest generation, or signature generation manually.

Certificate and private-key access will be abstracted behind tenant-safe credential handling. The design will keep separate logical credential roles:

* XML signing certificate and private key
* mutual TLS certificate and private key

Deployments may resolve both roles to the same qualified certificate when appropriate. The two bindings remain logically distinct, but both may point to the same `fiscal.credential`; application code must not collapse the two roles or assume that they always use the same material.

The operational requirements for qualified certificates, provider-neutral PKCS#12 resolution, trust boundaries, and rotation are defined in [ADR-012](ADR-012-paraguay-qualified-certificate-lifecycle.md).

Private keys must not be stored in ordinary plaintext model fields. Credential references may identify encrypted Odoo storage, an external secret store, KMS/HSM infrastructure, or another protected provider.

## Consequences

* The processing order becomes CDC, unsigned XML, signature, QR, full XSD validation, and SIFEN submission.
* `dFecFirma` is excluded from the unsigned XML builder and introduced only when signing.
* CDC and all signed `DE` content become immutable after signature generation.
* The unsigned and signed XML artifacts remain independently auditable.
* QR generation can consume the authoritative `DigestValue` produced by XMLDSig.
* Certificate rotation and transport authentication can evolve independently from XML signing.
* Signing implementation requires a maintained XML security dependency and compatible runtime packaging.
* Tenant isolation must cover certificate metadata, credential references, private-key access, and signed attachments.
* Full official XSD validation remains deferred until signature and QR stages are complete.

## Alternatives Considered

* Generate QR before signing.
  * Rejected because the SIFEN QR input includes the XMLDSig `DigestValue`.
* Sign the complete `rDE` element.
  * Rejected because the SIFEN profile signs `DE` and references its CDC-backed `Id`.
* Add XAdES preemptively.
  * Rejected because the current SIFEN v150 profile requires XMLDSig and does not mandate XAdES.
* Replace the unsigned XML attachment with the signed result.
  * Rejected because preserving both artifacts improves auditability and debugging.
* Implement canonicalization and RSA signing directly in project code.
  * Rejected because XML signature processing is security-sensitive and should use a maintained XML security library.
* Store private keys directly in plaintext Odoo fields.
  * Rejected because it is incompatible with tenant-safe secret handling and creates unacceptable exposure through administrators, exports, logs, and backups.
* Treat XML signing and mutual TLS as one inseparable credential.
  * Rejected because certificate usage, storage, rotation, and deployment requirements may differ.

## Related ADRs

* [ADR-001: Country Addons](ADR-001-country-addons.md)
* [ADR-002: CDC as Country Identifier](ADR-002-cdc-country-identifier.md)
* [ADR-003: Payload Before XML](ADR-003-payload-before-xml.md)
* [ADR-004: Multi-Tenant Shared Core](ADR-004-multi-tenant-shared-core.md)
* [ADR-007: Fiscal Attachments](ADR-007-fiscal-attachments.md)
* [ADR-008: Paraguay Numbering Before CDC](ADR-008-paraguay-numbering-before-cdc.md)
* [ADR-009: CSC Only For QR](ADR-009-csc-only-for-qr.md)
* [ADR-010: SIFEN XSD Validation Strategy](ADR-010-sifen-xsd-validation-strategy.md)
* [ADR-012: Paraguay Qualified Certificate Lifecycle](ADR-012-paraguay-qualified-certificate-lifecycle.md)

## Related Documents

* [Documentation Home](../README.md)
* [Documentation Index](../index.md)
* [Architecture](../ARCHITECTURE.md)
* [Roadmap](../ROADMAP.md)
* [Paraguay Documentation](../PARAGUAY/README.md)

## Next Recommended Reading

* [ADR-010 SIFEN XSD Validation Strategy](ADR-010-sifen-xsd-validation-strategy.md)
* [Paraguay Documentation](../PARAGUAY/README.md)
* [Roadmap](../ROADMAP.md)
