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
- [x] Align innominado XML with Manual v150 and enforce its amount guard. The
  neutral fiscal engine emits nature `2`, B2C operation `2`, country `PRY`, ID
  type `5`, number `0` and `Sin Nombre`, without fabricated geography. Above
  the invoice-date equivalent of USD 10,000 it fails closed and requires an
  identified receiver.
- [x] Implement local-first RUC resolution, official mTLS Consulta RUC fallback
  (`0500/0501/0502`) and an explicit manual-unverified fallback without
  fabricating optional data. Successful authority results are cached as local
  partners; remote data still requires the cashier to select the taxpayer type
  because Consulta RUC does not return that SIFEN field.
- [x] Complete new authority-resolved and manual-unverified taxpayers inside
  the POS with the address and SIFEN department/district/city data required by
  the B2B snapshot. The completed receiver is cached locally and reused;
  incomplete data, invalid numeric geography codes or a mismatched official
  department code-description pair fails before fiscal preparation.
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

- [x] Validate IVA 10%, IVA 5%, exempt and mixed-rate sales through the full
  offline signed-rDE/XSD path.
- [x] Validate multiple items, item discounts and SIFEN eight-decimal monetary
  precision offline. Authority/live matrix evidence remains a release gate.
- [x] Validate the V1 POS tender set offline: cash, credit/debit card, bank
  transfer, electronic wallet, mobile payment and electronic/QR payment.
  Card brand/processing data is snapshotted and emitted in the mandatory
  `gPagTarCD` group; incomplete configuration fails before fiscal preparation.
  Cheque, bank-payment presence and free-form "other" remain unavailable in a
  fiscal POS until their transaction-specific evidence can be captured safely.
- [x] Validate B2C, local B2B, remote-RUC B2B and manual-unverified B2B
  through the offline POS decision, receiver-completion and fiscal-preparation
  boundaries. The local-B2B path also has an isolated interactive POS result
  with a ready fiscal document and zero submissions.
- [x] Validate rejection, ambiguity, restart, duplicate click, email failure
  and printer fallback. Automated tests preserve a single queued job across a
  cache/process boundary, project rejection and ambiguity without side
  effects, and keep accepted fiscal state independent from email failure. An
  isolated interactive POS run also preserved its ready fiscal document when
  native preparation printing failed.
- [x] Install the complete fiscal/POS baseline on a clean local database and
  validate module discovery, dependency installation, registry, views,
  security and assets. The complete joint acceptance suite for
  `einvoice_module`, `einvoice_py` and `einvoice_py_pos` passes on that clean
  database with 804 methods / 880 checks and zero failures or errors. The
  clean database remains at zero fiscal documents, transmissions and
  submission jobs; fiscal checkout and automatic submission are disabled by
  default.
- [x] Deploy the same baseline to AWS STAGING and repeat the complete
  acceptance suite. The isolated Odoo `17.0-20260817` run passed with 805
  methods / 881 checks and zero failures or errors; its temporary database was
  removed afterward and no SIFEN request was made.
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

## Pre-habilitation deployment decision

The application may be deployed on its intended operational infrastructure
before DNIT production habilitation, but Paraguay fiscal configuration must
remain explicitly in **TEST**. During this phase every SIFEN endpoint, adapter,
timbrado, CSC and generated document must remain TEST-scoped; the documents
have no fiscal validity and the deployment must not be represented to users as
production electronic invoicing.

Switching SIFEN to **PRODUCTION** is a separate controlled release operation.
It requires DNIT habilitation plus production certificate, CSC, timbrado and
endpoint configuration, a reviewed readiness check and explicit authorization.
Application hosting in production-like infrastructure never implies authority
to select the SIFEN production environment.

Progress toward that deployment is maintained in the
[Commercial V1 SIFEN TEST deployment checklist](PRODUCTION_TEST_DEPLOYMENT_CHECKLIST.md).
