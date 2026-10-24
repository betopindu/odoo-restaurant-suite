# Paraguay Commercial V1 Roadmap

## Goal

Deliver a production-capable first version for small restaurants and retail
businesses operating in PYG, at low or medium volume, without delivery
logistics, warehouse transfers or automated supplier-document processing.

The product supports FE, NCE, NDE, AFE, cancellation, inutilization,
authoritative KuDE/XML delivery and conservative Consulta DE recovery. AFE is
available but is not part of the routine sales checkout.

## Commercial checkout contract

At payment, the cashier chooses exactly one outcome:

1. **No FE**: create no fiscal document, consume no fiscal number or CDC and
   contact no SIFEN service. Print only an Odoo receipt clearly identified as
   non-fiscal. Availability is configurable per company/POS and must reflect
   that taxpayer's legally approved operating model.
2. **Consumer final**: issue an innominado B2C FE. The SIFEN receiver uses
   nature `2`, operation type `2`, country `PRY`, ID type `5`, ID number `0`
   and receiver name `Sin Nombre`. A current DNIT amount rule may force an
   identified receiver and must fail closed when applicable.
3. **With RUC**: resolve an exact normalized RUC locally first. If absent,
   query SIFEN. Persist a successful authority result locally. If the query
   finds no result or is unavailable, permit an explicitly marked manual,
   unverified receiver and warn that authority rejection remains possible.

Only Manual-v150-required or conditionally required receiver fields block
issuance. Email, telephone, trade name and unrelated contact enrichment remain
optional. Fiscal snapshots remain immutable after preparation.

## Delivery contract

Email is optional for fiscal issuance and mandatory only when email delivery
is selected. Per-company/POS configuration controls automatic delivery:

* if an identified customer already has an email, KuDE PDF and XML may be
  queued automatically after acceptance without another prompt;
* if no email exists, print the KuDE;
* an innominado customer may provide an address for that sale only;
* email failure never changes an accepted fiscal result and is retried or
  corrected independently of SIFEN;
* the effective recipient, channel and delivery outcome are audited per sale.

## Delivery stages

The fiscal engine is channel-independent. Odoo POS, the existing API-first
integration and a future web frontend are separate adapters. The first POS
release uses `einvoice_py_pos`; installing Restaurant or KDS is never required
for Paraguay invoicing, and installing KDS never requires e-Invoice.

### V1.0-P0 — Checkout decision and fiscal identity

- [x] Add the `No FE / Consumer final / With RUC` decision to POS payment.
- [x] Record the selected decision and its stable client decision identifier in
  the POS order payload. The backend rejects conflicting replays and makes the
  confirmed decision immutable.
- [x] Keep this first UI increment offline: `With RUC` accepts only an existing
  local taxpayer partner; it neither queries SIFEN nor creates or submits a
  fiscal document. The configured innominado partner is explicitly loaded for
  `Consumer final`.
- Align innominado XML with Manual v150 and enforce its amount guard.
- [x] Implement local-first RUC resolution, official mTLS Consulta RUC fallback
  (`0500/0501/0502`) and an explicit manual-unverified fallback without
  fabricating optional data. Successful authority results are cached as local
  partners; remote data still requires the cashier to select the taxpayer type
  because Consulta RUC does not return that SIFEN field.
- Keep every network boundary mocked during development.

### V1.0-P1 — Payments and automatic orchestration

- [x] Map POS cash, card, bank transfer/QR and mixed tenders to SIFEN
  semantics. Each POS method requires an explicit official code; the immutable
  snapshot nets change, reconciles to the sale total and emits one ordered
  `gPaConEIni` group per tender.
- [x] Create the posted accounting move and immutable fiscal document exactly
  once when FE is selected.
- [x] Queue exactly one durable submission after cashier confirmation without
  blocking POS/KDS. A configured fiscal-operator identity executes the job;
  the job is claimed once, never requeued automatically, and its transmission
  is explicitly ineligible for automatic retry.
- [x] Show queued/processing, accepted, rejected, ambiguous and
  recovery/operator-required outcomes on the POS receipt screen. The polling
  endpoint is read-only and never invokes submission, retry or Consulta DE.
- Keep KDS preparation independent from fiscal checkout latency.

### V1.0-P2 — Recipient delivery and operational recovery

- [x] Apply configurable automatic email delivery for known recipients. The
  originating channel snapshots the confirmed recipient and may explicitly
  suppress automatic email when print-only delivery was selected.
- [x] Open/print the authoritative KuDE and download the accepted final XML
  directly from the POS receipt through session- and decision-scoped routes.
- [x] Expose email delivery state and an operator-authorized, idempotent resend
  of the authoritative KuDE/XML without another SIFEN call.
- Provide operator recovery and Consulta DE only through existing guards.
- Define the no-connectivity and SIFEN-unavailable operating procedure.

### V1.0-P3 — Commercial validation and release

- Validate IVA 10%, IVA 5%, exempt and mixed-rate sales.
- Validate multiple items, discounts, rounding and all supported tenders.
- Validate B2C, local B2B, remote-RUC B2B and manual-unverified B2B.
- Validate rejection, ambiguity, restart, duplicate click, email failure and
  printer fallback.
- Install on a clean local database, then deploy the same baseline to AWS
  STAGING and repeat the complete acceptance suite.
- Complete the authority-required homologation cases and production approval.
- Configure production certificate, CSC, timbrado, endpoints, HTTPS, secret
  management, monitoring, alerting, roles and tested backup restoration.
- Run a supported pilot with one or two low-volume businesses before general
  availability.

## Explicitly after V1

- asynchronous batch submission and batch-result query;
- received-DTE and supplier-document automation;
- Nota de Remision Electronica and logistics;
- receiver-event completion;
- general-purpose Consulta DE UI beyond guarded recovery;
- WhatsApp delivery;
- automatic DNIT catalog synchronization;
- financed installment sales, unless separately promoted into V1 scope;
- high-volume, multi-warehouse and complex multi-company operation.

## Release gate

Commercial V1 is ready only when the normal POS sale requires no Accounting
screen intervention, every FE decision is auditable, payment semantics are
correct, one-and-only-one submission is guaranteed, recipient delivery has a
usable channel, failure recovery is operator-safe, clean installation and AWS
STAGING validation pass, and DNIT production enablement is complete.
