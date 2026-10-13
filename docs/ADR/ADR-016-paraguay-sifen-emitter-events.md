# ADR-016: Paraguay SIFEN emitter-event boundary

## Status

Accepted.

## Context

Cancellation and number inutilization use the SIFEN emitter-event service, not
the synchronous DE reception service. Both require a signed `rEve`, SOAP 1.2,
mutual TLS, independent authority evidence and conservative handling of
uncertain transport outcomes. Inutilization is not naturally attached to a
`fiscal.document`, because it represents numbers that must not have been used.

## Decision

Keep the abstraction inside `einvoice_py`. `PySifenEventService` owns the common
v150 envelope, XMLDSig, mTLS, response parsing and safe observability.
`PySifenCancellationService` and `PySifenInutilizationService` own their distinct
eligibility and state rules. Cancellation uses an independent `cancel`
`fiscal.transmission` plus a successful `fiscal.event`; inutilization uses the
Paraguay-specific `fiscal.py.inutilization` audit model.

Cancellation validates its signed `rEve` against locally pinned official v150
event schemas before transport. `PySifenDurableCancellationService` commits
the exact request hash and event identity on a dedicated cursor, marks the POST
boundary independently, and finalizes the same attempt. Opening or cancelling
the operator confirmation wizard creates no attempt and performs no network
operation.

Number inutilization follows the same durable safety shape without pretending
that an unused range is a fiscal document. Its dedicated audit record is
created independently after signing/XSD validation and before POST. The
operator wizard is the normal creation path; direct user creation or editing
of authority evidence is denied.

No generic core event protocol is introduced. The existing neutral
`fiscal.event` remains a document lifecycle journal and is not stretched to
represent unused number ranges.

## Consequences

Original accepted submissions and signed artifacts remain immutable. Event
success is code `0600`; explicit rejections are separate evidence. Timeout,
HTTP/TLS uncertainty, SOAP Fault and malformed responses require manual review
and are never retried automatically. Tenant/company scoping and row locks are
mandatory before eligibility and overlap checks.

Receiver manifestations use this same Paraguay-local protocol boundary through
`PySifenReceiverEventService`, with a separate `fiscal.py.receiver.event`
record. Notification, conformity, disconformity and unknown-document semantics
remain localization rules; no neutral-core state or generic event protocol is
introduced.
