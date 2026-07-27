# SIFEN TEST Homologation Runbook

[Documentation Home](../README.md) -> [Paraguay](README.md) -> Homologation

The repository is TEST-ready, not live-certified. This runbook must not be
interpreted as evidence that SIFEN has accepted a DE.

## Before the first live submission

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
