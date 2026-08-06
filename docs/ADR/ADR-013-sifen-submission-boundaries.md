Documentation > ADR > ADR-013 SIFEN Submission Boundaries

# ADR-013: SIFEN Submission Boundaries

## Status

Accepted

## Date

2026-07-26

## Context

The TEST flow must distinguish local document validity, transport execution,
SOAP protocol failures, authority decisions, and fiscal workflow side effects.
Combining these concerns would make an HTTP success look like fiscal
acceptance and would make a controlled first submission retry unexpectedly.

## Decision

The final `rDE` is validated locally against the pinned official v150 XSD set
before SOAP construction or network access. The SOAP client returns transport
facts without interpreting SIFEN business meaning. The response parser
separates transport failure, HTTP error, SOAP Fault, malformed content,
accepted, rejected, duplicate, and unknown authority codes.

The isolated `PySifenSubmissionService.submit()` composes one TEST request and
returns a structured immutable result. It performs no persistence, state
transition, automatic retry, or Consulta DE call. Existing persistence and
retry services remain separate.

Durable pre-POST persistence proposed for Stage 8.24B is postponed until live
homologation evidence shows it is required. Ambiguous outcomes must not be
blindly retried; operators reconcile by CDC first.

The first accepted TEST submission confirms these boundaries in a live
authority exchange. Homologation corrections remained inside their owning
boundaries: fiscal time in the Paraguay datetime/preparation services, signed
artifact selection in attachment persistence, fiscal arithmetic in the payload
builder, QR preimage construction in the QR service, and authority outcomes in
the parser/persistence services. No transport or neutral-core special case was
introduced.

## Consequences

* Local XSD failures cannot reach the network.
* HTTP success is not confused with authority acceptance.
* SOAP Faults are not treated as business rejections.
* Live requests remain explicitly controlled until operational approval.
* Crash durability across an external POST is not claimed.

## Alternatives Considered

* Interpret responses in the transport.
  * Rejected because transport and authority semantics are different.
* Persist and retry inside the isolated submission service.
  * Rejected because that would duplicate existing workflow services.
* Implement Stage 8.24B before homologation.
  * Still postponed after first acceptance: the controlled flow and mandatory
    Consulta DE handling cover known ambiguous outcomes, while a durability
    redesign requires a separate operational decision.

## Related Documents

* [Architecture](../ARCHITECTURE.md)
* [Paraguay Documentation](../PARAGUAY/README.md)
* [Homologation Runbook](../PARAGUAY/HOMOLOGATION_RUNBOOK.md)
* [ADR-010 XSD Validation](ADR-010-sifen-xsd-validation-strategy.md)
