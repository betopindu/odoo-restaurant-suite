# Documentation Changelog

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
