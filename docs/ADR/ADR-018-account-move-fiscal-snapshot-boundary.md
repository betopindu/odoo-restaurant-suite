# ADR-018: Odoo invoice fiscal snapshot boundary

## Status

Accepted.

## Context

The fiscal platform accepted API-created or manually prepared
`fiscal.document` records, but normal Odoo invoices had no controlled entry
point. Reading `account.move` dynamically from country builders would couple
authority evidence to mutable accounting records and leak national rules into
the neutral core.

## Decision

A posted customer invoice is converted explicitly through
`FiscalDocumentFromAccountMoveService`. The neutral service locks the move,
validates company/tenant/adapter scope, creates one header/customer/line/tax/
total snapshot, and links it through `account_move_id` and the existing source
identity fields. SQL uniqueness and a deterministic idempotency key enforce one
active fiscal document per move and adapter.

The Paraguay composition service supplies national configuration and mappings:
explicit `account.tax` treatment, B2B/B2C receiver projection, issuer context,
numbering, CDC and persisted payload. Tax names are never interpreted.
Unsupported currencies, tax-exclusive prices, multiple taxes per line,
ambiguous configuration and incomplete receiver data fail closed.

Creation is explicit after posting. It never posts the entry, signs, transmits
or fabricates authority evidence. The current payload can render the existing
non-authoritative KuDE Preview.

## Mutation boundary

Once an active snapshot exists, changes to customer, currency, invoice date or
invoice lines, reset to draft, and accounting cancellation are blocked. Future
credit-note/correction workflows must resolve fiscal consequences instead of
silently rebuilding accounting data.

## Consequences

The core remains country-neutral while gaining a reusable accounting-source
boundary. Paraguay currently supports posted customer invoices in PYG with one
explicit tax-inclusive IVA 10%, IVA 5% or exempt mapping per line. Credit/debit
notes, tax-exclusive prices, automatic creation on posting and automatic SIFEN
transmission remain outside this stage.
