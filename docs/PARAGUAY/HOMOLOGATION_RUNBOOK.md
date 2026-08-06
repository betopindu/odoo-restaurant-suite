# SIFEN TEST Homologation Runbook

[Documentation Home](../README.md) -> [Paraguay](README.md) -> Homologation

See the [capability and homologation matrix](HOMOLOGATION_MATRIX.md) before
selecting the next case. A locally supported profile is not necessarily one of
the authority's minimum test rows.

The first controlled synchronous TEST DE has been accepted. This runbook now
records that baseline and remains the procedure for subsequent homologation
cases. Acceptance of one DE is not production authorization.

## Before each controlled live submission

1. Complete the [SIFEN TEST configuration](CONFIGURATION.md).
2. Install the qualified taxpayer PKCS#12 outside source control.
3. Validate certificate structure, chain information, validity, RSA key,
   certificate/private-key match, RUC/DV, `digitalSignature`,
   `contentCommitment`, and `clientAuth`.
4. Validate CSC and fiscal scope.
5. Run the local readiness check.
6. Run the TEST connection preflight. An HTTP response proves that DNS, TCP,
   TLS, client-certificate presentation, server verification, and endpoint
   access reached the HTTP layer; it does not prove DE acceptance.
7. Prepare one controlled document with a CDC that has not been submitted.

## During submission

Use the isolated `PySifenSubmissionService.submit()` procedure documented in
[Paraguay](README.md#first-live-submission-procedure) exactly once.

Capture only safe diagnostics: stage, CDC, `dId`, HTTP status, fixed error
category, hashes, and the authority code/message. Preserve the raw authority
response in protected operational evidence. Do not log signed XML,
certificates, PKCS#12 bytes, private keys, CSC, passwords, secret references,
or complete sensitive paths.

Do not automatically retry after a timeout, connection loss after POST, or
worker failure. Treat the outcome as ambiguous and use the existing Consulta
DE reconciliation by CDC before any operator-authorized resend.

## After submission

Classify the outcome as transport failure, HTTP error, SOAP Fault, malformed
response, accepted, rejected, duplicate, or unknown authority code. HTTP 200
alone is not acceptance.

Record undocumented authority behavior as evidence. Make only focused
interoperability corrections supported by that evidence. Stage 8.24B durable
pre-POST persistence remains postponed until homologation demonstrates that
the current controlled procedure is insufficient.

After the first accepted DE, execute the official homologation cases. Do not
enable production, cron, or unattended retry as part of the first request.

## Expected accepted response

The parser requires the SOAP 1.2 `rRetEnviDe/rProtDe` hierarchy. Acceptance is
reported by the official approved state or code `0260`; `dProtAut` is recorded
only when returned by SIFEN. SOAP Faults and business rejections remain
different outcomes.

## Homologación SIFEN TEST v1

The controlled sequence preserved every rejected transmission and derived
artifact. Corrections were made only from explicit authority evidence; no
historical transmission or attachment was deleted.

| Authority result | Root cause | Resolution and validation | Why generic |
| --- | --- | --- | --- |
| `1004` | A naive Odoo UTC instant was initially serialized as if already Paraguay civil time; a second attempt exposed practical clock skew. | Centralized UTC-to-`America/Asuncion` conversion and an explicit 60-second signing safety margin; timezone/DST tests and local XML verification. | Depends on an instant and country timezone, never host location or taxpayer data. |
| `1257` | District description did not correspond to the configured official code. | Corrected TEST establishment configuration from the official geographic catalog; XSD and offline pipeline revalidated. | Catalog consistency is configuration-scoped. No document-specific branch was added. |
| `1261` | Synthetic economic activity was not registered for the issuer. | Replaced it with the principal activity from the taxpayer's official RUC record. | Activities remain issuer configuration; the builder emits ordered active records. |
| `1313` | Receiver identity-type description did not correspond to its code. | Corrected the non-contributor/innominado receiver snapshot using the official table. | Identity mapping remains document data validated by normal XML rules. |
| `1326` | Optional receiver geography carried an inconsistent district description. | Removed optional innominado geography rather than fabricating codes. | Optionality follows receiver semantics, not a specific customer. |
| `2359` | The payload mixed net-base and VAT-inclusive subtotal conventions. | One Decimal path now derives item base/VAT and document 5%/10% subtotals from VAT-inclusive operation values; focused 5%, 10%, decimal, discount and partial-tax tests. | Calculation is item-driven and independent of the homologated amount or document. |
| `2501` | `IdCSC=0001` was paired with a non-official TEST CSC value. | Corrected operational TEST configuration; independently recalculated `cHashQR` from the exact final signed `DigestValue`. | QR algorithm and CSC lookup are environment/configuration driven. No secret or taxpayer literal was added to code. |
| `0260` | Final request satisfied the authority contract. | Document `16106`, transmission `17896`, accepted with `Autorización del DE satisfactoria`. | Confirms composition of the generic Paraguay services for the tested profile. |

### Closeout conclusions

The accepted request used the current signed attachment, SOAP 1.2, qualified
PKCS#12 material resolved through `external_secret`, separate logical signing
and mTLS bindings, and persisted safe request/response evidence. The operational
database remains the source for RUC, geographic catalogs, activity, CSC, and
credential references; none was hardcoded into the localization.

### Remaining technical debt

* CSC plaintext storage remains an acknowledged MVP limitation in
  `fiscal.py.csc`; migrate through an approved secret boundary without changing
  QR consumers.
* Stage 8.24B durable pre-POST persistence remains intentionally postponed.
  Ordinary Odoo rollback cannot prove whether a remote POST was accepted after
  a worker crash; ambiguous outcomes must continue through Consulta DE.
* Payload monetary calculations use Decimal internally but the normalized
  payload currently carries numeric floats before deterministic XML
  quantization. Broader currency/precision profiles should be validated before
  reusing this representation for another country.
* Official catalog correctness is operational configuration and was validated
  during this homologation, but catalog synchronization is not automated.
* Cron activation, monitoring, the remaining TEST case matrix, and production
  operations are pending.

### Before starting Costa Rica

Do not generalize Paraguay XML, timezone, QR, CSC, signature, catalog, or VAT
rules into the neutral core. First compare Costa Rica's official contracts.
Potential cross-country candidates requiring evidence are exact-decimal payload
serialization, a generic artifact-current/superseded lifecycle, secret-backed
country parameters, and durable external-call orchestration. These are review
candidates only, not approved abstractions or implementation work.

## Next controlled scenario

The next selected profile is a synchronous B2B cash FE with a real Paraguayan
taxpayer receiver and at least two IVA 10% item groups. Preparation is blocked
until an authorized current receiver RUC/DV, legal name, address and official
geography are supplied. Do not reuse historical fiscal snapshots, the issuer's
RUC, or generated identifiers as substitutes. No document number or CDC has
been consumed for this pending scenario.
