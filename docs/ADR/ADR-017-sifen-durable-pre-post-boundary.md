# ADR-017: Durable SIFEN pre-POST submission boundary

## Status

Accepted.

## Context

A synchronous SIFEN POST is an external side effect. Previously Paraguay
created its transmission, generated artifacts, performed the POST, and stored
the result inside the caller's Odoo transaction. A worker failure after SIFEN
received the request but before PostgreSQL committed could erase every local
indication that the CDC had been submitted.

Committing the caller cursor before POST is unacceptable because it can also
commit unrelated business changes. Savepoints and nested ORM environments on
the same cursor are not independently durable.

## Decision

DE submission uses a narrowly scoped independent cursor owned by
`PySifenDurableAttemptService`:

1. Before artifact preparation it locks the already-committed fiscal document,
   allocates the next attempt, creates a `pending` submit transmission, and
   commits only that transmission.
2. The caller builds the current payload/unsigned/signed/QR/rDE chain without
   committing its transaction.
3. After SOAP serialization and immediately before transport, the independent
   cursor updates the same attempt to `sent`, stores sanitized endpoint,
   request SHA-256, signing time, and artifact IDs/hashes, marks the outcome
   ambiguous, and commits.
4. After normalization, the independent cursor commits the explicit or
   ambiguous result on that same attempt. The caller then updates the document
   and optional normalized-response attachment in its normal transaction.

New, uncommitted fiscal documents cannot cross this boundary; normal business
persistence must happen first. Tests use their test-owned cursor so
`TransactionCase` rollback remains isolated, and separately verify that
production mode selects and commits an independent cursor.

## Recovery semantics

* `pending` with `durability_phase=prepared` and `post_started=false` proves the
  pre-POST callback did not run. It blocks automatic submission. An operator
  may explicitly abandon it as `pre_post_not_attempted` before another attempt.
* `sent` with `post_started=true` means request identity was committed before
  transport. Missing response evidence is ambiguous and requires Consulta DE.
* Completed accepted or rejected transmissions are terminal evidence even if
  the caller later rolls back. Acceptance always blocks another POST.
* Missing or inconsistent durability metadata fails closed as manual review.

Empty response fields never imply permission to resend.

## Consequences

Outbound identity survives caller rollback without committing unrelated data.
Crashes during local preparation leave a durable `pending` record requiring an
explicit operator decision but cannot represent an unknown remote side effect.

Cancellation, inutilization, receiver events, and Consulta DE do not yet use
this primitive. Their behavior remains unchanged pending separate work.
