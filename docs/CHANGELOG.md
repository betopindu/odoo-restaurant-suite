# Documentation Changelog

## 2026-10-25 — Clean Commercial V1 acceptance

* Installed the complete fiscal/POS baseline on an isolated clean database and
  ran the joint `einvoice_module`, `einvoice_py` and `einvoice_py_pos`
  acceptance suite: 804 methods / 880 checks, zero failures or errors.
* Made the account-move integration fixture independent of pre-existing local
  currency-rate data. Production enforcement of the USD 10,000 innominado
  boundary remains unchanged.
* Confirmed after the run that the clean database contains no fiscal document,
  transmission or submission job and has no POS automatic submission enabled.

## 2026-10-24 — Innominado amount boundary

* Enforced the regulatory identified-receiver boundary for Paraguay
  consumer-final FE: an innominado B2C invoice is rejected locally when its
  total exceeds the invoice-date equivalent of USD 10,000. The guard lives in
  the channel-neutral fiscal engine, preserves the Manual v150 innominado
  projection and does not affect identified B2B invoices.
* Completed the local-first Consulta RUC POS flow: new authority-resolved and
  manual-unverified taxpayers now collect and persist their required fiscal
  address and SIFEN geography before checkout. Official SIFEN department
  code-description pairs are enforced, while district/city codes and required
  descriptions fail closed when absent or structurally invalid.
* Prevented a payment method already attached to an enabled Paraguay fiscal POS
  from later losing its supported SIFEN payment mapping.

## 2026-10-24 — Commercial tax-matrix offline validation

* Added full offline signed-rDE/XSD regression coverage for the commercial POS
  tax matrix: IVA 10%, IVA 5%, exempt, mixed-rate items, item discounts and
  SIFEN monetary precision. No tax rule or production transport behavior was
  changed.
* Restricted the commercial POS to payment types it can represent safely and
  added immutable SIFEN card brand, processing and optional processor identity
  snapshots. Credit/debit card payments now emit the mandatory `gPagTarCD`
  XML group; incomplete or unsupported payment configuration fails closed.

## 2026-10-23 — Paraguay AFE live validation and authoritative delivery

* Corrected AFE commercial semantics to transaction type `10`, B2C receiver
  operation type and tax type `4`; an AFE now fails closed if its posted vendor
  bill carries IVA.
* Removed the per-item `gCamIVA` group and forbidden `F017/dTotIVA` element
  from AFE. The QR still receives the Manual v150 fallback value `0` when
  `F017` is absent, without fabricating the prohibited XML field.
* Added the mandatory `gCamDEAsoc` electronic non-taxpayer constancy for AFE.
* Preserved controlled TEST document `34204`, CDC
  `04032224796001001000000322026102215594656963`, and its explicit responses:
  `61056` (`2400`) and `61057` (`0160`, HTTP 400). The latter exposed the
  prohibited AFE `F017`; the corrected full pipeline passes offline. The DNIT
  prevalidator's QR warning was reproduced with already accepted FE `30219`,
  so it is not used as AFE defect evidence.
* The single corrected retry `61058` received HTTP 200 and explicit `1001 -
  TEST - CDC duplicado`. Operator-requested Consulta DE `61060` then returned
  HTTP 200, `0422 - CDC encontrado`, protocol `50276195`, proving that the same
  CDC was already accepted by SIFEN TEST. No response was ambiguous and no
  additional submission was made.
* Completed authoritative recipient delivery locally from the accepted,
  persisted chain: final rDE attachment `74708`, SHA-256
  `c6f0df343b1b4bc2c26871e3667cc18a5c4aa3b26dbc5d184bb0203c4bb0f1c5`, and
  KuDE attachment `74717`, SHA-256
  `04e4f5ca9aa37254b2bed9d4e9eb961d3bc623e174f327b36680f6043077ec99`.
  This closes AFE inside the synchronous Paraguay MVP without claiming the
  remaining official homologation counts or production readiness.

## 2026-10-22 — Paraguay synchronous correction/event MVP closure

* Live-validated NDE document `34200`, transmission `61045`, authority `0260`
  and protocol `50276074`.
* Corrected the SIFEN event wire boundary: eight-digit timbrado, unprefixed
  event data, official schema locations on the event containers, standalone
  `rEve` signing and SOAP 1.2 encapsulation without changing inclusive XMLDSig
  canonicalization.
* Live-validated cancellation transmission `61051` (`0600`, protocol
  `1169485`) and controlled NDE inutilization record `92`, event `47` (`0600`,
  protocol `1169487`).
* Preserved all earlier explicit rejections and added idempotent projection of
  a durable accepted cancellation without rereading an independently committed
  transmission through the caller's stale cursor.
* Closed only the synchronous FE/NCE/NDE plus cancellation/inutilization MVP;
  AFE live validation, receiver events, batch services and production
  hardening remain pending.

## 2026-10-14 — Paraguay NCE accepted in SIFEN TEST

* Closed the first controlled NCE live-validation cycle with document `34199`,
  transmission `61044`, authority `0260` and protocol `50237584`.
* Preserved the earlier explicit rejections (`61042`/`1216` and
  `61043`/`1501`) as interoperability evidence for the corrections that led to
  acceptance.
* Recorded current authoritative final rDE `74631` and NCE KuDE `74632`; NDE
  live validation remains the next document-type milestone.

## 2026-10-14 — SIFEN v150 sale-condition document-type rules

* Corrected NCE/NDE payload and XML generation to omit the complete
  `gCamCond` subtree, which Manual v150 permits only for FE (`01`) and AFE
  (`04`).
* Added fail-closed semantic validation so a credit/debit-note payload carrying
  a sale condition is rejected locally even though the generic XSD marks the
  group as optional.
* Preserved document `34199` and transmission `61043` as the explicit SIFEN
  TEST rejection `1501`; no additional live operation was performed.

## 2026-10-24 — POS fiscal delivery snapshot

* Connected the POS delivery choice to the immutable fiscal snapshot before
  payload persistence. Email/both uses the cashier-confirmed address; print-only
  suppresses automatic email without changing fiscal issuance or manual resend.
* Added offline regression coverage for channel policy, recipient propagation,
  invalid addresses and automatic-delivery suppression.

## 2026-10-24 — POS payment snapshot for SIFEN

* Added explicit SIFEN payment-type configuration to Odoo POS payment methods.
* Captured cash, card, transfer/QR and mixed tenders as an immutable, reconciled
  fiscal snapshot; cash change is netted by method and repeated v150
  `gPaConEIni` groups retain each resulting tender.
* Kept submission and automatic retry disabled; all validation remains offline.

## 2026-10-14 — SIFEN v150 transaction type conditionality

* Corrected NCE/NDE XML generation to omit `iTipTra` and `dDesTipTra`, as the
  v150 Manual requires those fields only for FE (`01`) and AFE (`04`).
* Preserved the first controlled NCE TEST rejection as document `34199`,
  transmission `61042`, authority code `1216`; no retry was performed.
* Revalidated the real NCE document end to end with its configured credential,
  final v150 XSD and stub transport only.
* Added a fail-closed, operator-only recovery classification for complete,
  explicit SIFEN rejections. It preserves the same CDC, rebuilds the canonical
  payload and artifact chain, requires a fresh signature, and never enables
  automatic retry.

## 2026-10-13 — Authoritative Paraguay fiscal email delivery

* Added operator-confirmed and optional company-controlled automatic email
  delivery of authoritative Paraguay KuDE/XML through Odoo's standard mail
  queue. Automatic delivery is disabled by default, uses the immutable receiver
  snapshot, is idempotent, and cannot change fiscal acceptance on mail failure.

## 2026-10-13 — Odoo payment-term snapshots for Paraguay credit operations

* Added immutable PYG installment schedules sourced from posted Odoo
  receivable/payable maturity lines for explicitly selected credit operations.
* Added SIFEN v150 `gPagCred`/`gCuotas` emission, exact total reconciliation and
  KuDE due-date visibility while leaving cash documents unchanged.
* Proved signing, XMLDSig, QR and final official XSD validation offline; no
  automatic submission, payment mutation or SIFEN request was introduced.

## 2026-10-13 — Paraguay Autofactura Electrónica end-to-end offline foundation

* Added the posted Odoo vendor-bill to immutable Paraguay AFE snapshot boundary
  with explicit non-taxpayer/foreign seller identity and transaction-place data.
* Added AFE timbrado/sequence/CDC `04`, official `gCamAE` v150 emission, AFE
  Preview/KuDE/delivery naming and AFE number-inutilization support.
* Proved XML generation, signing, XMLDSig, QR and final official v150 XSD
  validation through stub transport only. Live SIFEN TEST validation is pending.

## 2026-10-13 — Operator-controlled durable SIFEN number inutilization

* Added the Paraguay Fiscal Operator confirmation flow and read-only evidence
  views without enabling automatic events.
* Added an independent boundary that commits the exact fiscal range, event
  identity and request hash before POST and finalizes the same audit record.
* Kept ambiguous results blocked from blind repetition and denied direct user
  creation/editing of authority evidence.

## 2026-10-13 — Operator-controlled durable SIFEN cancellation

* Added the explicit accepted-document cancellation confirmation UI for the
  Paraguay Fiscal Operator group; opening/cancelling the modal has no side
  effects and confirmation delegates to the existing event service.
* Pinned and enforced the official SIFEN v150 event schemas before transport.
* Added an independent durable cancellation boundary that commits request
  identity before POST, blocks ambiguous duplicates, finalizes the same attempt
  and projects accepted crash-recovery evidence without resending.

## 2026-10-13 — Paraguay NDE end-to-end offline foundation

* Integrated Odoo 17's standard debit-note origin with an immutable Paraguay
  NDE snapshot linked to one accepted identified-receiver FE.
* Added independent NDE timbrado/sequence/CDC `06`, correction reason,
  `gCamNCDE`, `gCamDEAsoc`, NDE KuDE preview and existing delivery/submission
  services without duplicating transport or persistence logic.
* Proved signing, XMLDSig, QR and final official v150 XSD validation using
  stubbed transport only. Live SIFEN TEST validation remains pending.

## 2026-10-13 — Paraguay NCE end-to-end offline foundation

* Added the posted Odoo customer-credit-note to immutable Paraguay NCE
  snapshot boundary, requiring an accepted identified-receiver FE and
  preserving its CDC as the single associated electronic document.
* Added independent NCE timbrado/sequence/CDC `05`, allow-listed correction
  reasons, cumulative amount protection, `gCamNCDE`, `gCamDEAsoc`, NCE KuDE
  preview and authoritative delivery compatibility.
* Proved real signing, XMLDSig, QR and final official v150 XSD validation with
  stubbed transport only. No SIFEN request or historical-data change occurred;
  live TEST homologation remains pending.

## 2026-10-12 — Fiscal retry cron deduplication

* Restricted the generic fiscal cron to the latest transmission evidence for
  each `failed_retryable` document, so an expired historical schedule cannot
  repeatedly requeue the same document.
* Consumed older retry schedules whenever a new transmission attempt is
  created and added regressions for future, due and repeated cron execution.
* Kept the Paraguay-specific automatic SIFEN retry cron disabled and made no
  change to manual retry, reconciliation, transport or authority handling.

## 2026-10-12 — Post-baseline AWS KDS smoke test

* Verified AWS STAGING KDS order `#10` / line `#22` from Restaurant POS order
  `00001-010-0001`: one Café with note `PRUEBA KDS AWS 12-OCT`.
* Confirmed exactly one projection for source revision 4 and the complete
  visual transition `new -> preparing -> ready -> done`.
* Recorded one transient browser `Failed to fetch` during the initial reload;
  polling recovered automatically, backend KDS routes stayed healthy and no
  duplicate projection was created.
* Recorded the deliberate development policy: direct `8069` access is
  temporary, STAGING backups remain manual, and physical printer plus
  domain/HTTPS are deferred until production preparation.

## 2026-10-12 — KDS STAGING MVP closure

* Closed the `kds-staging-v1` development/STAGING baseline after successful
  Odoo 17 Restaurant POS, KDS workflow and Epson virtual-printer validation.
* Recorded preparation-note support for initial notes, note-only updates and
  explicit removal without changing active quantities.
* Recorded 41 post-tests / 49 checks with zero failures or errors, successful
  module upgrade, registry/route/view/assets verification and a tested
  database-and-filestore restoration.
* Kept physical printer validation, production-clone compatibility,
  domain/HTTPS, monitoring and production backup policy explicitly outside the
  STAGING MVP.

## 2026-10-10 — STAGING Epson ePOS simulator

* Added a development/STAGING-only Epson ePOS receiver for validating Odoo's
  native preparation-printer output without physical hardware.
* Added bounded capture retention, PNG rendering, token-protected review,
  protocol tests and a secure SSH-tunnel operating procedure.
* Kept the simulator independent from KDS and production; no KDS UI, POS
  workflow, e-Invoice or SIFEN behavior changed.

## 2026-09-08 — KDS POS asset loading correction

* Registered the preparation-revision patch in Odoo 17's real
  `point_of_sale._assets_pos` bundle so the hardened event identity is active
  in Restaurant POS sessions.
* Preserved the native preparation-printer integration and the approved KDS
  display, workflow, polling, sound and styling without frontend redesign.

## 2026-09-07 — Event-aware KDS projection identity

* Replaced snapshot-only projection identity with a monotonic POS preparation
  revision plus content hash, preserving true replay protection while allowing
  a valid `A -> B -> A` cancellation transition.
* Kept legacy projections readable with null revisions and hash-based
  deduplication; the module upgrade invents no history and deletes no records.
* Preserved the native preparation-printer flow and the frozen KDS display,
  polling, interaction and styling contracts.

## 2026-08-27 — Authoritative Paraguay FE delivery completion

* Completed the accepted synchronous FE lifecycle by ensuring the authoritative
  KuDE offline from the accepted current payload/QR/rDE chain after `0260`.
* Decoupled authenticated XML and KuDE resolution so a missing PDF cannot hide
  an otherwise valid accepted final `rDE`.
* Completed document `30219` offline from transmission `46822` (`0260`, protocol
  `49933128`) without changing authority evidence or contacting SIFEN.
* Closed the synchronous FE MVP end-to-end only; NCE/NDE, batch, Consulta RUC,
  received-DTE flows and production hardening remain open.

## 2026-08-18 — Operator-controlled Paraguay SIFEN workflow

* Added explicit, confirmation-gated Odoo actions for initial FE submission,
  guarded manual retry and Consulta DE recovery.
* Added the dedicated **Paraguay Fiscal Operator** group and enforced it in
  both views and the server-side orchestration boundary.
* Reused readiness, durable transmission, current artifact provenance, manual
  retry and reconciliation services without adding automatic submission or
  relaxing CDC/ambiguity protections.
* Exposed safe latest-attempt, authority, protocol, HTTP, duration and ambiguity
  status on fiscal documents and linked the workflow from `account.move`.
* Recorded that the live `29963` → `30867` (`0420`) → `31903` (`1306`)
  sequence validates the guarded same-CDC reconciliation transition.

## 2026-08-13 — Paraguay B2B SIFEN TEST acceptance

* Recorded live acceptance of B2B document `17894` for DNIT-published receiver
  Banco Itaú Paraguay S.A. (`80002201-7`): CDC
  `01032224796001001000000622026080718002274817`, transmission `31916`, code
  `0260`, protocol `49882799`, HTTP `200` in `2150 ms`, non-ambiguous.
* Recorded signing timestamp `2026-08-13T13:11:04` and preserved the exact
  authority message `Autorización del DE satisfactoria`.
* Closed the PKI incident as an active blocker after diagnostic document
  `17886` again reached normal fiscal validation (`31903`, explicit `1306`).
* Marked synchronous FE TEST live-validated for B2C and B2B only; NCE/NDE,
  asynchronous batch, cancellation, inutilization, receiver events and
  production readiness remain outstanding.

## 2026-08-13 — Guarded retry after SIFEN reconciliation not found

* Added an explicit `reconciled_not_found_manual_retry_allowed` evidence state
  for a successful `0420` Consulta DE linked to the same earlier ambiguous,
  post-started synchronous submission and fiscal scope.
* Allowed only an operator-triggered resend of the unchanged DE/CDC, using the
  existing fresh-signing, artifact-provenance and durable pre-POST boundaries.
* Kept `0420` outside rejection and automatic-retry classifications; later or
  contradictory submission/query evidence, acceptance, incomplete hashes and
  scope/CDC mismatches all fail closed without rewriting historical evidence.

## 2026-08-11 — Durable Paraguay DE outbound evidence

* Added an independent-cursor boundary that commits one submit attempt before
  artifact work and its exact request identity before HTTP POST.
* Persisted payload, unsigned XML, signed XML, QR, final rDE and SOAP hashes/IDs
  without storing fiscal XML, CSC or credential material.
* Made post-started transport errors ambiguous and blocked blind resend until
  reconciliation.
* Added explicit recovery for definitely-not-posted `pending` attempts;
  cancellation, inutilization, receiver events and Consulta DE remain outside
  this durability boundary.

## 2026-08-11 — Paraguay retry provenance hardening

* Replaced historical signing-time reuse with an injectable retry-time policy
  using the existing Paraguay timezone and 60-second margin.
* Added current/superseded lifecycle, hash and CDC validation for Paraguay
  payload and unsigned XML artifacts, including fail-closed legacy resolution.
* Linked payload, unsigned XML, signed XML, QR and final rDE versions through
  safe attachment IDs and SHA-256 provenance without deleting history.
* Kept the cron disabled and the SIFEN TEST PKI incident external; cancellation,
  inutilization and receiver events remain partial pending audit gaps.

## 2026-08-10 — Paraguay KuDE presentation

* Redesigned the shared Paraguay KuDE presentation with compact bordered
  fiscal sections, a true item grid, aligned Guaraní totals, grouped CDC,
  clearer consultation footer and optional non-persisted company branding.
* Kept the preview boundary explicitly non-fiscal with a dedicated
  `VISTA PREVIA - SIN VALIDEZ FISCAL` indicator and QR placeholder; accepted
  delivery, QR provenance and artifact lifecycle rules are unchanged.

## 2026-08-09 — Paraguay receiver events

* Added official v150 receipt notification (`10`), conformity (`11`, partial
  or total), disconformity (`12`) and unknown-document (`13`) flows.
* Reused XMLDSig, SOAP 1.2, credentials, mTLS and safe event observability.
* Added scoped audit records, row locking, official time windows, transition
  guards and manual review after ambiguity. No SIFEN request was executed.
* Updated the validation baseline to 589 counted tests across 523 methods.

## 2026-08-09 — Paraguay cancellation and number inutilization

* Added the signed v150 emitter-event boundary over the existing credential and
  mutual-TLS infrastructure, without changing DE submission.
* Added cancellation eligibility, independent transmissions, immutable accepted
  evidence and conservative manual-review handling.
* Added tenant-scoped, locked and idempotent unused-number ranges with issued
  number and prior-range overlap protection.
* Persisted safe transport and authority observability without raw XML or secret
  material. No live SIFEN event was executed.

## 2026-08-09 — Production-safe SIFEN Consulta DE reconciliation

* Exposed dedicated document-query and reconciliation boundaries while keeping
  the Stage 8.24A service names backward compatible.
* Preserved original submission evidence and recorded every query separately
  with safe endpoint, duration, HTTP status, hashes, normalized result and
  authority processing time.
* Treated official `0420` as `reconciliation_not_found`, never as proof of
  rejection or permission to resend; `0422` alone confirms approval.
* Added row-locked, idempotent reconciliation and guarded operator diagnostics.

## 2026-08-09 — Accepted Paraguay document delivery

* Hardened recipient delivery so `state = accepted` alone is insufficient.
  Delivery now requires coherent persisted SIFEN acceptance evidence for the
  same document scope and CDC, through either synchronous `0260` acceptance or
  authoritative Consulta DE `0422` reconciliation.
* Kept UI downloads and email preparation on the same fail-closed service
  boundary and documented fiscal preview as separate from recipient delivery;
  no local/demo bypass was introduced.
* Added an authenticated, ephemeral KuDE Preview boundary for visual inspection
  of complete Paraguay invoice payloads before acceptance. Preview output is
  unmistakably non-fiscal, fabricates no QR, persists no artifact and cannot
  satisfy recipient-delivery eligibility.

* Added a versioned final `rDE` artifact after QR/XSD validation and before the
  existing SOAP submission boundary.
* Added side-effect-free resolution of the current accepted KuDE/XML pair with
  deterministic recipient filenames, integrity checks, and email preparation.
* Added authenticated UUID-scoped PDF/XML downloads with tenant record-rule and
  company enforcement; arbitrary attachment IDs and superseded/internal
  artifacts are never exposed.
* Kept rejected, ambiguous, unfinished, failed, and cancelled documents outside
  final-recipient delivery. No mail sender, ZIP bundle, or audit model was added.
* Updated the validation baseline to 548 counted tests across 484 methods.

## 2026-08-07 — Authority incident observability and manual retry guard

* Persisted safe endpoint, HTTP status and measured duration for new SIFEN
  transmissions, plus a sensitive normalized-response artifact and raw-body
  SHA-256 without duplicating authority response bytes.
* Separated exceptional authority incidents from fiscal result codes. Only the
  exact `0100` / `Error Inesperado(PKI)` combination permits a controlled
  manual retry; it remains rejected, non-ambiguous and never auto-retryable.
* Added a CDC-scoped guard that blocks accepted and ambiguous submissions and
  requires a fresh signing timestamp before delegating to the existing
  persistence pipeline.

## 2026-08-07 — B2B TEST receiver gate resolved offline

* Recorded DNIT support confirmation that the SIFEN TEST taxpayer dataset is
  not synchronized with Production and that homologation receivers should be
  selected from DNIT's published electronic-taxpayer list.
* Preserved document `17886` and transmission `18534` as non-ambiguous `1306`
  evidence; they must not be retried or rewritten.
* Prepared fresh document `17894` with a DNIT-published electronic taxpayer and
  validated its two-item B2B cash flow through payload, unsigned/signed XML,
  XMLDSig, QR, rDE/XSD, SOAP 1.2, credential readiness, manifest and KuDE.
* Reclassified B2B from `BLOCKED BY TEST AUTHORITY DATA` to `REQUIRES LIVE TEST`.
  No SIFEN request or Consulta DE was performed.

## 2026-08-06 — Payload-first KuDE PDF

* Added deterministic Factura Electrónica KuDE rendering from the persisted
  normalized payload and exact persisted QR URL; XML, SOAP, CSC and authority
  responses are excluded from the renderer boundary.
* Added current/superseded lifecycle metadata for QR and KuDE fiscal artifacts,
  with document locking, idempotent regeneration and preserved audit history.
* Selected direct ReportLab rendering over HTML/wkhtmltopdf to avoid external
  renderer, font and CSS variability.
* Recorded Manual Técnico SIFEN v150 chapter 13 content, pagination,
  consultation and QR requirements, plus the invoice-only initial scope.
* Updated the validation baseline to 524 counted tests across 464 methods.
* Added explicit TEST/PRODUCTION projection and width-aware item-description
  wrapping after the first offline visual KuDE validation.

## 2026-08-06 — B2B TEST authority-data evidence

* Prepared and structurally validated the controlled B2B FE pipeline using
  current official receiver evidence.
* Preserved document `17886` and transmission `18534`, explicitly rejected by
  SIFEN TEST with `1306` because masked receiver `380****-*` is absent from the
  TEST Marangatu dataset.
* Verified the signed XML RUC/DV split, taxpayer/B2B classification and official
  geographic mappings; no code or local configuration defect was found.
* Classified B2B coverage as `BLOCKED BY TEST AUTHORITY DATA` pending DNIT
  provisioning or an authority-supplied TEST receiver. No universal public TEST
  receiver RUC was identified.
* Documented safe escalation, privacy controls and the rule that an explicit,
  non-ambiguous `1306` requires no Consulta DE.

## 2026-08-06 — Homologation scope matrix

* Compared the repository with DNIT's February 2026 testing guide.
* Separated authority minimum tests from optional technical profiles and
  unsupported services.
* Selected a two-item B2B cash FE as the next incremental profile, blocked
  pending real authorized receiver data; no document or CDC was created.

## 2026-08-06 — First accepted SIFEN TEST DE

* Recorded the first controlled synchronous SIFEN TEST acceptance (`0260`).
* Documented authority-driven corrections for fiscal timezone handling,
  signing clock margin, signed-artifact versioning, official catalog data,
  VAT-inclusive totals, receiver data, and TEST CSC configuration.
* Updated the validation baseline to 511 counted tests across 453 methods.
* Clarified that one accepted invoice profile is an interoperability milestone,
  not production authorization or completion of the homologation matrix.
* Registered remaining technical debt and evidence gates before considering
  cross-country abstractions for Costa Rica.
## 2026-08-11 — Odoo invoice fiscal snapshot integration

- Added the neutral posted `account.move` to `fiscal.document` snapshot service,
  relational/source provenance and database-backed idempotency.
- Added explicit Paraguay IVA 10%, IVA 5% and exempt mappings plus validated
  B2B taxpayer and unnamed B2C receiver profiles.
- Added invoice preparation/status UI and offline KuDE Preview integration;
  preparation never calls SIFEN.
- Protected snapshotted invoices against unsafe source edits, reset or
  cancellation and aligned CDC dates with Paraguay civil time.
