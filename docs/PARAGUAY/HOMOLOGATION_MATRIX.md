# Paraguay SIFEN TEST Homologation Matrix

[Documentation Home](../README.md) -> [Paraguay](README.md) -> Homologation Matrix

## Purpose and authority sources

This matrix separates the official TEST exercise scope from repository
capability. It does not turn every SIFEN feature into an immediate development
requirement and it does not claim habilitation from one accepted DE.

Sources reviewed on 2026-08-06:

* [DNIT Guía de Pruebas para el Sistema e-kuatia, February 2026](https://www.dnit.gov.py/documents/20123/424160/Guia%2Bde%2BPruebas%2Bpara%2Be-kuatia.pdf/715a15bf-d866-afe3-49e2-c10e05242c95?t=1770659877488.pdf), especially sections 2, 3 and 4.1–4.5.
* [DNIT Manual Técnico SIFEN v150](https://www.dnit.gov.py/documents/20123/420592/Manual%2BT%C3%A9cnico%2BVersi%C3%B3n%2B150.pdf/e706f7c7-6d93-21d4-b45b-5d22d07b2d22?t=1687362295907.pdf), including document groups, transmission, events, consultation and KuDE rules.
* [DNIT Guía paso a paso de habilitación](https://www.dnit.gov.py/documents/d/global/guia-paso-a-paso-solicitud-y-habilitacion-de-facturadores-electronicos), steps 2, 4 and 6.
* [DNIT e-Kuatia technical portal](https://www.dnit.gov.py/web/e-kuatia/ekuatia), which identifies Manual v150 and its technical notes as the current technical baseline.
* [DNIT FAQ on delivery to the receiver](https://www.dnit.gov.py/web/e-kuatia/preguntas-frecuentes/-/categories/2705316), which requires KuDE delivery to a non-electronic receiver or final consumer.

The February 2026 testing guide calls these the minimum suggested tests and
asks taxpayers to exercise all SIFEN services and functionality. Final
acceptance of the evidence remains an authority decision through the taxpayer's
DNIT habilitation ticket.

## Official minimum scope

The guide defines the following minimum matrix:

| Official area | Minimum described by the guide | Classification | Exact source |
| --- | --- | --- | --- |
| mTLS access | One valid-certificate connection to each synchronous, asynchronous, batch-result, Consulta DE, event and RUC service; invalid certificate is recommended | Mandatory/minimum for the enabled service set; negative certificate is recommended | Guía de Pruebas §4.1, pp. 5–6 |
| Synchronous approval | Five each of FE, NCE, NDE, AFE and NRE; FE has at least two item groups | Mandatory/minimum when those document types are included in the taxpayer TEST set | Guía de Pruebas §4.2, p. 6 |
| Synchronous rejection | Five different incorrect cases for each enabled DE type | Mandatory/minimum | Guía de Pruebas §4.2, p. 7 |
| Asynchronous approval/rejection | Five of each enabled DE type in batches, with the guide also recommending realistic batch sizes | Mandatory/minimum; not covered by the synchronous baseline | Guía de Pruebas §4.2, p. 7 |
| Issuer events | Five cancellations; inutilization counts for FE, NCE, NDE and AFE numbering | Mandatory/minimum event coverage | Guía de Pruebas §4.3, p. 8 |
| Receiver events | Three each of conformity, disagreement, unknown operation, receipt notification and event adjustment | Mandatory/minimum when exercising the receiver role | Guía de Pruebas §4.3, p. 8 |
| DTE consultation | Three each of FE, NCE, NDE, AFE and NRE | Mandatory/minimum for enabled types | Guía de Pruebas §4.4, p. 8 |
| KuDE | One PDF representation for each enabled DTE type | Mandatory/minimum | Guía de Pruebas §4.5, p. 9 |
| QR consultation | Two QR consultations for each enabled DTE type | Mandatory/minimum | Guía de Pruebas §4.5, p. 9 |

The guide does not separately mandate B2B versus B2C, each VAT bucket, cash
versus credit, duplicate submission or ambiguous transport as individual test
rows. They are useful coverage profiles, but must not be misrepresented as
explicit guide counts. Section 2 does require real receiver/customer data and
the taxpayer's real registered issuer data; synthetic RUC or approximate
catalog values are not acceptable substitutes (Guía de Pruebas §2, p. 4).

## Repository capability matrix

Status meanings:

* **READY**: implemented and covered locally; may also have live evidence.
* **PARTIAL**: some layers exist but the scenario is not complete end to end.
* **NOT IMPLEMENTED**: a required country behavior or service is absent.
* **REQUIRES OFFICIAL DATA**: implementation exists but authoritative fiscal
  input is unavailable.
* **REQUIRES LIVE TEST**: deterministic local coverage exists but authority
  behavior has not been exercised.
* **LIVE-VALIDATED**: the exact profile has preserved successful SIFEN TEST
  authority evidence; this does not imply production readiness.
* **BLOCKED BY TEST AUTHORITY DATA**: current official input is available and
  structurally valid locally, but the authority has not provisioned the
  required taxpayer data in its TEST dataset.

| Scenario | Status | Repository evidence and exact gap |
| --- | --- | --- |
| B2C FE, innominado, cash, IVA 10% | LIVE-VALIDATED | Complete payload-to-persistence path; document `16106`, transmission `17896`, accepted with `0260`. The accepted FE had one item, so it is not by itself the guide's two-item/five-FE minimum. |
| B2B FE to Paraguayan taxpayer | LIVE-VALIDATED | DNIT-published receiver Banco Itaú Paraguay S.A. (`80002201-7`): document `17894`, CDC `01032224796001001000000622026080718002274817`, transmission `31916`, accepted with `0260`, protocol `49882799` on 2026-08-13. Historical document `17886` remains evidence that arbitrary valid Production taxpayers may be absent from TEST. |
| IVA 10% | READY | Item/base/VAT/subtotal calculations, XML and focused tests exist; live accepted baseline. |
| IVA 5% | REQUIRES LIVE TEST | Decimal calculations and XML/tests exist; no live authority evidence. |
| Exempt item | REQUIRES LIVE TEST | Exempt bucket and XML/tests exist; no live authority evidence. |
| Mixed exempt/5%/10% FE | PARTIAL | Builder aggregates separate buckets, but there is no focused full-pipeline mixed-rate regression vector or live evidence. |
| Cash sale | READY | `gCamCond/gPaConEIni`, payment and accepted live baseline. |
| Credit sale with installments | NOT IMPLEMENTED | Selection fields exist, but the builder always emits initial-payment `gPaConEIni`; credit schedule/installment groups and models are absent. |
| Credit note | NOT IMPLEMENTED | Neutral type and Paraguay CDC code exist, but NCE-specific associated-document/reason XML groups and end-to-end tests are absent. |
| Debit note | NOT IMPLEMENTED | Neutral type and Paraguay CDC code exist, but NDE-specific associated-document/reason XML groups and end-to-end tests are absent. |
| Duplicate submission | PARTIAL | Response parser distinguishes configured duplicate codes and persistence blocks accidental resend of accepted CDCs. There is no operator-safe intentional duplicate homologation operation. |
| Explicit rejection | READY | Parser/persistence tests plus preserved live rejection evidence demonstrate non-ambiguous rejection handling. |
| Ambiguous POST and Consulta DE | LIVE-VALIDATED | Timeout normalization, CDC blocking, row-locked SOAP Consulta DE, immutable submission evidence, `0422` acceptance and `0420` `reconciliation_not_found` are live-observed. The guarded transition was exercised by ambiguous submission `29963`, linked Consulta DE `30867` (`0420`) and same-CDC manual retry `31903` (`1306`). `0420` is not a rejection or automatic-retry category, and newer/conflicting evidence still blocks retry. |
| QR generation/authority validation | READY | Deterministic QR uses the exact final XMLDSig digest and official TEST CSC pair; the accepted DE proves SIFEN validation for the baseline. Browser QR consultation counts remain pending. |
| KuDE PDF generation | READY | The invoice renderer consumes only persisted payload plus the exact persisted QR URL, produces deterministic/versioned PDF artifacts, and has unit/integration, regeneration, multipage and idempotency coverage. Live receiver delivery remains operational work. |
| Cancellation and inutilization | PARTIAL | Signed event XML/SOAP, locking and persistence exist, but complete associated-DTE/receiver-event eligibility and official event-XSD evidence remain pending. |
| Receiver events | PARTIAL | Notification `10`, conformity `11`, disconformity `12` and unknown-document `13` have offline request/persistence coverage; the received-DTE boundary and official event-XSD validation remain incomplete. |
| General DTE/event consultation | PARTIAL | TEST Consulta DE by CDC exists for ambiguous reconciliation; general consultation matrix and associated-event output are absent. |
| Asynchronous batch submission/result | NOT IMPLEMENTED | Current submission is synchronous only. |
| Synchronous SOAP, mTLS and response persistence | READY | SOAP 1.2, qualified PKCS#12, mTLS, parser and persistence are implemented and live-proven for FE. |
| Retry freshness and artifact provenance | READY | Manual and scheduled retries resolve one current hash/CDC-validated payload, use a fresh centralized signing instant and persist a linked, versioned payload/unsigned/signed/QR/rDE chain. Cron remains disabled. |

The historical `0100 - Error Inesperado(PKI)` incident remains preserved but
is no longer an active TEST blocker: controlled document `17886` again reached
normal fiscal validation (`1306`) and document `17894` was subsequently
accepted (`0260`). `0100` remains ineligible for automatic retry.

Country-neutral core support does not imply Paraguay protocol support. In
particular, a neutral `credit_note`, `debit_note` or `cancelled` value is not an
implementation of the corresponding SIFEN XML/service contract.

## Selected next scenario

The safest incremental live scenario is:

* synchronous TEST Factura Electrónica;
* B2B receiver that is a real Paraguayan taxpayer;
* cash operation in PYG;
* at least two item groups taxed at IVA 10%;
* current qualified certificate, TEST timbrado, CSC and existing synchronous
  pipeline;
* a fresh document number and CDC.

This reuses every live-proven boundary, adds taxpayer-receiver coverage and
aligns with the guide's minimum two-item FE shape. It does not depend on credit
schedules, associated documents, events, KuDE rendering or asynchronous batch
services.

### External TEST receiver-data gate

Official receiver evidence is available locally and the normalized B2B
snapshot contains a valid RUC/DV split, taxpayer nature/type, legal name and
official geography. The first signed request was nevertheless rejected
explicitly with `1306`, `RUC del receptor inexistente en la base de datos de
Marangatu`. DNIT support subsequently confirmed that the TEST taxpayer dataset
is not synchronized with Production and recommended selecting at least five
receivers from the electronic taxpayers published by DNIT.

This is an external TEST-data rule, not a local mapping correction. Banco Itaú
Paraguay S.A. appears in DNIT's [Resolution 06/18 electronic-taxpayer
list](https://www.dnit.gov.py/web/portal-institucional/w/resolucion-general-n-06/18)
and in the [published electronic-taxpayer list dated
2024-10-31](https://ekuatia.set.gov.py/documents/20123/473596/Facturadores%2BElectr%C3%B3nicos%2Bal%2B31-10-2024.pdf/648ec052-1e3c-e897-c9c8-7af2762d1dcd?t=1730484481868).
Document `17894` used that public authority evidence and was accepted by SIFEN
TEST through transmission `31916`, code `0260`, protocol `49882799`. Never try
generated, approximate or random taxpayer identifiers after `1306`.

## Live authorization gate

Preserve document `17886` and its transmissions as authority evidence of both
the stale receiver dataset and the resolved PKI incident. Document `17894` is
now accepted and must not be submitted again. Any further live scenario
requires a separate document, evidence-based scope and explicit authorization.
