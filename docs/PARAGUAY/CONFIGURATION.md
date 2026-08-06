# SIFEN TEST Configuration Reference

[Documentation Home](../README.md) -> [Paraguay](README.md) -> Configuration

This is the authoritative configuration checklist for the controlled first
SIFEN TEST submission. Use placeholders only. Never commit a CSC secret,
PKCS#12 file, password, private key, or certificate contents.

## Non-secret fiscal configuration

| Model | Field | Required TEST value |
|---|---|---|
| `fiscal.document` | `environment` | `test` |
| `fiscal.py.issuer` | `ruc`, `ruc_dv` | taxpayer RUC without DV; one-digit DV |
| `fiscal.py.establishment` | `code` | exactly three digits |
| `fiscal.py.point.of.issue` | `code` | exactly three digits |
| `fiscal.py.timbrado` | `number` | TEST timbrado: RUC without DV |
| `fiscal.py.timbrado` | `valid_from` | Form 364 start date |
| `fiscal.adapter.config` | `country_code`, `environment` | `PY`, `test` |
| `fiscal.adapter.config` | `endpoint_base_url` | `https://sifen-test.set.gov.py/de/ws/sync/recibe.wsdl` |
| `fiscal.adapter.config` | `timeout_seconds` | positive integer; runtime default is 30 seconds |
| `fiscal.adapter.config` | `sequence_id` | persistent numeric `dId` sequence, maximum 15 digits |
| `fiscal.py.csc` | `id_csc` | authority-issued identifier preserving leading zeros |

All records must be active and match the document tenant, company, and TEST
environment. The endpoint must be HTTPS and contain no credentials, query, or
fragment.

## Secret references

| Model | Field | Placeholder |
|---|---|---|
| `fiscal.credential` | `provider_type` | `external_secret` |
| `fiscal.credential` | `material_format` | `pkcs12` |
| `fiscal.credential` | `secret_ref` | `file:///run/secrets/sifen-test.p12` |
| `fiscal.credential` | `password_secret_ref` | `file:///run/secrets/sifen-test-password` or `env://SIFEN_TEST_P12_PASSWORD` |
| `fiscal.py.csc` | `csc_value` | deployment-supplied secret; never print or commit |

The PKCS#12 path must be absolute, readable by the Odoo worker, and mounted by
the deployment. Environment-variable names and complete sensitive paths must
not appear in logs or user-facing errors.

## Credential bindings

Create exactly one active `fiscal.adapter.credential.binding` for each role:

* `xml_signing`
* `mutual_tls`

Both bindings may reference the same qualified credential. The separation is
logical: XMLDSig consumes signing material, while the transport consumes the
mTLS identity.

## TEST versus PRODUCTION

The TEST timbrado convention above is not the production electronic timbrado
workflow. Production requires separately authorized configuration and is not
enabled by this TEST-ready baseline. Never copy TEST timbrado or CSC values
into production configuration.

## Validation order

1. Run `PyQualifiedCertificateInstallationValidationService`.
2. Run `PySifenTestReadinessService.check(document=document)`.
3. Run `PySifenSandboxTransport.verify_document_connection(document)`.
4. Continue only when certificate installation, readiness, and preflight pass.

See the [Homologation Runbook](HOMOLOGATION_RUNBOOK.md).

## Local Docker secret integration

The repository compose file passes only the secret reference inputs required by
the Odoo runtime:

```yaml
environment:
  SIFEN_P12_PASSWORD: ${SIFEN_P12_PASSWORD}
volumes:
  - ${HOME}/.secrets/sifen:/run/secrets/sifen:ro
```

Set `SIFEN_P12_PASSWORD` in the host process environment using an approved
secret-loading mechanism before starting Odoo. Do not put its value in the
compose file, `.env` files under version control, shell scripts, or Odoo fields.
Place the PKCS#12 beneath `${HOME}/.secrets/sifen` outside the repository and
reference its container path with `file:///run/secrets/sifen/<name>.p12`.

The mount is read-only and is exposed only to the Odoo service. PostgreSQL does
not receive the password or certificate mount. Deployments may replace this
local pattern with their platform secret mechanism as long as the existing
`file://` and `env://` provider contract remains unchanged.
