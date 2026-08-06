# Documentation Changelog

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
* Updated the validation baseline to 523 counted tests across 463 methods.

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
