# Paraguay SIFEN TEST Homologation Matrix

[Documentation Home](../README.md) -> [Paraguay](README.md) -> Homologation Matrix

## Purpose and authority sources

This matrix separates the official TEST exercise scope from repository
capability. It does not turn every SIFEN feature into an immediate development
requirement and it does not claim habilitation from one accepted DE.

Sources reviewed initially on 2026-08-06 and revalidated on 2026-10-27:

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

## Audited execution ledger (2026-10-25)

This ledger converts the guide into countable authority evidence. Counts are
conservative: repeated queries of one CDC count as one DTE, an accepted FE
counts toward the approval minimum only when it has at least two items, and
offline tests never count as SIFEN TEST executions. DNIT remains the authority
that decides whether preserved evidence satisfies the habilitation ticket.

| Official case | Required | Preserved qualifying evidence | Remaining | Status |
| --- | ---: | ---: | ---: | --- |
| Synchronous FE approvals (minimum two items) | 5 | 2 (`17894`, `30219`) | 3 | INCOMPLETE |
| Synchronous NCE approvals | 5 | 1 (`34199`) | 4 | INCOMPLETE |
| Synchronous NDE approvals | 5 | 1 (`34200`) | 4 | INCOMPLETE |
| Synchronous AFE approvals | 5 | 1 (`34204`, acceptance recovered by Consulta DE) | 4 | INCOMPLETE |
| Synchronous NRE approvals | 5 | 0 | 5 | BLOCKED — NRE not implemented |
| Synchronous FE rejections with different errors | 5 | at least 5 (`1004`, `1257`, `1261`, `1313`, `1326`, `2359`, `2501`) | 0 | COUNT COMPLETE; DNIT confirmation pending |
| Synchronous NCE rejections with different errors | 5 | 2 (`1216`, `1501`) | 3 | INCOMPLETE |
| Synchronous NDE rejections with different errors | 5 | 0 | 5 | INCOMPLETE |
| Synchronous AFE rejections with different errors | 5 | 5 (`1316`, `2562`, `1901`, `2400`, `0160`) | 0 | COUNT COMPLETE; DNIT confirmation pending |
| Synchronous NRE rejections with different errors | 5 | 0 | 5 | BLOCKED — NRE not implemented |
| Asynchronous approvals, all five DE types | 25 | 0 | 25 | BLOCKED — batch submission/result not implemented |
| Asynchronous rejections, all five DE types | 25 | 0 | 25 | BLOCKED — batch submission/result not implemented |
| Issuer cancellation events | 5 | 1 (`34200` / `61051`) | 4 | INCOMPLETE |
| FE number inutilizations | 2 | 0 | 2 | INCOMPLETE |
| NCE number inutilizations | 1 | 0 | 1 | INCOMPLETE |
| NDE number inutilizations | 1 | 1 (record `92`) | 0 | COUNT COMPLETE; DNIT confirmation pending |
| AFE number inutilizations | 1 | 0 | 1 | INCOMPLETE |
| Receiver events (five classes, three each) | 15 | 0 | 15 | BLOCKED — received-DTE/operator flow incomplete |
| Consulta DTE — FE | 3 distinct DTE | 1 (`16106`) | 2 | INCOMPLETE |
| Consulta DTE — NCE | 3 distinct DTE | 0 | 3 | INCOMPLETE |
| Consulta DTE — NDE | 3 distinct DTE | 0 | 3 | INCOMPLETE |
| Consulta DTE — AFE | 3 distinct DTE | 1 (`34204`) | 2 | INCOMPLETE |
| Consulta DTE — NRE | 3 distinct DTE | 0 | 3 | BLOCKED — NRE not implemented |
| KuDE PDF — FE/NCE/NDE/AFE | 1 each | 4 of 4 | 0 | COMPLETE for implemented types |
| KuDE PDF — NRE | 1 | 0 | 1 | BLOCKED — NRE not implemented |
| QR consultations — FE/NCE/NDE/AFE | 8 | 0 preserved browser-result records | 8 | INCOMPLETE |
| QR consultations — NRE | 2 | 0 | 2 | BLOCKED — NRE not implemented |

The local authority-evidence database also contains four accepted FE with only
one item (`16106`, `32231`, `34205`, `34206`). They remain valid interoperability
evidence but do not reduce the five-FE minimum because the guide explicitly
requires at least two items for that row. The separate AWS STAGING POS FE also
has one item and is therefore excluded from that count.

### Completion boundary

The full published matrix cannot be completed by merely sending more current
documents. It first requires three capabilities deliberately left outside the
Commercial V1 baseline: NRE, asynchronous batch submission/result, and the
complete receiver-event/received-DTE operator workflow. Completing only the
currently implemented synchronous Commercial V1 subset is not equivalent to
completing the full DNIT matrix unless DNIT explicitly narrows the taxpayer's
habilitation scope in its ticket.

Before any further live execution, record in the DNIT ticket which document
types and roles are being enabled and obtain confirmation whether NRE,
asynchronous services and receiver-role events are required for this specific
habilitation. No accepted CDC listed above may be sent again.

### Ordered completion plan

The next work is split so that more TEST traffic is not generated before its
scope can count toward habilitation:

1. **Authority scope gate.** In the existing DNIT habilitation ticket, record
   the intended first commercial scope (FE, NCE, NDE and AFE; synchronous
   issuance; issuer cancellation and inutilization) and ask DNIT to confirm
   whether the ticket still requires NRE, asynchronous batch/result services
   and receiver-role events. This is a scope confirmation, not a request to
   waive technical validation.
2. **Offline capability closure.** If DNIT requires the complete published
   matrix, implement and validate NRE, asynchronous batch submission/result
   and the received-DTE/receiver-event operator boundary before any additional
   live count execution. If DNIT accepts the narrower enabled set, keep those
   capabilities after Commercial V1 and proceed only with the confirmed rows.
3. **Controlled TEST evidence.** Prepare fresh numbers and immutable execution
   records for the remaining approvals, distinct intentional rejections,
   cancellation/inutilization, Consulta DTE and QR rows. Each POST or authority
   consultation remains a separately authorized live operation; accepted CDCs
   and terminal event evidence are never reused.
4. **Evidence submission.** Reconcile the preserved ledger with the DNIT
   ticket, attach the requested evidence, and obtain explicit production
   habilitation before configuring or enabling production endpoints.

As of 2026-10-27, step 1 is the only external gate. The current repository can
prepare and test the implemented synchronous subset offline, but it cannot
truthfully claim the complete published homologation matrix while the blocked
capabilities above remain absent.

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
| Credit sale with installments | READY | Posted Odoo payment terms are snapshotted into immutable PYG installment schedules; `gPagCred`/`gCuotas`, due dates and exact total reconciliation are covered offline. Live authority evidence remains pending. |
| Credit note | LIVE-VALIDATED | Posted Odoo refunds create an immutable NCE linked to one accepted identified-receiver FE, with independent CDC `05`, reason, cumulative amount guard, `gCamNCDE`, `gCamDEAsoc`, signing, XMLDSig, QR, final v150 XSD and KuDE. Document `34199`, transmission `61044`, was accepted with `0260`, protocol `50237584`; earlier `61042`/`1216` and `61043`/`1501` rejections preserve the interoperability trail. |
| Debit note | LIVE-VALIDATED | Odoo's standard debit-note origin creates an immutable NDE linked to one accepted identified-receiver FE. Document `34200`, CDC `06032224796001001000000122026102217549779160`, transmission `61045`, was accepted with `0260`, protocol `50276074`. |
| Autofactura | LIVE-VALIDATED | The posted-vendor-bill pipeline emits AFE transaction type `10`, receiver operation type B2C, tax type `4`, no per-item `gCamIVA`, no prohibited `F017/dTotIVA`, QR fallback `dTotIVA=0`, and the mandatory electronic non-taxpayer constancy association. Document `34204`, CDC `04032224796001001000000322026102215594656963`, preserves `61056` (`2400`) and pre-fix `61057` (`0160`, HTTP 400). Corrected retry `61058` returned `1001` duplicate; operator-requested Consulta DE `61060` returned `0422`, protocol `50276195`, proving acceptance. Authoritative final rDE `74708` and KuDE `74717` complete delivery. |
| Duplicate submission | PARTIAL | Response parser distinguishes configured duplicate codes and persistence blocks accidental resend of accepted CDCs. There is no operator-safe intentional duplicate homologation operation. |
| Explicit rejection | READY | Parser/persistence tests plus preserved live rejection evidence demonstrate non-ambiguous rejection handling. |
| Ambiguous POST and Consulta DE | LIVE-VALIDATED | Timeout normalization, CDC blocking, row-locked SOAP Consulta DE, immutable submission evidence, `0422` acceptance and `0420` `reconciliation_not_found` are live-observed. The guarded transition was exercised by ambiguous submission `29963`, linked Consulta DE `30867` (`0420`) and same-CDC manual retry `31903` (`1306`). `0420` is not a rejection or automatic-retry category, and newer/conflicting evidence still blocks retry. |
| QR generation/authority validation | READY | Deterministic QR uses the exact final XMLDSig digest and official TEST CSC pair; the accepted DE proves SIFEN validation for the baseline. Browser QR consultation counts remain pending. |
| KuDE PDF generation and accepted delivery | LIVE-VALIDATED | The invoice renderer consumes only persisted payload plus the exact persisted QR URL and produces deterministic/versioned PDF artifacts. Accepted document `30219` / transmission `46822` (`0260`, protocol `49933128`) has current authoritative KuDE `59605` and final rDE `59582`; both recipient files resolve independently with matching CDC, valid XMLDSig and XSD v150. The KuDE completion itself is offline and makes no authority request. |
| Cancellation | LIVE-VALIDATED | NDE `34200` was cancelled by transmission `61051`, authority `0600`, protocol `1169485`, HTTP 200 and non-ambiguous. The accepted DE and rejected event attempts remain immutable; the accepted durable result was projected idempotently without another POST. |
| Inutilization | LIVE-VALIDATED | Controlled unused NDE number `0000003` under timbrado `03222479` was accepted as record `92`, event `47`, authority `0600`, protocol `1169487`, HTTP 200 and non-ambiguous. Prior rejected range `0000002` remains preserved. |
| Receiver events | PARTIAL | Notification `10`, conformity `11`, disconformity `12` and unknown-document `13` have offline request/persistence and official event-XSD coverage; the received-DTE boundary, independent durable POST boundary, operator workflow and live authority evidence remain incomplete. |
| General DTE/event consultation | PARTIAL | TEST Consulta DE by CDC exists for ambiguous reconciliation; general consultation matrix and associated-event output are absent. |
| Asynchronous batch submission/result | NOT IMPLEMENTED | Current submission is synchronous only. |
| Synchronous SOAP, mTLS and response persistence | READY | SOAP 1.2, qualified PKCS#12, mTLS, parser and persistence are implemented and live-proven for FE. |
| Retry freshness and artifact provenance | READY | Manual and scheduled retries resolve one current hash/CDC-validated payload, use a fresh centralized signing instant and persist a linked, versioned payload/unsigned/signed/QR/rDE chain. Cron remains disabled. |

The historical `0100 - Error Inesperado(PKI)` incident remains preserved but
is no longer an active TEST blocker: controlled document `17886` again reached
normal fiscal validation (`1306`) and document `17894` was subsequently
accepted (`0260`). `0100` remains ineligible for automatic retry.

Country-neutral core support does not imply Paraguay protocol support. In
particular, a neutral document/event value alone is not implementation of its
corresponding SIFEN XML/service contract. NCE, NDE and AFE now have complete
accounting-to-delivery paths with live SIFEN TEST evidence. Official case-count
completion and production readiness remain separate milestones.

## Next live work

No accepted CDC in this matrix may be resubmitted. The next live operation
must be selected from the remaining official homologation counts, use a fresh
document/number where applicable, and receive separate explicit authorization.
This documentation closure does not select or authorize that operation.

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
