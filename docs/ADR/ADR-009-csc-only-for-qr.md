Documentation > ADR > ADR-009 CSC Only For QR

[Documentation Home](../README.md)
-> [Architecture](../ARCHITECTURE.md)
-> [ADRs](../index.md#adrs)
-> [Paraguay](../PARAGUAY/README.md)
-> [Diagrams](../diagrams/README.md)

# Title

ADR-009: CSC Only For QR

## Status

Accepted

## Date

2026-06-07

## Context

Paraguay configuration includes CSC and IdCSC. CDC research confirmed that CSC is not part of CDC generation. CDC uses a separate 9-digit security code (`dCodSeg`) and a modulo-11 check digit.

CSC and IdCSC are relevant for QR/hash generation, not for CDC composition.

## Decision

Do not use CSC for CDC generation.

CSC remains configured in `einvoice_py` and is consumed transiently by the
implemented QR builder. CDC generation uses issuer data, establishment, point
of issue, document number, taxpayer type, emission date, emission type,
security code, and modulo-11 check digit.

## Consequences

* CDC generation follows the Paraguay structure without mixing QR-specific secrets.
* CSC remains sensitive configuration and should not be exposed in payloads or API responses.
* QR generation uses IdCSC and CSC hash rules separately from CDC generation.
* Tests should ensure CDC can be generated without reading CSC secret value.
* Live TEST interoperability confirmed that `IdCSC` and CSC form one
  environment-specific authority-issued pair. A locally reproducible hash made
  with the wrong CSC is still rejected by the authority (`2501`).
* The CSC is appended only to the transient hash preimage. It is absent from
  `dCarQR`, normalized results, logs, and attachment metadata.

## Alternatives Considered

* Include CSC in CDC generation.
  * Rejected because CSC is not a CDC segment.
* Ignore CSC until QR implementation.
  * Rejected because CSC configuration is already needed for future Paraguay completeness and validation flow.
* Store CSC in the neutral core.
  * Rejected because CSC is Paraguay-specific and sensitive.

## Related ADRs

* [ADR-001: Country Addons](ADR-001-country-addons.md)
* [ADR-002: CDC as Country Identifier](ADR-002-cdc-country-identifier.md)
* [ADR-008: Paraguay Numbering Before CDC](ADR-008-paraguay-numbering-before-cdc.md)

## Related Documents

* [Documentation Home](../README.md)
* [Documentation Index](../index.md)
* [Architecture](../ARCHITECTURE.md)
* [Paraguay Documentation](../PARAGUAY/README.md)

## Next Recommended Reading

* [Paraguay Documentation](../PARAGUAY/README.md)
* [Paraguay Processing Diagram](../diagrams/paraguay-processing.mmd)
