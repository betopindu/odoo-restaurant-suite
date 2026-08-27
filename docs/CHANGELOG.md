# Documentation Changelog

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
