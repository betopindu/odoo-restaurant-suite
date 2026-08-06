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
* **BLOCKED BY TEST AUTHORITY DATA**: current official input is available and
  structurally valid locally, but the authority has not provisioned the
  required taxpayer data in its TEST dataset.

| Scenario | Status | Repository evidence and exact gap |
| --- | --- | --- |
| B2C FE, innominado, cash, IVA 10% | READY | Complete payload-to-persistence path; first live acceptance `0260`. The accepted FE had one item, so it is not by itself the guide's two-item/five-FE minimum. |
| B2B FE to Paraguayan taxpayer | BLOCKED BY TEST AUTHORITY DATA | Current receiver evidence was obtained from a Constancia de RUC and Cédula Tributaria. Document `17886` was locally validated and transmission `18534` proved that the B2B XML mapping is structurally correct, but SIFEN TEST rejected it with `1306` because masked receiver `380****-*` is absent from the TEST Marangatu dataset. No public universal TEST receiver RUC is documented. |
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
| Ambiguous POST and Consulta DE | REQUIRES LIVE TEST | Timeout normalization, CDC blocking, SOAP Consulta DE, `0422`/`0420` reconciliation and idempotency are tested without network. No live ambiguous outcome should be manufactured. |
| QR generation/authority validation | READY | Deterministic QR uses the exact final XMLDSig digest and official TEST CSC pair; the accepted DE proves SIFEN validation for the baseline. Browser QR consultation counts remain pending. |
| KuDE PDF and delivery | NOT IMPLEMENTED | QR URL exists, but no KuDE/PDF renderer, delivery or KuDE test matrix exists. |
| Cancellation and inutilization | NOT IMPLEMENTED | Core has a cancelled state, but Paraguay event SOAP/XML, authority response and persistence services do not exist. |
| Receiver events | NOT IMPLEMENTED | No Paraguay receiver-event implementation. |
| General DTE/event consultation | PARTIAL | TEST Consulta DE by CDC exists for ambiguous reconciliation; general consultation matrix and associated-event output are absent. |
| Asynchronous batch submission/result | NOT IMPLEMENTED | Current submission is synchronous only. |
| Synchronous SOAP, mTLS and response persistence | READY | SOAP 1.2, qualified PKCS#12, mTLS, parser and persistence are implemented and live-proven for FE. |

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

Official receiver evidence is now available locally and the normalized B2B
snapshot contains a valid RUC/DV split, taxpayer nature/type, legal name and
official geography. The signed request was nevertheless rejected explicitly
with `1306`, `RUC del receptor inexistente en la base de datos de Marangatu`.
This establishes an external TEST-data prerequisite, not a local mapping or
configuration defect.

The DNIT testing guide requires real customer data but does not state that all
ordinary Marangatu taxpayers are automatically replicated into SIFEN TEST and
does not publish a universal receiver RUC. Do not try generated, approximate or
random taxpayer identifiers. Continue only after DNIT provisions the intended
receiver in TEST or supplies an authorized TEST receiver dataset in writing.

## Live authorization gate

After DNIT confirms provisioning, document `17886` may be regenerated with a
fresh signing timestamp and submitted once through
`PySifenTransmissionPersistenceService.submit_and_persist()`. Rejection `1306`
was explicit and non-ambiguous, so Consulta DE is not required. Preserve
transmission `18534` as authority evidence and do not replace its receiver with
an unverified RUC.
